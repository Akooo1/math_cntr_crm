// Progressive enhancements. Every page works without JavaScript.
// Translated text never lives here: it comes from <script id="ui-i18n"> (json_script) or
// from data- attributes, so Uzbek apostrophes can't break the quotes.
(function () {
  "use strict";

  var root = document.documentElement;
  var T = {};
  try { T = JSON.parse(document.getElementById("ui-i18n").textContent); } catch (e) { /* login page before migrations */ }

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function on(type, sel, fn, opts) {
    document.addEventListener(type, function (e) {
      var el = e.target && e.target.closest ? e.target.closest(sel) : null;
      if (el) fn(e, el);
    }, opts);
  }

  // ---------------------------------------------------------------------------------
  // Input masks: money "1 250 000", date DD.MM.YYYY, time HH:MM.
  function formatMoney(input) {
    var digits = input.value.replace(/[^\d]/g, "");
    input.value = digits.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }
  function maskDate(input) {
    var d = input.value.replace(/[^\d]/g, "").slice(0, 8);
    var out = d.slice(0, 2);
    if (d.length > 2) out += "." + d.slice(2, 4);
    if (d.length > 4) out += "." + d.slice(4, 8);
    input.value = out;
  }
  function maskTime(input) {
    var d = input.value.replace(/[^\d]/g, "").slice(0, 4);
    input.value = d.length > 2 ? d.slice(0, 2) + ":" + d.slice(2) : d;
  }
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (!t.matches) return;
    if (t.matches("input[data-money]")) formatMoney(t);
    if (t.matches("input[data-mask=date]") && e.inputType && e.inputType !== "deleteContentBackward") maskDate(t);
    if (t.matches("input[data-mask=time]") && e.inputType && e.inputType !== "deleteContentBackward") maskTime(t);
  });

  // <select data-autosubmit> submits its form on change.
  on("change", "[data-autosubmit]", function (e, sel) { if (sel.form) sel.form.requestSubmit ? sel.form.requestSubmit() : sel.form.submit(); });

  // ---------------------------------------------------------------------------------
  // Theme: light / dark / system, remembered per browser. The <head> script applies it
  // before first paint; this keeps it in sync with the picker and the OS setting.
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function themeChoice() {
    try { return localStorage.getItem("theme") || "system"; } catch (e) { return "system"; }
  }
  function applyTheme(choice) {
    var dark = choice === "dark" || (choice === "system" && media && media.matches);
    root.setAttribute("data-theme", dark ? "dark" : "light");
    root.setAttribute("data-theme-choice", choice);
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-theme-set") === choice ? "true" : "false");
    });
  }
  on("click", "[data-theme-set]", function (e, btn) {
    var choice = btn.getAttribute("data-theme-set");
    try { localStorage.setItem("theme", choice); } catch (err) { /* private mode: this page only */ }
    applyTheme(choice);
  });
  if (media && media.addEventListener) media.addEventListener("change", function () { applyTheme(themeChoice()); });

  // Sidebar: full or icons only, remembered per browser (the <head> script applies it).
  on("click", "[data-rail-toggle]", function () {
    var collapsed = root.getAttribute("data-rail") !== "collapsed";
    if (collapsed) root.setAttribute("data-rail", "collapsed"); else root.removeAttribute("data-rail");
    try { localStorage.setItem("rail", collapsed ? "collapsed" : "full"); } catch (err) { /* private mode */ }
  });

  // Page header: the round back button goes to the last breadcrumb (hidden without one).
  document.querySelectorAll("[data-back]").forEach(function (btn) {
    var crumbs = document.querySelectorAll(".crumbs a[href]");
    if (crumbs.length) btn.setAttribute("href", crumbs[crumbs.length - 1].getAttribute("href"));
  });

  // ---------------------------------------------------------------------------------
  // Top-bar clock: "Seshanba, 25.11.2026 · 14:32" in Asia/Tashkent, every minute.
  var tzParts = null;
  try {
    var fmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    tzParts = function (d) {
      var o = {};
      fmt.formatToParts(d).forEach(function (p) { o[p.type] = p.value; });
      return o;
    };
  } catch (e) { tzParts = null; }
  function tashkentNow() {
    var p = tzParts ? tzParts(new Date()) : null;
    if (!p) return null;
    var y = +p.year, m = +p.month, d = +p.day;
    return { y: y, m: m, d: d, hh: p.hour === "24" ? "00" : p.hour, mm: p.minute, dow: (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7 };
  }
  function tick() {
    var n = tashkentNow();
    if (n && T.days) {
      document.querySelectorAll("[data-clock]").forEach(function (el) {
        el.querySelector("[data-clock-day]").textContent = T.days[n.dow];
        el.querySelector("[data-clock-rest]").textContent = pad(n.d) + "." + pad(n.m) + "." + n.y + " · " + n.hh + ":" + n.mm;
        el.setAttribute("datetime", n.y + "-" + pad(n.m) + "-" + pad(n.d) + "T" + n.hh + ":" + n.mm);
      });
    }
    setTimeout(tick, 60000 - (Date.now() % 60000) + 50);
  }

  // ---------------------------------------------------------------------------------
  // Toasts: success/info leave after 5 s, warnings after 8 s, errors after 12 s.
  // Hovering or focusing a toast keeps it.
  function dismiss(toast) {
    if (!toast || toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    setTimeout(function () { toast.remove(); }, 220);
  }
  function armToast(toast) {
    var kind = toast.getAttribute("data-kind");
    var ms = kind === "error" ? 12000 : kind === "warning" ? 8000 : 5000;
    var timer = setTimeout(function () { dismiss(toast); }, ms);
    function hold() { clearTimeout(timer); }
    function resume() { timer = setTimeout(function () { dismiss(toast); }, 2500); }
    toast.addEventListener("mouseenter", hold);
    toast.addEventListener("focusin", hold);
    toast.addEventListener("mouseleave", resume);
  }
  on("click", "[data-toast-close]", function (e, btn) { dismiss(btn.closest("[data-toast]")); });

  // ---------------------------------------------------------------------------------
  // Loading bar: htmx requests and full-page navigation.
  var pending = 0, safety = null;
  function loading(onOff) {
    clearTimeout(safety);
    if (onOff) {
      root.classList.remove("is-loading");
      void root.offsetWidth; // restart the animation
      root.classList.add("is-loading");
      safety = setTimeout(function () { root.classList.remove("is-loading"); }, 15000);
    } else {
      root.classList.remove("is-loading");
    }
  }
  document.addEventListener("htmx:beforeRequest", function () { pending++; loading(true); });
  document.addEventListener("htmx:afterRequest", function () { pending = Math.max(0, pending - 1); if (!pending) loading(false); });
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target || a.hasAttribute("download") || a.hasAttribute("hx-get") || a.origin !== location.origin) return;
    var href = a.getAttribute("href");
    if (!href || href.charAt(0) === "#" || /[?&]excel=/.test(href) || /\/(namuna|chek)\//.test(href)) return;
    loading(true);
  });

  // ---------------------------------------------------------------------------------
  // Forms. <form data-confirm="..."> asks first. A submitted POST form disables its
  // buttons and shows a spinner on the one pressed, so nothing is saved twice (a double
  // click on "To'lov qabul qilish" must not record two payments). Opt out: data-no-busy.
  function setBusy(form, submitter) {
    form.setAttribute("data-busy", "1");
    if (submitter && submitter.name) {
      // A disabled button is not sent: keep its name=value (e.g. Keldi / Kelmadi).
      var keep = document.createElement("input");
      keep.type = "hidden"; keep.name = submitter.name; keep.value = submitter.value;
      keep.setAttribute("data-busy-keep", "");
      form.appendChild(keep);
    }
    form.querySelectorAll("button, input[type=submit]").forEach(function (b) {
      if (b.type === "button") return;
      b.setAttribute("data-was-disabled", b.disabled ? "1" : "0");
      b.disabled = true;
    });
    if (submitter && submitter.tagName === "BUTTON") {
      submitter.setAttribute("aria-busy", "true");
      var spin = document.createElement("span");
      spin.className = "spinner";
      spin.setAttribute("data-busy-spinner", "");
      var icon = submitter.querySelector("svg");
      if (icon) { icon.setAttribute("data-busy-hidden", ""); icon.style.display = "none"; }
      submitter.insertBefore(spin, submitter.firstChild);
      if (T.saving && !submitter.classList.contains("btn-icon")) submitter.setAttribute("aria-label", T.saving);
    }
  }
  function clearBusy(form) {
    form.removeAttribute("data-busy");
    form.querySelectorAll("[data-busy-keep], [data-busy-spinner]").forEach(function (el) { el.remove(); });
    form.querySelectorAll("[data-busy-hidden]").forEach(function (el) { el.style.display = ""; el.removeAttribute("data-busy-hidden"); });
    form.querySelectorAll("[aria-busy]").forEach(function (el) { el.removeAttribute("aria-busy"); el.removeAttribute("aria-label"); });
    form.querySelectorAll("[data-was-disabled]").forEach(function (b) { b.disabled = b.getAttribute("data-was-disabled") === "1"; b.removeAttribute("data-was-disabled"); });
  }
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var msg = (e.submitter && e.submitter.getAttribute("data-confirm")) || (form.getAttribute && form.getAttribute("data-confirm"));
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    if (e.defaultPrevented) return; // htmx handles its own forms (see below)
    if (form.getAttribute("data-busy")) { e.preventDefault(); return; }
    var method = (form.getAttribute("method") || "get").toLowerCase();
    if (method !== "post" || form.target || form.hasAttribute("data-no-busy")) {
      if (method === "get" && !form.target) loading(true);
      return;
    }
    setBusy(form, e.submitter);
    loading(true);
  });
  document.addEventListener("htmx:beforeRequest", function (e) {
    var form = e.detail.elt && e.detail.elt.closest ? e.detail.elt.closest("form") : null;
    var verb = (e.detail.requestConfig && e.detail.requestConfig.verb) || "";
    if (form && verb.toLowerCase() === "post" && !form.hasAttribute("data-no-busy")) {
      var sub = e.detail.requestConfig.triggeringEvent && e.detail.requestConfig.triggeringEvent.submitter;
      setBusy(form, sub || (e.detail.elt.tagName === "BUTTON" ? e.detail.elt : null));
      form.querySelectorAll("[data-busy-keep]").forEach(function (el) { el.remove(); }); // htmx sends the button itself
    }
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    var form = e.detail.elt && e.detail.elt.closest ? e.detail.elt.closest("form") : null;
    if (form && form.isConnected) clearBusy(form);
  });
  // Back/forward cache: a page restored from history must not keep frozen buttons.
  window.addEventListener("pageshow", function () {
    loading(false);
    document.querySelectorAll("form[data-busy]").forEach(clearBusy);
  });

  // ---------------------------------------------------------------------------------
  // Global search palette: Ctrl+K / Cmd+K, "/" or the search button.
  var palette = document.querySelector("[data-palette]");
  var paletteInput = palette && palette.querySelector("[data-palette-input]");
  var lastFocus = null;
  function paletteItems() { return Array.prototype.slice.call(palette.querySelectorAll(".palette-item")); }
  function selectItem(i) {
    var items = paletteItems();
    items.forEach(function (it, k) { it.setAttribute("aria-selected", k === i ? "true" : "false"); });
    if (items[i]) {
      items[i].scrollIntoView({ block: "nearest" });
      paletteInput.setAttribute("aria-activedescendant", items[i].id || "");
    }
  }
  function openPalette() {
    if (!palette) return;
    lastFocus = document.activeElement;
    palette.hidden = false;
    document.body.style.overflow = "hidden";
    paletteInput.focus();
    paletteInput.select();
  }
  function closePalette() {
    if (!palette || palette.hidden) return;
    palette.hidden = true;
    document.body.style.overflow = "";
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  if (palette) {
    on("click", "[data-search-open]", function (e) { e.preventDefault(); openPalette(); });
    on("click", "[data-palette-close]", function () { closePalette(); });
    document.addEventListener("keydown", function (e) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
      if ((e.key === "k" || e.key === "K") && (e.ctrlKey || e.metaKey)) { e.preventDefault(); palette.hidden ? openPalette() : closePalette(); return; }
      if (e.key === "/" && !typing && palette.hidden) { e.preventDefault(); openPalette(); return; }
      if (palette.hidden) return;
      if (e.key === "Escape") { e.preventDefault(); closePalette(); return; }
      var items = paletteItems();
      var cur = items.findIndex(function (it) { return it.getAttribute("aria-selected") === "true"; });
      if (e.key === "ArrowDown") { e.preventDefault(); selectItem(Math.min(items.length - 1, cur + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); selectItem(Math.max(0, cur - 1)); }
      else if (e.key === "Enter" && document.activeElement === paletteInput) {
        e.preventDefault();
        var target = items[cur >= 0 ? cur : 0];
        if (target) { loading(true); location.href = target.getAttribute("href"); }
      } else if (e.key === "Tab") {
        // keep focus inside the dialog
        var f = palette.querySelectorAll("input, button, a[href]");
        if (f.length && e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (f.length && !e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    });
    document.addEventListener("htmx:afterSwap", function (e) {
      if (e.detail.target && e.detail.target.id === "palette-results") selectItem(0);
    });
    on("mousemove", ".palette-item", function (e, it) { selectItem(paletteItems().indexOf(it)); });
  }

  // ---------------------------------------------------------------------------------
  // Calendar popover for DD.MM.YYYY inputs (typing still works).
  var CAL_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="w-5 h-5" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>';
  var CHEV_L = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="w-5 h-5" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>';
  var CHEV_R = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="w-5 h-5" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';
  var openCal = null;

  function parseDMY(s) {
    var m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec((s || "").trim());
    if (!m) return null;
    var d = new Date(+m[3], +m[2] - 1, +m[1]);
    return d.getMonth() === +m[2] - 1 ? d : null;
  }
  function fmtDMY(d) { return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear(); }
  function sameDay(a, b) { return a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
  function todayLocal() { var n = tashkentNow(); return n ? new Date(n.y, n.m - 1, n.d) : new Date(); }

  function closeCalendar(focusInput) {
    if (!openCal) return;
    var input = openCal.input;
    openCal.el.remove();
    openCal.btn.setAttribute("aria-expanded", "false");
    openCal = null;
    if (focusInput) input.focus();
  }
  function renderCalendar(state) {
    var el = state.el, view = state.view, sel = parseDMY(state.input.value), today = todayLocal();
    var first = new Date(view.getFullYear(), view.getMonth(), 1);
    var start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
    var html = '<div class="cal-head"><button type="button" class="btn-ghost btn-icon" data-cal-nav="-1" aria-label="' + (T.prev_month || "") + '">' + CHEV_L + "</button>" +
      '<span aria-live="polite">' + (T.months ? T.months[view.getMonth()] : view.getMonth() + 1) + " " + view.getFullYear() + "</span>" +
      '<button type="button" class="btn-ghost btn-icon" data-cal-nav="1" aria-label="' + (T.next_month || "") + '">' + CHEV_R + "</button></div>" +
      '<div class="cal-grid" role="grid">';
    (T.days_short || ["1", "2", "3", "4", "5", "6", "7"]).forEach(function (d) { html += '<span class="cal-dow" role="columnheader">' + d + "</span>"; });
    for (var i = 0; i < 42; i++) {
      var d = new Date(start); d.setDate(start.getDate() + i);
      var cls = "cal-day" + (d.getMonth() !== view.getMonth() ? " is-out" : "") + (sameDay(d, today) ? " is-today" : "");
      var focus = sameDay(d, state.focus) ? "0" : "-1";
      html += '<button type="button" role="gridcell" class="' + cls + '" data-cal-day="' + fmtDMY(d) + '" tabindex="' + focus + '" aria-selected="' + (sameDay(d, sel) ? "true" : "false") + '">' + d.getDate() + "</button>";
    }
    html += '</div><div class="cal-foot"><button type="button" class="btn-ghost" data-cal-today>' + (T.today || "") + '</button><button type="button" class="btn-ghost" data-cal-close>' + (T.close || "") + "</button></div>";
    el.innerHTML = html;
  }
  function openCalendar(input, btn) {
    closeCalendar(false);
    var sel = parseDMY(input.value) || todayLocal();
    var el = document.createElement("div");
    el.className = "cal";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", T.calendar || "");
    var state = { input: input, btn: btn, el: el, view: new Date(sel.getFullYear(), sel.getMonth(), 1), focus: sel };
    openCal = state;
    renderCalendar(state);
    input.parentNode.appendChild(el);
    btn.setAttribute("aria-expanded", "true");
    var r = el.getBoundingClientRect();
    if (r.right > window.innerWidth - 8) { el.style.left = "auto"; el.style.right = "0"; }
    if (r.bottom > window.innerHeight - 8 && r.top - r.height > 70) { el.style.top = "auto"; el.style.bottom = "calc(100% + 0.375rem)"; }
    var f = el.querySelector('.cal-day[tabindex="0"]');
    if (f) f.focus();
  }
  function moveFocus(days, months) {
    var s = openCal, d = new Date(s.focus);
    if (months) d.setMonth(d.getMonth() + months); else d.setDate(d.getDate() + days);
    s.focus = d;
    s.view = new Date(d.getFullYear(), d.getMonth(), 1);
    renderCalendar(s);
    var f = s.el.querySelector('.cal-day[tabindex="0"]');
    if (f) f.focus();
  }
  function pick(value) {
    var input = openCal.input;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    closeCalendar(true);
  }
  function enhanceDates(scope) {
    (scope || document).querySelectorAll("input[data-mask=date]:not([data-cal-ready])").forEach(function (input) {
      input.setAttribute("data-cal-ready", "");
      var wrap = document.createElement("span");
      // The wrapper takes the input's width classes (w-40, sm:w-44, ...); the input fills it.
      var widths = input.className.split(/\s+/).filter(function (c) { return /^(?:(?:sm|md|lg|xl):)?(?:max-|min-)?w-/.test(c); });
      widths.forEach(function (c) { input.classList.remove(c); });
      wrap.className = ["date-wrap"].concat(widths).join(" ");
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "date-btn";
      btn.setAttribute("aria-label", T.choose_date || "");
      btn.setAttribute("aria-haspopup", "dialog");
      btn.setAttribute("aria-expanded", "false");
      btn.innerHTML = CAL_ICON;
      if (input.disabled) btn.disabled = true;
      wrap.appendChild(btn);
    });
  }
  on("click", ".date-btn", function (e, btn) {
    e.preventDefault();
    var input = btn.parentNode.querySelector("input");
    if (openCal && openCal.input === input) closeCalendar(true); else openCalendar(input, btn);
  });
  on("click", "[data-cal-nav]", function (e, b) { e.preventDefault(); moveFocus(0, +b.getAttribute("data-cal-nav")); });
  on("click", "[data-cal-day]", function (e, b) { e.preventDefault(); pick(b.getAttribute("data-cal-day")); });
  on("click", "[data-cal-today]", function (e) { e.preventDefault(); pick(fmtDMY(todayLocal())); });
  on("click", "[data-cal-close]", function (e) { e.preventDefault(); closeCalendar(true); });
  document.addEventListener("mousedown", function (e) {
    if (openCal && !openCal.el.contains(e.target) && !openCal.btn.contains(e.target)) closeCalendar(false);
  });
  document.addEventListener("keydown", function (e) {
    if (!openCal || !openCal.el.contains(document.activeElement)) {
      if (openCal && e.key === "Escape") closeCalendar(true);
      return;
    }
    var map = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [-7, 0], ArrowDown: [7, 0], PageUp: [0, -1], PageDown: [0, 1] };
    if (e.key === "Escape") { e.preventDefault(); closeCalendar(true); }
    else if (map[e.key] && document.activeElement.hasAttribute("data-cal-day")) { e.preventDefault(); moveFocus(map[e.key][0], map[e.key][1]); }
  });

  // ---------------------------------------------------------------------------------
  // <button data-geolocate="submit|fill"> inside a [data-geo-box]: ask the phone for its GPS
  // position. "submit" fills the form's lat/lng/accuracy and submits it ("Keldim");
  // "fill" writes "lat, lng" into the box's [data-geo-coords] input (branch location).
  on("click", "[data-geolocate]", function (e, btn) {
    var box = btn.closest("[data-geo-box]");
    var err = box.querySelector("[data-geo-error]");
    function busy(onOff) {
      btn.disabled = onOff;
      box.querySelectorAll("[data-idle]").forEach(function (el) { el.hidden = onOff; });
      box.querySelectorAll("[data-busy]").forEach(function (el) { el.hidden = !onOff; });
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
        loading(true);
        form.submit();
      },
      function () { fail(box.getAttribute("data-denied")); },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
    );
  });

  // <select data-fill-target="id"> whose options carry data-text: choosing one copies
  // the text into the target field (message templates).
  on("change", "select[data-fill-target]", function (e, sel) {
    var opt = sel.options[sel.selectedIndex];
    var target = document.getElementById(sel.getAttribute("data-fill-target"));
    if (target && opt && opt.getAttribute("data-text")) target.value = opt.getAttribute("data-text");
  });

  // Keep CSRF on htmx requests.
  document.addEventListener("htmx:configRequest", function (e) {
    var token = document.querySelector("meta[name=csrf-token]");
    if (token) e.detail.headers["X-CSRFToken"] = token.content;
  });
  document.addEventListener("htmx:afterSwap", function (e) { enhanceDates(e.detail.target); });

  function init() {
    applyTheme(themeChoice());
    tick();
    document.querySelectorAll("[data-toast]").forEach(armToast);
    enhanceDates(document);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
