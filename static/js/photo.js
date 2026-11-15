// Photo page: ← / → for previous / next, Esc (or the close button) back to the gallery,
// swipe on touch screens, and prefetch the next photo once this one is loaded.
(function () {
  "use strict";
  var fig = document.querySelector(".photo");
  if (!fig) return;
  var d = fig.dataset;

  function go(url) { if (url) window.location.href = url; }

  function back() {
    // Return to the gallery, at this photo. history.back() keeps the gallery's
    // scroll position when we came from it.
    var up = new URL(d.up, window.location.href);
    var ref = document.referrer ? new URL(document.referrer) : null;
    if (ref && ref.origin === up.origin && ref.pathname === up.pathname && history.length > 1) {
      history.back();
    } else {
      go(d.up + "#" + d.id);
    }
  }

  document.addEventListener("keydown", function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (e.key === "ArrowLeft") go(d.prev);
    else if (e.key === "ArrowRight") go(d.next);
    else if (e.key === "Escape") back();
  });

  var close = document.querySelector(".stage .close");
  if (close) close.addEventListener("click", function (e) { e.preventDefault(); back(); });

  // Swipe: horizontal movement of at least 50px that is mostly sideways.
  var stage = fig.parentNode;
  var x0 = null, y0 = null;
  stage.addEventListener("touchstart", function (e) {
    if (e.touches.length !== 1) { x0 = null; return; }
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
  }, { passive: true });
  var vv = window.visualViewport;
  function zoomed() { return vv && vv.scale > 1.05; }
  stage.addEventListener("touchend", function (e) {
    if (x0 === null) return;
    if (zoomed()) { x0 = null; return; }          // pinch-zoomed in: one-finger drag pans, not swipes
    var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > 1.5 * Math.abs(dy)) go(dx < 0 ? d.next : d.prev);
  }, { passive: true });

  // Pinch-zoom: browsers don't fetch a sharper file when you zoom in, so ask
  // for one sized to the zoomed width (the largest is 2400 px).
  if (vv) {
    var wanted = 0;
    vv.addEventListener("resize", function () {
      if (vv.scale < 1.3) return;
      var w = Math.round(fig.getBoundingClientRect().width * vv.scale);
      if (w <= wanted) return;
      wanted = w;
      fig.querySelectorAll("source, img").forEach(function (el) { el.sizes = w + "px"; });
    });
  }

  // Prefetch the next photo at the size this screen would pick.
  function prefetch() {
    if (!d.nextSrcset) return;
    var c = navigator.connection;
    if (c && (c.saveData || /2g/.test(c.effectiveType || ""))) return;
    var img = new Image();
    img.decoding = "async";
    img.sizes = d.nextSizes;
    img.srcset = d.nextSrcset;
  }
  var main = fig.querySelector("img");
  if (main && !main.complete) main.addEventListener("load", prefetch, { once: true });
  else window.addEventListener("load", prefetch, { once: true });
})();
