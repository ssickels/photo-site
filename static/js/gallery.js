// Justified gallery rows (Flickr-style). Without JS the CSS flex layout is
// used instead. Rows are chosen to keep every row close to the target
// height (--row-h): a small dynamic program over possible row breaks,
// rather than greedy filling, so one panorama doesn't blow up its row.
(function () {
  "use strict";
  var grid = document.querySelector(".grid");
  if (!grid) return;
  var items = Array.prototype.slice.call(grid.children);
  var ars = items.map(function (li) {
    return parseFloat(li.style.getPropertyValue("--ar")) || 1.5;
  });
  var MAX_ROW = 12;

  function layout() {
    var cs = getComputedStyle(grid);
    var W = grid.clientWidth;
    var gap = parseFloat(cs.columnGap) || 0;
    var target = parseFloat(cs.getPropertyValue("--row-h")) || 240;
    var n = ars.length;
    if (!W || !n) return;

    // best[j] = lowest cost of laying out items 0..j-1; prev[j] = start of last row
    var best = [0], prev = [0];
    for (var j = 1; j <= n; j++) {
      best[j] = Infinity;
      var sum = 0;
      for (var i = j - 1; i >= 0 && j - i <= MAX_ROW; i--) {
        sum += ars[i];
        var h = (W - gap * (j - i - 1)) / sum;
        var cost;
        if (j === n && h > target) cost = 0;                 // last row may be short
        else cost = Math.pow((h - target) / target, 2) * (h < target ? 1.5 : 1);
        if (best[i] + cost < best[j]) { best[j] = best[i] + cost; prev[j] = i; }
        if (h < target * 0.4) break;                           // row is already far too full
      }
    }
    var rows = [];
    for (var k = n; k > 0; k = prev[k]) rows.unshift([prev[k], k]);

    rows.forEach(function (r, ri) {
      var s = 0;
      for (var x = r[0]; x < r[1]; x++) s += ars[x];
      var h = (W - gap * (r[1] - r[0] - 1)) / s;
      // a last row that would be much taller than the target stays ragged
      var ragged = ri === rows.length - 1 && h > target * 1.25;
      if (ragged) h = target;
      for (var y = r[0]; y < r[1]; y++) {
        var w = Math.floor(ars[y] * h * 100) / 100;
        // the last tile of a full row absorbs rounding, and its width forces the break
        var fill = !ragged && y === r[1] - 1;
        items[y].style.flex = fill ? "1 1 " + (w - 1) + "px" : "0 0 " + w + "px";
        items[y].style.maxWidth = "none";
      }
    });
    grid.classList.add("js");
  }

  layout();
  var pending = false, lastW = grid.clientWidth;
  var onResize = function () {
    if (pending || grid.clientWidth === lastW) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; lastW = grid.clientWidth; layout(); });
  };
  if ("ResizeObserver" in window) new ResizeObserver(onResize).observe(grid);
  else window.addEventListener("resize", onResize);
})();
