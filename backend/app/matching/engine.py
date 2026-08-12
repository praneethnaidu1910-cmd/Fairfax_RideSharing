"""Matching engine core.

Design: docs/MATCHING_ALGORITHM.md
Build order: TASKS.md (bucketing -> scoring -> greedy batch match ->
incremental match). Each piece lands as its own task; this file starts as
a stub so later tasks have a clear seam to fill in rather than a blank page.
"""

from app.schemas import MatchGroup, RideRequest


class MatchingEngine:
    def __init__(self) -> None:
        self._unmatched: list[RideRequest] = []

    def match_batch(self, requests: list[RideRequest]) -> list[MatchGroup]:
        raise NotImplementedError("TASKS.md #4: greedy matching engine")

    def on_new_request(self, request: RideRequest) -> list[MatchGroup]:
        raise NotImplementedError("TASKS.md #5: incremental matching")
