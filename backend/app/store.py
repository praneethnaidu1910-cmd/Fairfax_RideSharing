"""In-memory store of every RideRequest ever created, keyed by id.

Separate from MatchingEngine._unmatched, which only tracks requests that
haven't matched yet (purely for bucketing candidates) and drops a request
the moment it matches. GET /requests -- and TASKS.md #7's GET
/requests/{id} -- need every request regardless of status, so this keeps
its own full list rather than reaching into the engine's internals.
"""

from uuid import UUID

from app.schemas import RequestStatus, RideRequest


class RequestStore:
    def __init__(self) -> None:
        self._requests: dict[UUID, RideRequest] = {}

    def add(self, request: RideRequest) -> None:
        self._requests[request.id] = request

    def get(self, request_id: UUID) -> RideRequest | None:
        return self._requests.get(request_id)

    def list_open(self) -> list[RideRequest]:
        return [r for r in self._requests.values() if r.status == RequestStatus.OPEN]
