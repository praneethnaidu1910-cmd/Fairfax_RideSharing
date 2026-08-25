# Scope — Fairfax-Area Ride-Pooling Platform

## The problem, stated honestly

Around 1,000 international students/professionals across Fairfax, Ashburn,
Herndon, Chantilly, Reston, and the wider Northern Virginia commuter belt
(real message samples from the group also show Aldie, Manassas, Sterling,
South Riding, Vienna, Falls Church, and Centerville) coordinate rides
through an open WhatsApp group. A typical stretch of that group looks like:
someone posts "Need ride from Fairfax to aldie," someone else posts a full
home street address because there's no other way to be specific about
pickup, a third person reposts the same request the next night because
there's no way to mark a request as recurring, and a fourth bumps their own
post hours later with "Still looking" because there's no status or
notification — just a scrolling list everyone has to read in full to catch
a match.

The bet: software can do the matching (space, direction, time, capacity)
faster and more safely than a human skimming a chat thread — and can do it
without asking anyone to broadcast their home address to ~1,000 strangers,
which the current group makes people do by default.

## Where this is going

This started as a local, portfolio-only demo (see git history from
`577105f` onward for that phase — the matching-engine skeleton and the
separate dispatch side-module both still stand and still matter as the
technical core). **The actual goal now is to ship this to the real
~1,000-person community that already exists and already trusts each other
enough to coordinate rides today** — not a hypothetical user base, the
literal people posting in that group. That changes what "done" means, but
it doesn't mean building Uber's entire company. The scope below is sized to
this community's actual observed behavior, not a speculative feature list.

## What this is (Phase 1 — Fairfax/Northern-Virginia, real users)

A **web app** — not a WhatsApp Business API bot. A bot would need Meta
business verification and has ongoing per-conversation cost; a plain web
app doesn't, and gives full control over what gets shown to whom (a
WhatsApp group is all-or-nothing broadcast by design; a web app isn't).

- **Structured intake, not free text.** A form collects origin,
  destination, time (one-off or recurring), and seats needed. This
  sidesteps parsing unstructured messages like "Need ride" (which real
  examples show carry zero usable structure) entirely — no NLP layer
  needed, because we're not reading WhatsApp text, we're asking for the
  fields directly.
- **Recurring requests are first-class.** "Daily rides weekdays at 9am" is
  a standing pattern, not five separate one-off posts. The current group
  has no way to express this, so people repost near-verbatim every day.
- **No exact address, ever, pre-match.** Locations are geocoded from
  informal place names or a dropped pin, but only ever shown to *other*
  users as a coarse area (neighborhood-level) and a fuzzed time window.
  Exact pickup point and contact info are exchanged only between two
  people after they mutually match — never broadcast.
- **Matches both strangers and groups.** A request can represent one
  person or a small party (a friend posting on behalf of a couple of
  others); matching respects vehicle capacity across parties, not just
  individuals. Real geospatial + temporal + directional compatibility
  scoring — see docs/MATCHING_ALGORITHM.md.
- **Live status, not manual bumping.** A request shows open / matched /
  expired. Nobody should need to repost "Still looking."
- **Open-join, no membership gate.** Consistent with how the WhatsApp
  group actually works — anyone can post or browse, no verification that
  someone "belongs." Contact info (e.g. a phone number) is collected at
  request time so a matched pair can reach each other, same trust level
  as the group today — **no SMS/OTP verification for the MVP**, since that
  costs real (if small) per-message money and isn't what the current
  group requires either. Worth revisiting only if spam/abuse actually
  shows up.

## What this explicitly does NOT do (Phase 1)

- **No payments.** People settle ride cost (~$1/mile is the group's
  current informal norm) the way they already do — Zelle, cash — outside
  the app. No money-movement, escrow, or invoicing gets built.
- **No membership verification.** Open join, open leave, same as today.
- **No routing/ETA engine.** Distance is haversine (straight-line), not
  real road-network drive time — same honest simplification as the
  original demo scope. Revisit only if match quality actually suffers.
- **No native mobile app.** Web app only — no app-store distribution
  overhead.
- **Not multi-region.** Scoped to the Northern Virginia / Fairfax
  commuter belt the real messages actually show. Expanding beyond that is
  a real Phase 2 conversation (different geocoding density, different
  community-trust assumptions) — deliberately not designed yet.

## The part that isn't just an engineering decision

This app will hold real people's real travel plans and, even without
handling money directly, sits right next to real cash/Zelle payment for
transportation. That's a genuinely different risk profile than a localhost
demo: real data protection for real location data, some way to handle
harassment/abuse reports, and — worth being honest about rather than
quietly ignoring — an open legal question about how Virginia treats
software-mediated ride-cost-splitting versus casual carpooling among
acquaintances. That's worth actually researching before this goes live to
the full group, not something to resolve by assumption in this file.

## MVP definition (Phase 1, real usage)

1. **Structured intake**: web form → validated `RideRequest` (one-off or
   recurring), origin/destination geocoded to a coarse + precise location,
   party size.
2. **Privacy-safe browsing**: open requests are visible as coarse area +
   fuzzed time + seats needed — never exact address/time/contact
   pre-match.
3. **Match**: real geospatial + directional + temporal + capacity scoring
   (docs/MATCHING_ALGORITHM.md), covering both stranger-pooling and
   group/on-behalf-of-friends requests.
4. **Live status**: open / matched / expired, without the poster manually
   re-posting or bumping.
5. **Post-match reveal**: exact pickup point and contact info shared only
   between the matched parties.
6. **Explainable**: for any match, the engine can state why — shared
   corridor, time overlap, capacity fit.

## Phase 2 (explicitly deferred, not designed yet)

- Geographic expansion beyond the Fairfax/Northern-Virginia commuter belt.
- Anything payments-adjacent beyond "no-op, people handle it themselves."
- Native mobile apps.
- SMS/OTP identity verification, and any further trust/safety tooling
  (reporting, blocking, moderation) beyond what Phase 1 needs to not be
  obviously unsafe.
