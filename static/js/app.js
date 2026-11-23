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

  // <button data-geolocate="submit|fill"> inside a [data-geo-box]: ask the phone for its GPS
  // position. "submit" fills the form's lat/lng/accuracy and submits it ("Keldim");
  // "fill" writes "lat, lng" into the box's [data-geo-coords] input (branch location).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-geolocate]");
    if (!btn) return;
    var box = btn.closest("[data-geo-box]");
    var err = box.querySelector("[data-geo-error]");
    function busy(on) {
      btn.disabled = on;
      box.querySelectorAll("[data-idle]").forEach(function (el) { el.hidden = on; });
      box.querySelectorAll("[data-busy]").forEach(function (el) { el.hidden = !on; });
    }
    function fail(msg) {
      busy(false);
      err.textContent = msg;
      err.hidden = false;
    }
    if (!navigator.geolocation) return fail(box.getAttribute("data-no-geo"));
    err.hidden = true;
    busy(true);
    navigator.geolocation.getCurrentPosition(
      function (p) {
        var lat = p.coords.latitude.toFixed(6);
        var lng = p.coords.longitude.toFixed(6);
        if (btn.getAttribute("data-geolocate") === "fill") {
          box.querySelector("[data-geo-coords]").value = lat + ", " + lng;
          busy(false);
          return;
        }
        var form = btn.form;
        form.elements.lat.value = lat;
        form.elements.lng.value = lng;
        form.elements.accuracy.value = Math.round(p.coords.accuracy);
        form.submit();
      },
      function () { fail(box.getAttribute("data-denied")); },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
    );
  });

  // Keep CSRF on htmx requests.
  document.addEventListener("htmx:configRequest", function (e) {
    var token = document.querySelector("meta[name=csrf-token]");
    if (token) e.detail.headers["X-CSRFToken"] = token.content;
  });
})();
