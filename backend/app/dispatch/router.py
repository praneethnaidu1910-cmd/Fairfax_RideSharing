from fastapi import APIRouter, HTTPException

from app.dispatch.matching import find_nearest_available_driver
from app.dispatch.sample_drivers import SAMPLE_DRIVERS
from app.dispatch.schemas import MatchRequest, MatchResult

router = APIRouter()


@router.post("/match", response_model=MatchResult)
def match(request: MatchRequest) -> MatchResult:
    result = find_nearest_available_driver(request.rider_location, SAMPLE_DRIVERS)
    if result is None:
        raise HTTPException(status_code=404, detail="No available drivers")

    driver, distance = result
    return MatchResult(
        driver_id=driver.id,
        driver_name=driver.name,
        driver_location=driver.location,
        distance_miles=round(distance, 3),
    )
