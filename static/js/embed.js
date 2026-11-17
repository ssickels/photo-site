// Click-to-load embeds (see photosite/embeds.py): the other site's iframe is
// only created once the visitor asks for it.
(function () {
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-embed]");
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    var f = document.createElement("iframe");
    f.src = a.getAttribute("data-embed");
    f.title = a.getAttribute("data-title") || "";
    f.referrerPolicy = "strict-origin-when-cross-origin";
    if (a.hasAttribute("data-fullscreen")) f.allowFullscreen = true;
    a.replaceWith(f);
  });
})();
