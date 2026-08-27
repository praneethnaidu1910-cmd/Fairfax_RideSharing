"""Simulator + minimal live view (TASKS.md #8).

Replays app/sample_data.py's SAMPLE_REQUESTS against a *running* server
(`uvicorn app.main:app --reload` in another terminal) with staggered,
compressed timing -- "requests trickle in over the evening," per
docs/MATCHING_ALGORITHM.md's real-time section, compressed into a run
that's quick to watch instead of hours long. A second task subscribes to
`WS /matches` the whole time and prints each match as it arrives, so match
events show up interleaved with the posts that produced them, not batched
at the end -- proof the incremental pipeline (TASKS.md #5) is actually
real-time and not a batch job wearing a websocket.

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


async def _subscribe(
    base_url: str, rider_names: dict, start: float, connected: asyncio.Event, stop: asyncio.Event
) -> None:
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/matches"
    async with websockets.connect(ws_url) as websocket:
        connected.set()
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            match = json.loads(raw)
            names = [rider_names.get(rid, rid) for rid in match["request_ids"]]
            print(
                f"[{_elapsed(start)}] MATCH  {names[0]} <-> {names[1]}  "
                f"score={match['score']:.2f}  ({match['reason']})"
            )


async def _publish(client: httpx.AsyncClient, rider_names: dict, start: float, total_seconds: float) -> None:
    gap = total_seconds / max(len(SAMPLE_REQUESTS) - 1, 1)
    for index, request in enumerate(SAMPLE_REQUESTS):
        response = await client.post("/requests", json=_payload(request))
        response.raise_for_status()
        rider_names[response.json()["id"]] = request.rider_id
        print(
            f"[{_elapsed(start)}] POSTED {request.rider_id}: "
            f"{request.origin.lat:.4f},{request.origin.lng:.4f} -> "
            f"{request.destination.lat:.4f},{request.destination.lng:.4f}"
        )
        if index < len(SAMPLE_REQUESTS) - 1:
            await asyncio.sleep(gap)


async def run(base_url: str, total_seconds: float, settle_seconds: float) -> None:
    start = time.monotonic()
    rider_names: dict = {}
    connected = asyncio.Event()
    stop = asyncio.Event()

    subscriber = asyncio.create_task(_subscribe(base_url, rider_names, start, connected, stop))
    connected_waiter = asyncio.create_task(connected.wait())
    # Race the "connected" signal against the subscriber task itself finishing
    # early (e.g. connection refused) -- otherwise a dead server just hangs
    # here forever instead of raising, since connected.set() would never come.
    done, _pending = await asyncio.wait({subscriber, connected_waiter}, return_when=asyncio.FIRST_COMPLETED)
    if subscriber in done:
        connected_waiter.cancel()
        subscriber.result()  # re-raises whatever killed the subscriber
    connected_waiter.cancel()

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        await _publish(client, rider_names, start, total_seconds)

    await asyncio.sleep(settle_seconds)
    stop.set()
    await subscriber


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
