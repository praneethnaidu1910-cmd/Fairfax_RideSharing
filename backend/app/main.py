from fastapi import FastAPI

from app.dispatch.router import router as dispatch_router
from app.matching.engine import MatchingEngine

app = FastAPI(title="Ride-Pooling Matching Engine (Demo)")
engine = MatchingEngine()

app.include_router(dispatch_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
