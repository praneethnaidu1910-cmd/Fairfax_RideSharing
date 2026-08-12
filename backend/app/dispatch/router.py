from fastapi import APIRouter

from app.dispatch.schemas import Location, MatchRequest, MatchResult

router = APIRouter()


@router.post("/match", response_model=MatchResult)
def match(request: MatchRequest) -> MatchResult:
    return MatchResult(
        driver_id="d1",
        driver_name="Alex",
        driver_location=Location(lat=38.8462, lng=-77.3064),
        distance_miles=0.0,
    )
