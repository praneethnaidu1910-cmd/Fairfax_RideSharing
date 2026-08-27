import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.dispatch.router import router as dispatch_router
from app.matching.engine import MatchingEngine
from app.router import router as requests_router
from app.store import RequestStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fresh per app instance (not a module-level singleton) so each
    # `with TestClient(app) as client:` in tests starts from an empty,
    # unmatched pool instead of leaking state across tests.
    app.state.engine = MatchingEngine()
    app.state.store = RequestStore()
    # run_forever() is the incremental-matching pipeline from TASKS.md #5 --
    # started here, per that module's own docstring, so POST /requests can
    # just submit() and let this task do the matching in the background.
    pipeline_task = asyncio.create_task(app.state.engine.run_forever())
    try:
        yield
    finally:
        pipeline_task.cancel()


app = FastAPI(title="Ride-Pooling Matching Engine (Demo)", lifespan=lifespan)

app.include_router(dispatch_router)
app.include_router(requests_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
