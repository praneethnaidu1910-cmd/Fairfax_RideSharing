"""Minimal server-rendered frontend: a plain HTML form that posts a new
ride request (TASKS.md #11), a browse page listing open ones (#11), and a
per-rider "waiting for a match" page that updates live over the existing
/matches WebSocket and reveals the counterpart the moment a match is found
(#12) -- no framework, no build step, no separate frontend server. FastAPI
serves the templates directly (Jinja2Templates), the same app that serves
the JSON API.

Deliberately reuses app/router.py's create_request() instead of
re-implementing request creation here, so this is one more caller of the
same store/engine pipeline, not a second intake path with its own
validation/privacy rules.
"""

from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.privacy import to_list_item, to_public
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
    # Both of these used to be typed `list[int]`/`int` straight on the Form
    # parameter -- which meant FastAPI/pydantic coerced them to int *before*
    # this function (and its own try/except below) ever ran at all. A
    # malformed value (a non-numeric weekday, or non-numeric seats_needed)
    # never reached this function's own error handling; it 422'd with
    # FastAPI's raw JSON error body instead of this endpoint's own
    # "Couldn't post that request: ..." HTML re-render every *other*
    # malformed field on this exact form gets (bad place name, bad
    # schedule, empty rider_id/contact). Confirmed real, not theoretical,
    # with a live TestClient call before this fix: POST /new with
    # seats_needed="abc" (a rider mistyping the seats field, or any
    # non-browser client) returned a bare `{"detail":[{"type":
    # "int_parsing",...}]}` JSON body, not the form page -- and the exact
    # same thing happened for weekdays=["abc"]. Taking them in as plain
    # strings and parsing them inside the try block below, same pattern as
    # origin_lat/origin_lng's own float() calls just beneath it, routes a
    # bad value through the one error path this endpoint already has
    # instead of a second, inconsistent one FastAPI provides for free.
    weekdays: list[str] = Form([]),
    earliest_departure_time: Optional[str] = Form(None),
    latest_departure_time: Optional[str] = Form(None),
    seats_needed: str = Form("1"),
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
        # Blank seats_needed (a cleared number field) keeps the same
        # "default to 1" behavior the old `int = Form(1)` typing gave it
        # for free; anything present but non-numeric is a real mistake that
        # belongs in the error below, same as a bad weekday value.
        parsed_seats_needed = int(seats_needed) if seats_needed.strip() else 1
        parsed_weekdays = [int(day) for day in weekdays]

        if schedule_type == "recurring":
            schedule = RecurringSchedule(
                weekdays=parsed_weekdays,
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
            seats_needed=parsed_seats_needed,
            contact=contact,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return _error(f"Couldn't post that request: {exc}")

    created = await create_request(payload, request)
    # TASKS.md #12's live-match page needs to know "my own request id" to
    # watch for -- redirecting here (instead of straight to /browse) is
    # what hands it over, as a URL the rider can bookmark/reload.
    return RedirectResponse(url=f"/mine/{created.id}", status_code=303)


@router.get("/browse")
def browse_requests(request: Request):
    # to_list_item(), not to_public() -- this page is exactly the
    # "anonymous browser scrolling the open list" case RideRequestListItem's
    # own docstring describes; the template never renders an id today, but
    # the data this handler builds shouldn't carry one to begin with.
    open_requests = [to_list_item(r) for r in request.app.state.store.list_open()]
    return templates.TemplateResponse(request, "browse.html", {"requests": open_requests})


@router.get("/mine/{request_id}")
def my_request_status(request_id: UUID, request: Request):
    """TASKS.md #12: the rider's own "waiting for a match" page. Opens a
    WebSocket to /matches client-side (static/live.js) and shows the
    reveal the moment a match involving this request arrives -- no
    reload. If the request is already matched by the time this page loads
    (e.g. a reload after the fact), render the reveal server-side instead
    of making the rider wait on a WebSocket event that already happened.

    A request that's no longer OPEN but also never matched -- cancelled
    (TASKS.md #15) or expired (TASKS.md #14) -- used to render exactly the
    same "Waiting for a match... this page updates itself" message as a
    genuinely still-open one, which is actively wrong for a cancel: the
    poster who just cancelled their own request, via the API, would reload
    this page and be told it's still waiting, and the page would open a
    WebSocket that can never receive a match for it. `status` (the same
    computed value GET /requests already reports via to_public(), so
    "expired" here means the same thing it means there) lets the template
    tell the two states apart.
    """
    store = request.app.state.store
    mine = store.get(request_id)
    if mine is None:
        raise HTTPException(status_code=404, detail="request not found")

    reveal = None
    if mine.matched_with is not None:
        counterpart = store.get(mine.matched_with)
        if counterpart is not None:
            reveal = counterpart

    return templates.TemplateResponse(
        request,
        "mine.html",
        {"request_id": request_id, "reveal": reveal, "status": to_public(mine).status.value},
    )
