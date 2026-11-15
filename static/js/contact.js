/* Contact form: send with fetch (so the message stays in the form if anything
   goes wrong), report how long the form took to fill (a bot check), and show
   the banner for a no-JS post that came back with ?status=. */
(function () {
  var form = document.querySelector(".contact-form");
  var box = document.getElementById("form-status");
  if (!form || !box) return;
  var started = Date.now();

  var REASONS = {
    captcha: "The verification check didn't pass. Please try it again and resend.",
    ratelimit: "That's several messages from this connection in a short time. Please try again later.",
    invalid: "Please check your name, email address and message, then resend.",
    send: "The message couldn't be sent just now. Please try again shortly."
  };
  var THANKS = "Thanks! Your message has been sent.";
  var GENERIC = "Something went wrong. Please try again in a few minutes.";

  function show(kind, text) {
    box.hidden = false;
    box.className = "form-status " + kind;
    box.textContent = text;
    box.scrollIntoView({ block: "nearest" });
  }

  // Back from a no-JS post: show the result, then drop the query so a reload
  // or a bookmark doesn't show it again.
  var params = new URLSearchParams(location.search);
  var status = params.get("status");
  if (status === "success") show("success", THANKS);
  else if (status === "error") show("error", REASONS[params.get("reason")] || GENERIC);
  if (status && history.replaceState) {
    try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) {}
  }

  var button = form.querySelector("button[type=submit]");
  form.addEventListener("submit", function (ev) {
    if (!window.fetch || !window.FormData) return;     // normal post instead
    ev.preventDefault();
    var data = new FormData(form);
    data.append("ajax", "1");
    data.append("elapsed", String(Date.now() - started));
    button.disabled = true;
    fetch(form.action, { method: "POST", body: data, headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.status === "success") {
          form.reset();
          form.hidden = true;
          show("success", THANKS);
        } else {
          show("error", res.message || GENERIC);
        }
      })
      .catch(function () { show("error", GENERIC); })
      .then(function () {
        button.disabled = false;
        if (window.turnstile) { try { window.turnstile.reset(); } catch (e) {} }   // tokens are single-use
      });
  });
})();
