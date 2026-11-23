import asyncio
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.db import make_session_factory
from app.dispatch.router import router as dispatch_router
from app.matching.engine import MatchingEngine
from app.reports import ReportStore
from app.router import router as requests_router
from app.store import RequestStore
from app.web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fresh per app instance (not a module-level singleton) so each
    # `with TestClient(app) as client:` in tests starts from an empty,
    # in-memory matching pool instead of leaking state across tests. The
    # store (TASKS.md #9) is Postgres-backed and DATABASE_URL-driven, so
    # unlike the pool it deliberately does *not* reset per app instance --
    # that's the whole point, a request posted in one process is still
    # there in the next.
    session_factory = make_session_factory()
    app.state.session_factory = session_factory
    app.state.store = RequestStore(session_factory)
    app.state.engine = MatchingEngine(store=app.state.store)
    # Abuse/harassment reports (TASKS.md #16) -- its own store, own table,
    # no relation to the matching pipeline above.
    app.state.report_store = ReportStore(make_session_factory())
    # run_forever() is the incremental-matching pipeline from TASKS.md #5 --
    # started here, per that module's own docstring, so POST /requests can
    # just submit() and let this task do the matching in the background.
    pipeline_task = asyncio.create_task(app.state.engine.run_forever())
    try:
        yield
    finally:
        pipeline_task.cancel()


app = FastAPI(title="Ride-Pooling Matching Engine (Demo)", lifespan=lifespan)


def _json_safe(value: Any) -> Any:
    """Recursively replaces a NaN/+-Infinity float with its str() -- the
    one thing FastAPI's own default RequestValidationError handler
    doesn't do, which crashes the response for it rather than 422ing.

    `Location.lat`/`lng` (here and in app/dispatch/schemas.py) already
    reject an out-of-range coordinate with Field(ge=.., le=..) -- but
    Python's own `json.loads()` (what Starlette's Request.json() uses to
    parse the body) accepts the non-standard `NaN`/`Infinity`/`-Infinity`
    tokens as valid float literals, unlike strict JSON. That value then
    reaches pydantic as a real `float('nan')`, correctly fails the ge/le
    check (any comparison against NaN is False, so it's never mistaken
    for a valid number), and pydantic's own error object faithfully
    echoes the bad value back as `error['input']` -- exactly what every
    other validation error already does, so a caller can see what it
    sent. The crash isn't in any of that: it's that FastAPI's default
    handler builds the 422 body with `jsonable_encoder(exc.errors())`,
    which leaves a NaN/Infinity float untouched (confirmed directly:
    `jsonable_encoder(float('nan'))` returns right back `nan`, not a
    string), and Starlette's JSONResponse renders with
    `json.dumps(..., allow_nan=False)` -- deliberately strict, since a
    literal NaN/Infinity isn't valid JSON for any other parser to read
    back. Confirmed real, not theoretical, with a live TestClient call
    before this fix: POST /requests with
    `{"origin": {"lat": NaN, "lng": -77.3}, ...}` (valid Python-flavored
    JSON, parses cleanly) 500'd -- not even a clean 500, the connection
    itself reset mid-response, since the crash happened *while building*
    the error response, after the status line may already have gone out.
    POST /match (app/dispatch/router.py) hits the identical crash through
    its own Location, since it has the same Field(ge=.., le=..) shape.
    Sanitizing just the one thing that can't survive `allow_nan=False` --
    recursively, since a nested model's error can bury the bad float
    several levels into `error['input']`/`error['ctx']` -- turns this into
    the same clean 422 every other bad coordinate already gets."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe(jsonable_encoder(exc.errors()))},
    )


def parse_allowed_origins(raw: str) -> list[str]:
    """`ALLOWED_ORIGINS` is a comma-separated env var, e.g.
    "https://app.example.com,https://www.example.com". Blank entries
    (including an unset/empty env var) are dropped, so the default is an
    empty list -- restrictive until someone sets it, never a silent
    wildcard."""
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# TASKS.md #18: CORS has to be an explicit, documented choice, not whatever
# FastAPI's defaults happen to be (which is "no CORS middleware at all,"
# i.e. browsers block every cross-origin request).
_allowed_origins = parse_allowed_origins(os.environ.get("ALLOWED_ORIGINS", ""))
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

app.include_router(dispatch_router)
app.include_router(requests_router)
app.include_router(web_router)
app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
)


@app.get("/healthz")
def healthz(request: Request, response: Response) -> dict[str, str]:
    """TASKS.md #18: a hosting platform's health check needs to know the
    app can actually reach its database, not just that the process is
    alive -- an app that's up but can't talk to Postgres is not healthy
    from a deploy's point of view. Reads `request.app` rather than the
    module-level `app` global so this keeps working correctly regardless
    of which app instance actually served the request."""
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "detail": "database unreachable"}
    return {"status": "ok"}
