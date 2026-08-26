"""Greedy batch matching engine.

Design: docs/MATCHING_ALGORITHM.md's "Grouping" section, baseline pass --
"sort candidate pairs by score descending, assign greedily while
respecting capacity, no backtracking." Groups larger than 2 are that
doc's explicit "upgrade, if time allows" phase (min-cost assignment /
local search) and aren't built here; match_batch() only ever produces
pairs, which is why MatchGroup.request_ids is always length 2 for now
even though the schema allows more.

Build order (TASKS.md): bucketing (#2) -> scoring (#3) -> this file (#4).
"""

from uuid import UUID

from app.matching.bucketing import candidate_groups
from app.matching.scoring import (
    capacity_fits,
    compatibility_score,
    directional_score,
    expand_schedule,
)
from app.schemas import MatchGroup, RequestStatus, RideRequest

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
    def __init__(self, vehicle_capacity: int = DEFAULT_VEHICLE_CAPACITY) -> None:
        self._unmatched: list[RideRequest] = []
        self.vehicle_capacity = vehicle_capacity

    def match_batch(self, requests: list[RideRequest]) -> list[MatchGroup]:
        """Score every bucketed candidate pair once, sort descending, then
        assign greedily (no backtracking): the first, highest-scoring pair
        for each request wins, and both requests drop out of consideration
        for the rest of this pass. Flips both requests' `status` to
        `matched` in place -- the only place a batch run does that."""
        open_requests = [r for r in requests if r.status == RequestStatus.OPEN]
        by_id = {r.id: r for r in open_requests}
        candidates = candidate_groups(open_requests)

        scored_pairs: list[tuple[float, UUID, UUID]] = []
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
                best_score = max(
                    compatibility_score(request, candidate, window_a, window_b)
                    for window_a in windows_a
                    for window_b in windows_b
                )
                scored_pairs.append((best_score, request.id, candidate.id))

        scored_pairs.sort(key=lambda scored: scored[0], reverse=True)

        matched_ids: set[UUID] = set()
        matches: list[MatchGroup] = []
        for score, a_id, b_id in scored_pairs:
            if a_id in matched_ids or b_id in matched_ids:
                continue
            matched_ids.add(a_id)
            matched_ids.add(b_id)
            by_id[a_id].status = RequestStatus.MATCHED
            by_id[b_id].status = RequestStatus.MATCHED
            matches.append(
                MatchGroup(
                    request_ids=[a_id, b_id],
                    score=score,
                    reason="shared corridor, overlapping window, capacity fits",
                )
            )
        return matches

    def on_new_request(self, request: RideRequest) -> list[MatchGroup]:
        raise NotImplementedError("TASKS.md #5: incremental matching")
