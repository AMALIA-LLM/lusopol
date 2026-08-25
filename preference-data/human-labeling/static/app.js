/* Annotation page behaviour: selection, keyboard shortcuts, pane controls. */
(function () {
  "use strict";

  var form = document.getElementById("annotate-form");
  var nextBtn = document.getElementById("next-btn");
  var elapsed = document.getElementById("elapsed_ms");
  var started = Date.now();

  function options() {
    return Array.prototype.slice.call(document.querySelectorAll('input[name="choice"]'));
  }

  function paint() {
    var any = false;
    options().forEach(function (input) {
      var card = input.closest(".answer-card, .tie-option, .radio-pill");
      if (card) card.classList.toggle("selected", input.checked);
      if (input.checked) any = true;
    });
    if (nextBtn) nextBtn.disabled = !any;
  }

  function select(value) {
    options().forEach(function (input) {
      if (input.value === value) {
        input.checked = true;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }

  document.addEventListener("change", function (e) {
    if (e.target && e.target.name === "choice") paint();
  });

  // Let people select text inside an answer without it counting as a click.
  document.querySelectorAll(".answer-card:not(.static)").forEach(function (card) {
    card.addEventListener("click", function (e) {
      var selection = window.getSelection();
      if (selection && selection.toString().length > 2) e.preventDefault();
    });
  });

  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "input" || tag === "select" || e.metaKey || e.ctrlKey) return;
    if (e.key === "1") { select("A"); e.preventDefault(); }
    else if (e.key === "2") { select("B"); e.preventDefault(); }
    else if (e.key.toLowerCase() === "t") { select("tie"); e.preventDefault(); }
    else if (e.key === "Enter" && nextBtn && !nextBtn.disabled) { nextBtn.click(); e.preventDefault(); }
  });

  if (form && elapsed) {
    form.addEventListener("submit", function () {
      elapsed.value = String(Date.now() - started);
    });
  }

  // --- pane controls --------------------------------------------------------

  var heightBtn = document.getElementById("toggle-height");
  function applyHeight(tall) {
    document.body.classList.toggle("tall-panes", tall);
    if (heightBtn) heightBtn.textContent = tall ? "Shorter panes" : "Taller panes";
  }
  if (heightBtn) {
    applyHeight(localStorage.getItem("tallPanes") === "1");
    heightBtn.addEventListener("click", function () {
      var tall = !document.body.classList.contains("tall-panes");
      localStorage.setItem("tallPanes", tall ? "1" : "0");
      applyHeight(tall);
    });
  }

  var syncBox = document.getElementById("sync-scroll");
  var panes = document.querySelectorAll(".pair .answer");
  if (syncBox && panes.length === 2) {
    syncBox.checked = localStorage.getItem("syncScroll") === "1";
    syncBox.addEventListener("change", function () {
      localStorage.setItem("syncScroll", syncBox.checked ? "1" : "0");
    });
    var busy = false;
    panes.forEach(function (pane, i) {
      pane.addEventListener("scroll", function () {
        if (!syncBox.checked || busy) return;
        var other = panes[1 - i];
        var span = pane.scrollHeight - pane.clientHeight;
        var otherSpan = other.scrollHeight - other.clientHeight;
        if (span <= 0 || otherSpan <= 0) return;
        busy = true;
        other.scrollTop = (pane.scrollTop / span) * otherSpan;
        window.requestAnimationFrame(function () { busy = false; });
      });
    });
  }

  paint();
})();
