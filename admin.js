(function () {
  "use strict";

  var state = { csrf: "", username: "", status: "" };
  var el = {
    loginView: document.getElementById("loginView"),
    dashView: document.getElementById("dashView"),
    loginForm: document.getElementById("loginForm"),
    loginMsg: document.getElementById("loginMsg"),
    globalMsg: document.getElementById("globalMsg"),
    list: document.getElementById("list"),
    settings: document.getElementById("settings"),
    settingsWarn: document.getElementById("settingsWarn"),
    filters: document.getElementById("filters"),
    logoutBtn: document.getElementById("logoutBtn")
  };

  function show(node, visible) { node.classList.toggle("hidden", !visible); }

  function message(node, text, kind) {
    node.textContent = text;
    node.className = "msg " + (kind === "ok" ? "msg-ok" : "msg-err");
    show(node, true);
  }

  function api(path, options) {
    var opts = options || {};
    var headers = { "Accept": "application/json" };
    if (opts.body) headers["Content-Type"] = "application/json";
    if (opts.method && opts.method !== "GET" && state.csrf) {
      headers["X-FixMate-CSRF"] = state.csrf;
    }
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      credentials: "same-origin",
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (response) {
      return response.json().catch(function () { return {}; })
        .then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
    });
  }

  function statusPill(status) {
    return '<span class="pill pill-' + status.toLowerCase() + '">' + status + "</span>";
  }

  function row(label, value) {
    if (!value) return "";
    return "<div><b>" + label + "</b><span>" + escapeHtml(value) + "</span></div>";
  }

  function escapeHtml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function card(booking) {
    var actions = "";
    if (booking.status === "Pending") {
      actions +=
        '<button class="btn btn-green" data-action="confirm" data-id="' + booking.id + '">Confirm</button>';
    }
    if (booking.status !== "Cancelled") {
      actions +=
        '<button class="btn btn-red" data-action="cancel" data-id="' + booking.id + '">Cancel</button>';
    }
    var link = 'tel:' + booking.phone.replace(/[^\d+]/g, "");

    return (
      '<article class="bk">' +
      '<div class="bk-top">' +
      '<div><div class="bk-when">' + escapeHtml(booking.summary) + "</div>" +
      '<div class="bk-ref">' + escapeHtml(booking.reference) + " &middot; " +
      escapeHtml(booking.service_type) + "</div></div>" +
      statusPill(booking.status) +
      "</div>" +
      '<div class="bk-grid">' +
      row("Name", booking.full_name) +
      row("Phone", booking.phone + "  ") +
      row("Email", booking.email) +
      row("Address", booking.property_address) +
      row("Postcode", booking.postcode) +
      row("Job", booking.job_description) +
      "</div>" +
      '<div class="bk-actions">' +
      '<a class="btn btn-line" href="' + link + '">Call ' + escapeHtml(booking.phone) + "</a>" +
      actions +
      "</div></article>"
    );
  }

  function renderBookings(bookings) {
    if (!bookings.length) {
      el.list.innerHTML = '<p class="bk-ref">No bookings in this view.</p>';
      return;
    }
    var upcoming = bookings.filter(function (b) { return b.status !== "Cancelled"; });
    var cancelled = bookings.filter(function (b) { return b.status === "Cancelled"; });
    var html = "";
    if (upcoming.length) {
      html += "<h2>Active &middot; " + upcoming.length + "</h2>" +
        upcoming.map(card).join("");
    }
    if (cancelled.length) {
      html += "<h2 style='margin-top:20px'>Cancelled &middot; " + cancelled.length + "</h2>" +
        cancelled.map(card).join("");
    }
    el.list.innerHTML = html;
  }

  function loadBookings() {
    var path = "/api/admin/bookings";
    if (state.status) path += "?status=" + encodeURIComponent(state.status);
    return api(path).then(function (res) {
      if (res.status === 401) return signedOut();
      renderBookings(res.data.bookings || []);
    });
  }

  function loadSettings() {
    return api("/api/admin/settings").then(function (res) {
      if (res.status === 401) return signedOut();
      var d = res.data;

      if (!d.accepting_bookings) {
        el.settingsWarn.innerHTML =
          '<div class="warn">Booking is <b>closed</b> until ' +
          escapeHtml(d.opening_closed_until) +
          ". Customers cannot book. This is the safety switch in server/config.json.</div>";
      }
      if (!d.notify_configured) {
        el.settingsWarn.innerHTML +=
          '<div class="warn">Google Sheets copy via n8n is <b>not configured</b>. ' +
          "Bookings are still saved safely in the database; only the spreadsheet copy is missing.</div>";
      }

      var days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
      var names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
      var hoursRows = days.map(function (key, i) {
        var windows = (d.working_hours || {})[key] || [];
        var text = windows.length
          ? windows.map(function (w) { return w[0] + "&ndash;" + w[1]; }).join(", ")
          : "closed";
        return "<tr><td>" + names[i] + "</td><td>" + text + "</td></tr>";
      }).join("");

      el.settings.innerHTML =
        '<table class="cfg"><tbody>' +
        "<tr><th>Timezone</th><td>" + escapeHtml(d.timezone) + "</td></tr>" +
        "<tr><th>Appointment length</th><td>" + d.appointment_duration_minutes + " minutes</td></tr>" +
        "<tr><th>Slot spacing</th><td>" + d.slot_granularity_minutes + " minutes</td></tr>" +
        "<tr><th>Minimum notice</th><td>" + d.min_notice_hours + " hours</td></tr>" +
        "<tr><th>Booking window</th><td>" + d.max_advance_days + " days ahead</td></tr>" +
        "<tr><th>Treated as busy</th><td>" + escapeHtml((d.busy_statuses || []).join(", ")) + "</td></tr>" +
        "<tr><th>Booked slots shown</th><td>" + (d.show_booked_slots ? "yes, marked Booked" : "hidden") + "</td></tr>" +
        "<tr><th>Holidays</th><td>" + escapeHtml((d.holidays || []).join(", ") || "none") + "</td></tr>" +
        "<tr><th>Closures</th><td>" + escapeHtml((d.closures || []).join(", ") || "none") + "</td></tr>" +
        "</tbody></table>" +
        '<table class="cfg" style="margin-top:14px"><thead><tr><th>Day</th><th>Working hours</th></tr></thead>' +
        "<tbody>" + hoursRows + "</tbody></table>";
    });
  }

  function refresh() {
    show(el.globalMsg, false);
    return Promise.all([loadBookings(), loadSettings()]);
  }

  function signedOut() {
    state.csrf = "";
    show(el.dashView, false);
    show(el.loginView, true);
  }

  el.loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    var username = document.getElementById("username").value;
    var password = document.getElementById("password").value;
    api("/api/admin/login", {
      method: "POST",
      body: { username: username, password: password }
    }).then(function (res) {
      if (!res.ok) {
        message(el.loginMsg, res.data.message || "Sign in failed.", "err");
        return;
      }
      state.csrf = res.data.csrf;
      state.username = res.data.username;
      show(el.loginMsg, false);
      show(el.loginView, false);
      show(el.dashView, true);
      document.getElementById("password").value = "";
      refresh();
    }).catch(function () {
      message(el.loginMsg, "Network problem. Try again.", "err");
    });
  });

  el.logoutBtn.addEventListener("click", function () {
    api("/api/admin/logout", { method: "POST", body: {} }).then(signedOut);
  });

  el.filters.addEventListener("click", function (event) {
    var button = event.target.closest(".chip");
    if (!button) return;
    state.status = button.getAttribute("data-status");
    Array.prototype.forEach.call(el.filters.querySelectorAll(".chip"), function (chip) {
      chip.classList.toggle("is-active", chip === button);
    });
    loadBookings();
  });

  el.list.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-action]");
    if (!button) return;
    var id = button.getAttribute("data-id");
    var action = button.getAttribute("data-action");
    var target = action === "confirm" ? "Confirmed" : "Cancelled";
    button.disabled = true;

    api("/api/admin/bookings/" + encodeURIComponent(id) + "/status", {
      method: "POST",
      body: { status: target, note: action === "cancel" ? "cancelled in admin" : "" }
    }).then(function (res) {
      if (!res.ok) {
        message(el.globalMsg, res.data.message || "Could not update that booking.", "err");
        button.disabled = false;
        return;
      }
      message(el.globalMsg, "Booking " + res.data.booking.reference + " is now " + target + ".", "ok");
      refresh();
    }).catch(function () {
      message(el.globalMsg, "Network problem. Try again.", "err");
      button.disabled = false;
    });
  });

  api("/api/admin/session").then(function (res) {
    if (!res.ok) return signedOut();
    state.csrf = res.data.csrf;
    state.username = res.data.username;
    show(el.loginView, false);
    show(el.dashView, true);
    refresh();
  }).catch(signedOut);
})();