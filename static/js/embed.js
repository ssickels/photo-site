// Click-to-load embeds (see photosite/embeds.py): the other site's iframe is
// only created once the visitor asks for it. Videos also get a "Full screen"
// button under the box, since the player's own one is easy to miss in a
// small frame; it loads the video too if needed.
(function () {
  function load(a) {
    var f = document.createElement("iframe");
    f.src = a.getAttribute("data-embed");
    f.title = a.getAttribute("data-title") || "";
    f.referrerPolicy = "strict-origin-when-cross-origin";
    if (a.hasAttribute("data-allow")) f.allow = a.getAttribute("data-allow");
    if (a.hasAttribute("data-fullscreen")) f.allowFullscreen = true;
    a.replaceWith(f);
    return f;
  }

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-embed]");
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    load(a);
  });

  // Full screen needs the Fullscreen API on an element (not on iPhone, which
  // only puts <video> itself full screen; there the player's button does it).
  var can = document.fullscreenEnabled || document.webkitFullscreenEnabled;
  if (!can) return;
  document.querySelectorAll("a[data-embed][data-video][data-fullscreen]").forEach(function (a) {
    var fig = a.closest(".embed");
    var b = document.createElement("button");
    b.type = "button";
    b.className = "embed-full";
    b.textContent = "⛶︎ Full screen";
    b.addEventListener("click", function () {
      var f = fig.querySelector("iframe") || load(fig.querySelector("a[data-embed]"));
      var r = (f.requestFullscreen || f.webkitRequestFullscreen).call(f);
      if (r && r.catch) r.catch(function () {});   // refused: the video still plays in the box
    });
    var p = document.createElement("p");
    p.className = "embed-tools";
    p.appendChild(b);
    fig.after(p);
  });
})();
