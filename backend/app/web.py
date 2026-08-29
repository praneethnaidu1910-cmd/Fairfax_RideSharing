"""Minimal server-rendered frontend (TASKS.md #11): a plain HTML form that
posts a new ride request, and a browse page listing open ones -- no
framework, no build step, no separate frontend server. FastAPI serves the
templates directly (Jinja2Templates), the same app that serves the JSON API.

Deliberately reuses app/router.py's create_request() instead of
re-implementing request creation here, so this is one more caller of the
same store/engine pipeline, not a second intake path with its own
validation/privacy rules.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.privacy import to_public
from app.router import create_request
from app.schemas import Location, OneOffSchedule, RecurringSchedule, RideRequestCreate

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/new")
def new_request_form(request: Request):
    return templates.TemplateResponse(request, "new_request.html", {"form": None, "error": None})


@router.post("/new")
async def submit_new_request(
    request: Request,
    rider_id: str = Form(...),
    origin_place: str = Form(...),
    origin_lat: Optional[str] = Form(None),
    origin_lng: Optional[str] = Form(None),
    destination_place: str = Form(...),
    destination_lat: Optional[str] = Form(None),
    destination_lng: Optional[str] = Form(None),
    schedule_type: str = Form(...),
    earliest_departure: Optional[str] = Form(None),
    latest_departure: Optional[str] = Form(None),
    weekdays: list[int] = Form([]),
    earliest_departure_time: Optional[str] = Form(None),
    latest_departure_time: Optional[str] = Form(None),
    seats_needed: int = Form(1),
    contact: str = Form(...),
):
    # Re-render with whatever the rider typed on any failure below, so a
    # mistake doesn't mean starting the form over from scratch.
    form_values = {
        "rider_id": rider_id,
        "origin_place": origin_place,
        "origin_lat": origin_lat,
        "origin_lng": origin_lng,
        "destination_place": destination_place,
        "destination_lat": destination_lat,
        "destination_lng": destination_lng,
        "schedule_type": schedule_type,
        "earliest_departure": earliest_departure,
        "latest_departure": latest_departure,
        "weekdays": weekdays,
        "earliest_departure_time": earliest_departure_time,
        "latest_departure_time": latest_departure_time,
        "seats_needed": seats_needed,
        "contact": contact,
    }

    def _error(message: str):
        return templates.TemplateResponse(
            request,
            "new_request.html",
            {"form": form_values, "error": message},
            status_code=400,
        )

    if not origin_lat or not origin_lng:
        return _error(f'Could not resolve pickup place "{origin_place}" -- pick a more specific name.')
    if not destination_lat or not destination_lng:
        return _error(
            f'Could not resolve destination place "{destination_place}" -- pick a more specific name.'
        )

    try:
        if schedule_type == "recurring":
            schedule = RecurringSchedule(
                weekdays=weekdays,
                earliest_departure_time=earliest_departure_time,
                latest_departure_time=latest_departure_time,
            )
        else:
            schedule = OneOffSchedule(
                earliest_departure=earliest_departure,
                latest_departure=latest_departure,
            )

        payload = RideRequestCreate(
            rider_id=rider_id,
            origin=Location(lat=float(origin_lat), lng=float(origin_lng)),
            destination=Location(lat=float(destination_lat), lng=float(destination_lng)),
            schedule=schedule,
            seats_needed=seats_needed,
            contact=contact,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return _error(f"Couldn't post that request: {exc}")

    await create_request(payload, request)
    return RedirectResponse(url="/browse", status_code=303)


@router.get("/browse")
def browse_requests(request: Request):
    open_requests = [to_public(r) for r in request.app.state.store.list_open()]
    return templates.TemplateResponse(request, "browse.html", {"requests": open_requests})
