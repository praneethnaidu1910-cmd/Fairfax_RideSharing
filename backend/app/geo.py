"""Shared H3 indexing.

One H3 cell computation, reused for two purposes (per TASKS.md #1/#2): the
"coarse area" shown to other users pre-match, and the bucketing key used for
candidate reduction in the matching engine. Keeping it here means both call
the same function instead of growing two geocoding schemes.
"""

import h3

# Resolution ~8 (~460m edge) per docs/MATCHING_ALGORITHM.md's bucketing design.
COARSE_RESOLUTION = 8


def h3_cell(lat: float, lng: float, resolution: int = COARSE_RESOLUTION) -> str:
    return h3.latlng_to_cell(lat, lng, resolution)
