// Runs before first paint so a saved Light/Dark choice never flashes (DR13).
(function () {
  var t = "auto";
  try { t = localStorage.getItem("stavsboard.theme") || "auto"; } catch (e) {}
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
})();
