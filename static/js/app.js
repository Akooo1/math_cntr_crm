// Small progressive enhancements. Pages work without JavaScript.
(function () {
  "use strict";

  // Money inputs: show "1 250 000" while typing. The server strips the spaces.
  function formatMoney(input) {
    var digits = input.value.replace(/[^\d]/g, "");
    input.value = digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  // Date inputs: DD.MM.YYYY with automatic dots.
  function maskDate(input) {
    var d = input.value.replace(/[^\d]/g, "").slice(0, 8);
    var out = d.slice(0, 2);
    if (d.length > 2) out += "." + d.slice(2, 4);
    if (d.length > 4) out += "." + d.slice(4, 8);
    input.value = out;
  }

  // Time inputs: HH:MM with an automatic colon.
  function maskTime(input) {
    var d = input.value.replace(/[^\d]/g, "").slice(0, 4);
    input.value = d.length > 2 ? d.slice(0, 2) + ":" + d.slice(2) : d;
  }

  document.addEventListener("input", function (e) {
    var t = e.target;
    if (t.matches && t.matches("input[data-money]")) formatMoney(t);
    if (t.matches && t.matches("input[data-mask=date]") && e.inputType !== "deleteContentBackward") maskDate(t);
    if (t.matches && t.matches("input[data-mask=time]") && e.inputType !== "deleteContentBackward") maskTime(t);
  });

  // <form data-confirm="..."> asks before submitting.
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // Keep CSRF on htmx requests.
  document.addEventListener("htmx:configRequest", function (e) {
    var token = document.querySelector("meta[name=csrf-token]");
    if (token) e.detail.headers["X-CSRFToken"] = token.content;
  });
})();
