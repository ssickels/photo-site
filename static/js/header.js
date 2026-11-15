// Header that slides away while scrolling down and comes back on any scroll up.
// Without JS the header simply stays at the top of the page.
(function () {
  var header = document.querySelector(".site-header");
  if (!header) return;
  var root = document.documentElement, lastY = window.scrollY, ticking = false, full = 0;

  function measure() {                    // space the page keeps for the full-size header
    var compact = header.classList.contains("compact");
    header.classList.remove("compact");
    full = header.offsetHeight;
    root.style.setProperty("--header-space", full + "px");
    if (compact) header.classList.add("compact");
  }

  function update() {
    ticking = false;
    var y = Math.max(0, window.scrollY);
    if (y <= full) {                     // near the top: full header, always shown
      header.classList.remove("compact", "hidden");
    } else {
      header.classList.add("compact");
      if (header.contains(document.activeElement)) header.classList.remove("hidden");
      else if (y > lastY + 4) header.classList.add("hidden");
      else if (y < lastY - 4) header.classList.remove("hidden");
    }
    lastY = y;
  }

  root.classList.add("js-header");
  measure();
  update();
  window.addEventListener("scroll", function () {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }, { passive: true });
  window.addEventListener("resize", measure);
  header.addEventListener("focusin", function () { header.classList.remove("hidden"); });
})();
