// Live match updates for the "my request" page (TASKS.md #12). Opens a
// WebSocket to /matches and, the moment a MatchGroup mentioning this page's
// own request id arrives, fetches the counterpart's full reveal (task 7's
// viewer_request_id mechanism) and renders it -- no page reload.

(function () {
  const myId = window.MY_REQUEST_ID;
  if (!myId) {
    return;
  }

  const waitingMessage = document.getElementById("waiting-message");
  const revealBox = document.getElementById("reveal-box");

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(protocol + "//" + window.location.host + "/matches");

  socket.addEventListener("message", async (event) => {
    const match = JSON.parse(event.data);
    if (!match.request_ids.includes(myId)) {
      return; // some other rider's match -- every connection sees every match
    }

    const counterpartId = match.request_ids.find((id) => id !== myId);
    const response = await fetch(
      "/requests/" + counterpartId + "?viewer_request_id=" + myId
    );
    if (!response.ok) {
      return;
    }
    const counterpart = await response.json();

    waitingMessage.textContent = "Matched! Your ride partner, " + counterpart.rider_id + ":";
    revealBox.hidden = false;
    // Built with textContent, not innerHTML -- counterpart.contact/rider_id
    // are free text another rider typed into POST /requests with no
    // sanitization (SCOPE.md never restricts `contact` to a phone-number
    // shape), so interpolating them into an HTML string here would let a
    // malicious poster's contact field run as script in whoever they match
    // with's browser the moment the reveal renders.
    const list = document.createElement("ul");
    const addRevealItem = (label, value) => {
      const item = document.createElement("li");
      item.textContent = label + ": " + value;
      list.appendChild(item);
    };
    addRevealItem("Contact", counterpart.contact);
    addRevealItem("Pickup", counterpart.origin.lat + ", " + counterpart.origin.lng);
    addRevealItem("Dropoff", counterpart.destination.lat + ", " + counterpart.destination.lng);
    revealBox.replaceChildren(list);
  });
})();
