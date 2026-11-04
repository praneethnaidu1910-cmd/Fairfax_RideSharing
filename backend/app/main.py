import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
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
