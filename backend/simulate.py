"""Simulator + minimal live view (TASKS.md #8).

Replays app/sample_data.py's SAMPLE_REQUESTS against a *running* server
(`uvicorn app.main:app --reload` in another terminal) with staggered,
compressed timing -- "requests trickle in over the evening," per
docs/MATCHING_ALGORITHM.md's real-time section, compressed into a run
that's quick to watch instead of hours long. One filtered `WS /matches`
connection per posted request (see _publish_and_watch()'s own docstring --
this used to be a single global connection, until that turned out to be a
real, exploitable privacy leak, not just this script's own concern) prints
each match as it arrives, so match events show up interleaved with the
posts that produced them, not batched at the end -- proof the incremental
pipeline (TASKS.md #5) is actually real-time and not a batch job wearing a
websocket.

Usage, from the repo root, with the server already running:

    python backend/simulate.py
"""

import argparse
import asyncio
import json
import sys
import time

import httpx
import websockets

from app.sample_data import SAMPLE_REQUESTS

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
# Spread the whole sample dataset's posts across ~15s by default -- long
# enough to see requests trickle in rather than burst, short enough to
# watch in one sitting.
DEFAULT_SECONDS = 15.0
# Extra time to keep the websocket open after the last POST, since
# on_new_request() runs on run_forever()'s next queue-drain, a scheduling
# hop after the POST response already came back.
DEFAULT_SETTLE_SECONDS = 2.0


def _payload(request) -> dict:
    return {
        "rider_id": request.rider_id,
        "origin": {"lat": request.origin.lat, "lng": request.origin.lng},
        "destination": {"lat": request.destination.lat, "lng": request.destination.lng},
        "schedule": request.schedule.model_dump(mode="json"),
        "seats_needed": request.seats_needed,
        "contact": request.contact,
    }


def _elapsed(start: float) -> str:
    return f"{time.monotonic() - start:6.2f}s"


async def _publish_and_watch(
    client: httpx.AsyncClient,
    ws_url: str,
    rider_names: dict,
    start: float,
    total_seconds: float,
    printed: set,
    stop: asyncio.Event,
) -> list["asyncio.Task[None]"]:
    """Posts the whole sample dataset, opening one filtered /matches
    connection per request along the way.

    GET /matches now only ever forwards a match that actually names the id
    a connection registers for (TASKS.md's fix for a real leak: it used to
    broadcast every match to every connection, no auth required) -- so
    there's no single global feed left to watch the whole run from one
    socket the way this used to. One connection per posted request plus
    `printed` (shared across all of them, see _drain()) gets back to the
    same "every match prints once, as it happens" behavior this had before.

    Each connection is opened -- and so already subscribed server-side --
    *before* its own request is posted, not after: a match involving that
    request can be produced essentially immediately, inside the same
    event-loop hop that processes the POST, and nothing racing that gap is
    lost as long as the subscription itself started first (see
    app/router.py's stream_matches() for the server side of this).
    """
    gap = total_seconds / max(len(SAMPLE_REQUESTS) - 1, 1)
    watchers: list[asyncio.Task[None]] = []
    for index, request in enumerate(SAMPLE_REQUESTS):
        websocket = await websockets.connect(ws_url)
        response = await client.post("/requests", json=_payload(request))
        response.raise_for_status()
        request_id = response.json()["id"]
        rider_names[request_id] = request.rider_id
        print(
            f"[{_elapsed(start)}] POSTED {request.rider_id}: "
            f"{request.origin.lat:.4f},{request.origin.lng:.4f} -> "
            f"{request.destination.lat:.4f},{request.destination.lng:.4f}"
        )
        await websocket.send(json.dumps({"request_id": request_id}))
        watchers.append(
            asyncio.create_task(_drain(websocket, rider_names, start, printed, stop))
        )
        if index < len(SAMPLE_REQUESTS) - 1:
            await asyncio.sleep(gap)
    return watchers


async def _drain(
    websocket, rider_names: dict, start: float, printed: set, stop: asyncio.Event
) -> None:
    """Reads one request's filtered match feed until `stop` is set, printing
    any match not already printed by the *other* party's own connection --
    a match arrives on both sides of a pair's feeds, so `printed` (a set of
    `frozenset(request_ids)`, shared across every _drain() call this run)
    is what keeps it from printing twice."""
    try:
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            match = json.loads(raw)
            key = frozenset(match["request_ids"])
            if key in printed:
                continue
            printed.add(key)
            names = [rider_names.get(rid, rid) for rid in match["request_ids"]]
            print(
                f"[{_elapsed(start)}] MATCH  {names[0]} <-> {names[1]}  "
                f"score={match['score']:.2f}  ({match['reason']})"
            )
    finally:
        await websocket.close()


async def run(base_url: str, total_seconds: float, settle_seconds: float) -> None:
    start = time.monotonic()
    rider_names: dict = {}
    printed: set = set()
    stop = asyncio.Event()
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/matches"

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        watchers = await _publish_and_watch(
            client, ws_url, rider_names, start, total_seconds, printed, stop
        )

    await asyncio.sleep(settle_seconds)
    stop.set()
    for watcher in watchers:
        await watcher


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="running server's base URL")
    parser.add_argument(
        "--seconds", type=float, default=DEFAULT_SECONDS,
        help="compressed total time to spread the sample dataset's posts over",
    )
    parser.add_argument(
        "--settle", type=float, default=DEFAULT_SETTLE_SECONDS,
        help="extra seconds to keep listening after the last post",
    )
    args = parser.parse_args()

    print(
        f"Replaying {len(SAMPLE_REQUESTS)} sample requests against {args.base_url} "
        f"over ~{args.seconds:.0f}s ..."
    )
    try:
        asyncio.run(run(args.base_url, args.seconds, args.settle))
    except (httpx.ConnectError, OSError) as exc:
        print(
            f"Couldn't reach {args.base_url} ({exc}). "
            "Start the server first: cd backend && uvicorn app.main:app --reload",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
