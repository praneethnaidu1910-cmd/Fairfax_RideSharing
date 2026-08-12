# Scope — Ride-Pooling Matching Engine (Demo)

## The problem, stated honestly

Around 1,000 international students/professionals in Fairfax, Ashburn, Herndon,
Chantilly, Reston, and the wider DC area coordinate rides through a WhatsApp
group. A typical night looks like: someone posts "leaving Dulles 9pm need 2
seats," five minutes later someone else posts "IAD arrival 9:15, anyone
going towards Fairfax," and nobody sees both messages in time. Matches happen
by luck and manual scrolling, not by anyone actually comparing routes.

This project is not "build Uber." It's: given a stream of loosely structured
ride requests (origin, destination, rough time, seats needed), can software
find compatible groupings faster and more reliably than a human skimming a
chat thread? That's the whole bet, and it's the thing worth explaining in an
interview — the tech (geospatial matching, real-time pub/sub) is in service
of that specific, lived problem, not the other way around.

## What this is

A **local, non-deployed technical demo**: a matching engine that ingests
ride requests (initially: sample data modeled on real anonymized group
messages) and produces proposed rider groupings, with a real-time layer that
demos matches forming as requests stream in.

## What this explicitly is NOT (tonight, or this phase)

- No real drivers, no real riders, no real trips.
- No payments, no live location tracking of actual people.
- No public deployment. Runs on localhost only.
- No account system / auth beyond what's needed to demo multi-user flow.

If this ever moves toward real usage, that's a separate, later decision with
its own legal/liability/privacy conversation — not something to back into
via an unattended overnight coding session.

## MVP definition (what "done" looks like for the demo)

1. **Ingest**: sample ride requests (structured JSON, seeded from anonymized
   patterns of real group messages) loaded into the engine.
2. **Match**: the engine groups compatible requests using real geospatial +
   temporal logic (see [docs/MATCHING_ALGORITHM.md](docs/MATCHING_ALGORITHM.md)),
   not a toy database query.
3. **Stream**: a simulator replays requests over time (e.g. compressed into
   minutes) over a WebSocket/pub-sub channel; the engine re-matches
   incrementally as new requests arrive, instead of batch-recomputing from
   scratch.
4. **Observe**: a minimal view (CLI output or a barebones page) shows matches
   forming live during the simulated run.
5. **Explainable**: for any match, the engine can state *why* — shared
   corridor, time overlap, capacity fit — in interview-ready terms.

## Non-goals for the resume story

Don't over-scope this into a full-stack SaaS build. The differentiator is
matching quality and real-time architecture, not a polished UI or a large
feature surface. Resist adding auth, payments, admin panels, or a mobile app
— none of that demonstrates the thing this project is meant to prove.
