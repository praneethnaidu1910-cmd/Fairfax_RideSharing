// Minimal vanilla JS for the "post a ride request" form (TASKS.md #11).
// Two jobs, no framework, no build step:
//   1. Turn a typed place name into lat/lng via GET /geocode (TASKS.md #10)
//      and stash it in the matching hidden input, so the form still posts
//      plain origin_lat/origin_lng fields the server already understands.
//   2. Show only the one-off or recurring schedule fields that match the
//      selected radio button, since a request has exactly one schedule type.

async function geocodeField(input) {
  const target = input.dataset.geocodeTarget;
  const status = document.getElementById(target + "_place_status");
  const latField = document.getElementById(target + "_lat");
  const lngField = document.getElementById(target + "_lng");
  const place = input.value.trim();

  if (!place) {
    latField.value = "";
    lngField.value = "";
    delete input.dataset.resolvedFor;
    status.textContent = "";
    return;
  }

  status.textContent = "Looking up...";
  try {
    const response = await fetch("/geocode?q=" + encodeURIComponent(place));
    if (response.status === 404) {
      // A confirmed "no such place" from the server -- safe to clear
      // whatever lat/lng was there before, since it no longer applies.
      latField.value = "";
      lngField.value = "";
      delete input.dataset.resolvedFor;
      status.textContent = "Couldn't find that place -- try a more specific name.";
      return;
    }
    if (!response.ok) {
      // A transient server/network problem, not "not found" -- leave any
      // previously-resolved lat/lng alone rather than wiping it out from
      // under a field the rider already filled in successfully. Also
      // leave resolvedFor exactly as it was (the place that lat/lng
      // actually came from, not this one) -- see ensureGeocodeFieldsMatchTypedPlace()
      // below for why that's what makes a later submit retry this lookup
      // instead of trusting a pairing that was never actually confirmed.
      status.textContent = "Lookup failed -- check your connection and try again.";
      return;
    }
    const location = await response.json();
    latField.value = location.lat;
    lngField.value = location.lng;
    input.dataset.resolvedFor = place;
    status.textContent = "Resolved to " + location.lat.toFixed(4) + ", " + location.lng.toFixed(4);
  } catch (err) {
    status.textContent = "Lookup failed -- check your connection and try again.";
  }
}

// geocodeField() only ever runs on a field's `blur` event -- but blurring
// isn't actually guaranteed to happen before the form submits. Pressing
// Enter inside a still-focused text input submits the form directly,
// without firing blur on that input first, and even a normal blur (tabbing
// or clicking elsewhere) only *starts* the async /geocode fetch -- the
// native, synchronous form submission that follows a click or Enter
// doesn't wait for it to finish. Either way, whatever origin_lat/origin_lng
// happened to be sitting in the hidden fields already -- correct for
// whatever place was typed *before* this edit, not the one on screen now --
// gets submitted as-is, with no error and nothing telling the rider their
// pickup/destination doesn't match what they typed. Confirmed this was
// real, not theoretical, with a live headless-Chromium script against a
// running server (same tool the root README's own #12 verification used):
// resolved origin_place to "Fairfax" (lat/lng correctly set), edited it to
// "Reston" without blurring, then pressed Enter directly in that same
// field -- the form submitted immediately, landed on /mine/<id> (a real,
// successful POST /requests), and the row that actually got stored still
// held Fairfax's coordinates, not Reston's, with the rider never told any
// of that happened. For a real app whose whole point is coordinating
// physical pickups (SCOPE.md), silently posting the wrong location is a
// much worse failure than the 404/transient-failure cases geocodeField()
// already guards above.
//
// Fix: every resolved field remembers which exact place string its current
// lat/lng actually came from (input.dataset.resolvedFor, set on a
// successful lookup above, cleared whenever lat/lng themselves get
// cleared). The form's own submit handler below intercepts every attempt
// to submit -- a click, Enter, anything -- and for any geocode-tracked
// field whose current text doesn't match that remembered value (edited
// since the last resolution, or never resolved at all), awaits a fresh
// geocodeField() call before letting the submission through. The already-
// correctly-resolved, unedited case (the common path) matches immediately
// and costs nothing extra; everything else gets a real lookup instead of
// a stale or absent one.
async function ensureGeocodeFieldsMatchTypedPlace(form) {
  for (const input of form.querySelectorAll("[data-geocode-target]")) {
    const place = input.value.trim();
    if (place && input.dataset.resolvedFor === place) {
      continue;
    }
    await geocodeField(input);
  }
}

function updateScheduleFieldsVisibility() {
  const selected = document.querySelector('input[name="schedule_type"]:checked');
  const isRecurring = selected && selected.value === "recurring";
  document.getElementById("one_off_fields").style.display = isRecurring ? "none" : "block";
  document.getElementById("recurring_fields").style.display = isRecurring ? "block" : "none";
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-geocode-target]").forEach((input) => {
    input.addEventListener("blur", () => geocodeField(input));
  });

  document.querySelectorAll('input[name="schedule_type"]').forEach((radio) => {
    radio.addEventListener("change", updateScheduleFieldsVisibility);
  });
  updateScheduleFieldsVisibility();

  const form = document.querySelector("form");
  if (form) {
    form.addEventListener("submit", (event) => {
      // Intercept every submission attempt (not just the ones that happen
      // to follow a blur) so a stale/unconfirmed lat-lng pairing never
      // reaches the server -- see ensureGeocodeFieldsMatchTypedPlace()
      // above for the real reproduction this closes. form.submit() below
      // bypasses the "submit" event entirely (no re-entrant loop) and
      // skips native constraint validation, but that's already been run
      // by the browser to get here in the first place, so nothing new
      // slips past it.
      event.preventDefault();
      ensureGeocodeFieldsMatchTypedPlace(form).then(() => form.submit());
    });
  }
});
