"""Greedy batch matching engine.

Design: docs/MATCHING_ALGORITHM.md's "Grouping" section, baseline pass --
"sort candidate pairs by score descending, assign greedily while
respecting capacity, no backtracking." Groups larger than 2 are that
doc's explicit "upgrade, if time allows" phase (min-cost assignment /
local search) and aren't built here; match_batch() only ever produces
pairs, which is why MatchGroup.request_ids is always length 2 for now
even though the schema allows more.

Build order (TASKS.md): bucketing (#2) -> scoring (#3) -> this file (#4),
plus incremental matching (#5) below.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from app.matching.bucketing import build_indexes, candidate_groups, candidates_for
from app.matching.scoring import (
    capacity_fits,
    compatibility_score,
    directional_score,
    expand_schedule,
    explain_match,
    is_expired,
)
from app.schemas import MatchGroup, OneOffSchedule, RequestStatus, RideRequest

if TYPE_CHECKING:
    from app.store import RequestStore

logger = logging.getLogger(__name__)

# A typical sedan's usable passenger capacity for a shared ride -- the
# "vehicle/trip capacity" docs/MATCHING_ALGORITHM.md's hard constraint
# refers to. There's no separate driver/vehicle entity in this rider-to-
# rider pooling model (that's the unrelated dispatch side-module), so this
# stands in for "how many people can realistically share one car." Named/
# tunable like scoring.py's weights, not a magic number.
DEFAULT_VEHICLE_CAPACITY = 4

# Below this, two requests' origin->destination bearings differ by more
# than 90 degrees -- headed different enough ways that no amount of
# spatial/temporal closeness makes them a real match (docs/
# MATCHING_ALGORITHM.md's "opposite direction" false-positive). Treated as
# a hard cutoff alongside capacity, not folded into the weighted score, so
# a pair can't buy its way past it with a tight time window.
MIN_DIRECTIONAL_SCORE = 0.5


class MatchingEngine:
    def __init__(
        self,
        vehicle_capacity: int = DEFAULT_VEHICLE_CAPACITY,
        store: Optional["RequestStore"] = None,
    ) -> None:
        self._unmatched: list[RideRequest] = []
        self.vehicle_capacity = vehicle_capacity
        # Optional (TASKS.md #9): when set, persists a request's status/
        # matched_with the moment this engine flips them, so a match
        # survives a restart the same way the original open request does.
        # None everywhere the engine's own tests construct it directly --
        # no store, no persistence, same in-memory-only behavior as before.
        self._store = store
        # The real-time pipeline docs/MATCHING_ALGORITHM.md describes:
        # requests trickle in via `incoming` (fed by submit(), drained by
        # run_forever()), and each resulting match is published to
        # `matches` for a subscriber -- TASKS.md #6's WebSocket -- to read.
        self.incoming: "asyncio.Queue[RideRequest]" = asyncio.Queue()
        self.matches: "asyncio.Queue[MatchGroup]" = asyncio.Queue()
        # Real fan-out for TASKS.md #12: `self.matches` alone only lets one
        # reader ever drain a given match (a second simultaneous WS
        # connection would just starve, per the gap router.py's own
        # docstring used to flag). Each subscribe() call hands out an
        # independent queue that run_forever() also feeds, so N connected
        # clients each get a copy of every match, not N-1 of them starving.
        self._subscribers: list["asyncio.Queue[MatchGroup]"] = []

    def match_batch(self, requests: list[RideRequest]) -> list[MatchGroup]:
        """Score every bucketed candidate pair once, sort descending, then
        assign greedily (no backtracking): the first, highest-scoring pair
        for each request wins, and both requests drop out of consideration
        for the rest of this pass. Flips both requests' `status` to
        `matched` in place -- the only place a batch run does that."""
        # A still-OPEN request whose one-off window has already passed
        # (TASKS.md #14, scoring.is_expired) is unmatchable -- it displays
        # as `expired` (app/privacy.py's to_public()) and shouldn't win a
        # slot a still-live request could use.
        open_requests = [
            r for r in requests if r.status == RequestStatus.OPEN and not is_expired(r)
        ]
        by_id = {r.id: r for r in open_requests}
        candidates = candidate_groups(open_requests)

        scored_pairs: list[tuple[float, UUID, UUID, OneOffSchedule, OneOffSchedule]] = []
        seen_pairs: set[frozenset[UUID]] = set()
        for request in open_requests:
            windows_a = expand_schedule(request.schedule)
            for candidate in candidates[request.id]:
                pair_key = frozenset((request.id, candidate.id))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                if not capacity_fits(request, candidate, self.vehicle_capacity):
                    continue
                if directional_score(request, candidate) < MIN_DIRECTIONAL_SCORE:
                    continue

                windows_b = expand_schedule(candidate.schedule)
                # Track which window pair actually produced the best score,
                # not just the score itself -- explain_match() below needs
                # the real overlapping windows, not an arbitrary one.
                best_score, best_window_a, best_window_b = None, None, None
                for window_a in windows_a:
                    for window_b in windows_b:
                        score = compatibility_score(request, candidate, window_a, window_b)
                        if best_score is None or score > best_score:
                            best_score, best_window_a, best_window_b = score, window_a, window_b
                scored_pairs.append(
                    (best_score, request.id, candidate.id, best_window_a, best_window_b)
                )

        scored_pairs.sort(key=lambda scored: scored[0], reverse=True)

        matched_ids: set[UUID] = set()
        matches: list[MatchGroup] = []
        for score, a_id, b_id, window_a, window_b in scored_pairs:
            if a_id in matched_ids or b_id in matched_ids:
                continue
            matched_ids.add(a_id)
            matched_ids.add(b_id)
            matched_at = datetime.utcnow()
            by_id[a_id].status = RequestStatus.MATCHED
            by_id[b_id].status = RequestStatus.MATCHED
            by_id[a_id].matched_with = b_id
            by_id[b_id].matched_with = a_id
            # TASKS.md #17 needs to know *when* a request became
            # unmatchable, not just that it did -- this is what
            # app.retention.terminal_at() reads for a MATCHED request.
            by_id[a_id].status_changed_at = matched_at
            by_id[b_id].status_changed_at = matched_at
            if self._store is not None:
                self._store.save(by_id[a_id])
                self._store.save(by_id[b_id])
            matches.append(
                MatchGroup(
                    request_ids=[a_id, b_id],
                    score=score,
                    reason=explain_match(by_id[a_id], by_id[b_id], window_a, window_b),
                )
            )
        return matches

    def on_new_request(self, request: RideRequest) -> list[MatchGroup]:
        """Incremental counterpart to match_batch(): scores `request`
        against only its own H3 neighborhood within the running
        self._unmatched pool (bucketing.candidates_for over just that
        pool, not the full open-request set) -- "new request -> re-run
        bucketing/scoring only against relevant existing unmatched
        requests," per docs/MATCHING_ALGORITHM.md's real-time section.

        A new request can match at most one existing one, so this returns
        a list of zero or one MatchGroup (list, not Optional, to keep the
        same return shape as match_batch()). On a match, both requests'
        status flips to `matched` and the matched candidate leaves
        self._unmatched; otherwise `request` joins the pool for future
        calls to match against.
        """
        # Same expiry gate as match_batch(): an already-expired request
        # (TASKS.md #14) never joins the pool or wins a match, and an
        # existing pool member that's since expired while waiting is
        # skipped as a candidate rather than matched against.
        if request.status != RequestStatus.OPEN or is_expired(request):
            return []

        origin_index, destination_index = build_indexes(self._unmatched)
        candidates = candidates_for(request, origin_index, destination_index)
        windows_new = expand_schedule(request.schedule)

        best_score: Optional[float] = None
        best_candidate: Optional[RideRequest] = None
        best_window_new: Optional[OneOffSchedule] = None
        best_window_existing: Optional[OneOffSchedule] = None
        for candidate in candidates:
            if is_expired(candidate):
                continue
            if not capacity_fits(request, candidate, self.vehicle_capacity):
                continue
            if directional_score(request, candidate) < MIN_DIRECTIONAL_SCORE:
                continue
            windows_existing = expand_schedule(candidate.schedule)
            for window_a in windows_new:
                for window_b in windows_existing:
                    score = compatibility_score(request, candidate, window_a, window_b)
                    if best_score is None or score > best_score:
                        best_score, best_candidate = score, candidate
                        best_window_new, best_window_existing = window_a, window_b

        if best_candidate is None:
            self._unmatched.append(request)
            return []

        # best_candidate came from the self._unmatched pool read above, but
        # scoring it took a while (every candidate in the bucket, every
        # window pair) with nothing holding this up -- and
        # POST /requests/{id}/cancel's cancel_request() (app/router.py) is a
        # sync FastAPI route, which Starlette runs on a threadpool worker,
        # not this event loop, so it can run its own store.save(CANCELLED)
        # + remove_from_pool() for this exact best_candidate at any point
        # during that scoring. Without this recheck, the code below would
        # still flip best_candidate back to MATCHED and store.save() it --
        # silently reverting a cancel the poster already got a 200 for, and
        # self._unmatched.remove(best_candidate) right after would raise
        # ValueError, since remove_from_pool() already dropped it. Confirmed
        # this was real, not theoretical: a script that pauses
        # on_new_request() mid-scoring (monkeypatching this module's
        # compatibility_score), runs the real cancel_request() sequence
        # against best_candidate from another thread in that window, then
        # lets scoring finish -- without this check, best_candidate's
        # stored status came back MATCHED (not CANCELLED) and
        # self._unmatched.remove() raised.
        if self._store is not None:
            current_candidate = self._store.get(best_candidate.id)
            if current_candidate is not None and current_candidate.status != RequestStatus.OPEN:
                self._unmatched = [r for r in self._unmatched if r.id != best_candidate.id]
                self._unmatched.append(request)
                return []

        matched_at = datetime.utcnow()
        request.status = RequestStatus.MATCHED
        best_candidate.status = RequestStatus.MATCHED
        request.matched_with = best_candidate.id
        best_candidate.matched_with = request.id
        request.status_changed_at = matched_at
        best_candidate.status_changed_at = matched_at
        if self._store is not None:
            self._store.save(request)
            self._store.save(best_candidate)
        self._unmatched.remove(best_candidate)
        return [
            MatchGroup(
                request_ids=[request.id, best_candidate.id],
                score=best_score,
                reason=explain_match(request, best_candidate, best_window_new, best_window_existing),
            )
        ]

    async def submit(self, request: RideRequest) -> None:
        """Queue-side entry point for a request arriving in real time --
        puts it on `incoming` for run_forever() to pick up."""
        await self.incoming.put(request)

    def remove_from_pool(self, request_id: UUID) -> None:
        """Drops `request_id` from self._unmatched if it's sitting there
        (TASKS.md #15's cancel path): store.get() hands the cancel endpoint
        a fresh RideRequest instance built from the DB row, not the same
        object this pool holds, so flipping that fresh copy's status alone
        wouldn't stop a still-pooled request from winning a future match --
        this is what actually does. A no-op if the request was never
        pooled (already matched, or still sitting in `incoming`)."""
        self._unmatched = [r for r in self._unmatched if r.id != request_id]

    def subscribe(self) -> "asyncio.Queue[MatchGroup]":
        """Registers a new queue that receives a copy of every future match
        alongside the shared `self.matches` queue -- call this once per
        WebSocket connection (TASKS.md #12 needs two simultaneous tabs to
        both see the same match) and unsubscribe() when that connection
        closes."""
        queue: "asyncio.Queue[MatchGroup]" = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[MatchGroup]") -> None:
        self._subscribers.remove(queue)

    async def run_forever(self) -> None:
        """Drain `incoming` one request at a time, running each through
        on_new_request() (never a full recompute) and publishing any
        resulting match to `matches` plus every subscribe()'d queue. Runs
        until cancelled -- intended to be launched as a background task,
        e.g. by TASKS.md #6's app startup and by #8's simulator.

        on_new_request() failing for one request (e.g. a transient DB
        error from store.save()) must not take the whole loop down -- this
        task is started once, at app startup, with nothing that restarts
        it, so an unguarded exception here used to propagate out of
        run_forever() entirely and silently end the background task for
        good: every request submitted after that point would just sit in
        `incoming` forever, never matched, with POST /requests still
        returning 201 as if nothing were wrong. Catching broad Exception
        and logging it, instead of letting it escape the loop, keeps the
        pipeline itself alive for every request after the failing one --
        the one request involved in the failure is dropped from this
        pass, not retried.

        Also re-checks the request's status against the store (when one is
        configured) before touching it at all. submit() hands this loop
        the exact RideRequest object POST /requests built, and that object
        sits in `incoming` until this loop gets around to it -- if
        POST /requests/{id}/cancel runs in that window, it mutates a
        *different*, freshly-fetched RideRequest instance (store.get()
        always returns a fresh one) and calls remove_from_pool(), which
        only drops a request that's already in self._unmatched. A request
        still waiting in `incoming` isn't in self._unmatched yet, so
        remove_from_pool() was a no-op for it, and on_new_request() would
        go on to match (and store.save() back to MATCHED) a request the
        store already had as CANCELLED -- confirmed this was real, not
        theoretical, before this fix: submit a request, cancel it via the
        store the same way the cancel endpoint does, then let this loop
        reach it, and the cancelled row came back MATCHED. Treating
        anything that's no longer OPEN in the store as "already handled
        elsewhere" and skipping it closes that gap.
        """
        while True:
            request = await self.incoming.get()
            try:
                if self._store is not None:
                    current = self._store.get(request.id)
                    if current is not None and current.status != RequestStatus.OPEN:
                        continue
                for match in self.on_new_request(request):
                    await self.matches.put(match)
                    for subscriber in self._subscribers:
                        await subscriber.put(match)
            except Exception:
                logger.exception(
                    "on_new_request failed for request %s -- dropping it, pipeline stays up",
                    request.id,
                )
            finally:
                self.incoming.task_done()
