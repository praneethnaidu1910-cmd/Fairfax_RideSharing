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
    status.textContent = "";
    return;
  }

  status.textContent = "Looking up...";
  try {
    const response = await fetch("/geocode?q=" + encodeURIComponent(place));
    if (!response.ok) {
      latField.value = "";
      lngField.value = "";
      status.textContent = "Couldn't find that place -- try a more specific name.";
      return;
    }
    const location = await response.json();
    latField.value = location.lat;
    lngField.value = location.lng;
    status.textContent = "Resolved to " + location.lat.toFixed(4) + ", " + location.lng.toFixed(4);
  } catch (err) {
    status.textContent = "Lookup failed -- check your connection and try again.";
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
});
