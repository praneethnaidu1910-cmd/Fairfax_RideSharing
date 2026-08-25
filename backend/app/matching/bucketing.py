"""Spatial candidate reduction via H3 bucketing.

Turns all-pairs comparison into a hash-bucket lookup
(docs/MATCHING_ALGORITHM.md): two requests only become match candidates
when their origin cells are the same or neighboring AND their destination
cells are the same or neighboring. This reuses the same H3 cell
(app/geo.h3_cell, resolution 8) that Location.coarse_cell() exposes as the
pre-match "coarse area" -- one index, two purposes, not two geocoding
schemes.
"""

from collections import defaultdict
from uuid import UUID

import h3

from app.schemas import RideRequest

# Same-or-adjacent hex ring -- "close enough to share a pickup" per
# docs/MATCHING_ALGORITHM.md, without widening the candidate set too far.
NEIGHBOR_RING = 1

CellIndex = dict[str, list[RideRequest]]


def _origin_cell(request: RideRequest) -> str:
    return request.origin.coarse_cell()


def _destination_cell(request: RideRequest) -> str:
    return request.destination.coarse_cell()


def _build_index(requests: list[RideRequest], cell_of) -> CellIndex:
    index: CellIndex = defaultdict(list)
    for request in requests:
        index[cell_of(request)].append(request)
    return index


def build_indexes(requests: list[RideRequest]) -> tuple[CellIndex, CellIndex]:
    """Origin and destination cell indexes, built once and reused across lookups."""
    return _build_index(requests, _origin_cell), _build_index(requests, _destination_cell)


def candidates_for(
    request: RideRequest,
    origin_index: CellIndex,
    destination_index: CellIndex,
) -> list[RideRequest]:
    """Requests sharing/neighboring both `request`'s origin AND destination cell.

    Excludes `request` itself. A hash-bucket lookup over the prebuilt
    indexes, not an O(n^2) all-pairs scan.
    """
    origin_ring = h3.grid_disk(_origin_cell(request), NEIGHBOR_RING)
    destination_ring = h3.grid_disk(_destination_cell(request), NEIGHBOR_RING)

    origin_matches = {r.id: r for cell in origin_ring for r in origin_index.get(cell, [])}
    destination_matches = {
        r.id for cell in destination_ring for r in destination_index.get(cell, [])
    }

    candidate_ids = origin_matches.keys() & destination_matches
    candidate_ids -= {request.id}
    return [origin_matches[rid] for rid in candidate_ids]


def candidate_groups(requests: list[RideRequest]) -> dict[UUID, list[RideRequest]]:
    """Candidate set for every request, keyed by request id."""
    origin_index, destination_index = build_indexes(requests)
    return {
        request.id: candidates_for(request, origin_index, destination_index)
        for request in requests
    }
