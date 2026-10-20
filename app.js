(function () {
  "use strict";

  var D = window.FM_DATA || {};
  var $ = function (selector, context) { return (context || document).querySelector(selector); };
  var $$ = function (selector, context) { return Array.prototype.slice.call((context || document).querySelectorAll(selector)); };

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon() {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 9.2 17 19 7"/></svg>';
  }

  function renderServices() {
    var tabs = $("#serviceTabs");
    var panels = $("#servicePanels");
    var groups = D.serviceGroups || [];
    if (!tabs || !panels || !groups.length) return;

    groups.forEach(function (group, index) {
      var tab = make("button", "stab", group.title);
      tab.type = "button";
      tab.id = "service-tab-" + group.id;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", "service-panel-" + group.id);
      tab.setAttribute("aria-selected", index === 0 ? "true" : "false");
      tab.tabIndex = index === 0 ? 0 : -1;
      tabs.appendChild(tab);

      var panel = make("section", "spanel");
      panel.id = "service-panel-" + group.id;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      panel.hidden = index !== 0;

      var head = make("div", "sp-head");
      head.appendChild(make("h3", "sp-title", group.title));
      head.appendChild(make("span", "sp-count", (group.items || []).length + " services"));
      panel.appendChild(head);
      panel.appendChild(make("p", "sp-summary", group.summary || ""));

      var grid = make("div", "card-grid");
      (group.items || []).forEach(function (service) {
        var card = make("article", "scard");
        var mark = make("span", "scard-icon");
        mark.innerHTML = icon();
        var body = make("div", "scard-body");
        body.appendChild(make("h4", "", service));
        body.appendChild(make("p", "", (D.serviceDescriptions || {})[service] || "Professional property maintenance and repair.") );
        card.appendChild(mark);
        card.appendChild(body);
        grid.appendChild(card);
      });
      panel.appendChild(grid);
      panels.appendChild(panel);

      tab.addEventListener("click", function () { selectServiceGroup(group.id); });
    });

    $$('[data-service-link]').forEach(function (link) {
      link.addEventListener("click", function () {
        var id = link.getAttribute("data-service-link");
        if (groups.some(function (group) { return group.id === id; })) selectServiceGroup(id);
      });
    });

    function selectServiceGroup(id) {
      groups.forEach(function (group) {
        var active = group.id === id;
        var tab = $("#service-tab-" + group.id);
        var panel = $("#service-panel-" + group.id);
        if (tab) {
          tab.setAttribute("aria-selected", active ? "true" : "false");
          tab.tabIndex = active ? 0 : -1;
        }
        if (panel) panel.hidden = !active;
      });
    }
  }

  function renderGallery() {
    var grid = $("#workGrid");
    var projects = D.projects || [];
    if (!grid || !projects.length) return;

    projects.forEach(function (project) {
      var card = make("article", "work-card" + (project.extra && project.extra.length ? " is-wide" : ""));
      var head = make("header", "work-head");
      head.appendChild(make("p", "work-eyebrow", "FixMate project"));
      head.appendChild(make("h3", "work-title", project.title || "Completed work"));
      if (project.summary) head.appendChild(make("p", "work-summary", project.summary));
      card.appendChild(head);

      var body = make("div", "work-body");
      var side = make("div", "work-side");
      if (project.compare && project.compare.src) {
        var media = make("figure", "work-media");
        var image = document.createElement("img");
        image.src = project.compare.src;
        image.alt = project.compare.alt || ((project.title || "Property maintenance") + " before and after");
        image.width = project.compare.width || 1122;
        image.height = project.compare.height || 1402;
        image.loading = "lazy";
        image.decoding = "async";
        media.appendChild(image);
        side.appendChild(media);
        var legend = make("div", "work-legend");
        legend.appendChild(make("span", "work-chip", "Before & After"));
        side.appendChild(legend);
      }
      body.appendChild(side);

      if (project.extra && project.extra.length) {
        var extras = make("div", "work-extras");
        project.extra.forEach(function (photo) {
          var figure = make("figure", "work-extra");
          var image = document.createElement("img");
          image.src = photo.src;
          image.alt = photo.alt || project.title || "FixMate project photo";
          image.width = photo.width || 1200;
          image.height = photo.height || 1600;
          image.loading = "lazy";
          image.decoding = "async";
          figure.appendChild(image);
          if (photo.caption) figure.appendChild(make("figcaption", "", photo.caption));
          extras.appendChild(figure);
        });
        body.appendChild(extras);
      }
      card.appendChild(body);
      grid.appendChild(card);
    });
  }

  function renderWhyUs() {
    var grid = $("#whyGrid");
    if (!grid) return;
    (D.whyUs || []).forEach(function (item) {
      var card = make("li", "why-card");
      var mark = make("span", "why-icon");
      mark.innerHTML = icon();
      card.appendChild(mark);
      card.appendChild(make("h3", "", item.title || "Why choose FixMate"));
      card.appendChild(make("p", "", item.text || "Reliable property maintenance across London."));
      grid.appendChild(card);
    });
  }

  function initQuoteForm() {
    var form = $("#quoteForm");
    var select = $("#qService");
    var statusBox = $("#formStatus");
    var fallback = $("#qMailFallback");
    if (!form || !select) return;

    var options = D.formServices || D.services || [];
    select.innerHTML = '<option value="" disabled selected>Select a service</option>' + options.map(function (service) {
      return "<option></option>";
    }).join("");
    Array.prototype.slice.call(select.options, 1).forEach(function (option, index) {
      option.value = options[index];
      option.textContent = options[index];
    });

    var rules = [
      { id: "qName", test: function (value) { return value.trim().length > 1; }, message: "Please enter your full name." },
      { id: "qPhone", test: function (value) { return /^[0-9+\s()-]{6,}$/.test(value.trim()); }, message: "Please enter a valid phone number." },
      { id: "qEmail", test: function (value) { return !value || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim()); }, message: "Please enter a valid email address." },
      { id: "qService", test: function (value) { return Boolean(value); }, message: "Please select a type of service." },
      { id: "qDetails", test: function (value) { return value.trim().length >= 5; }, message: "Please briefly describe the work." }
    ];

    function clearError(input) {
      var field = input.closest(".field");
      if (field) {
        field.classList.remove("has-error");
        var message = field.querySelector(".err");
        if (message) message.textContent = "";
      }
      input.removeAttribute("aria-invalid");
    }
    function showError(input, message) {
      var field = input.closest(".field");
      if (field) {
        field.classList.add("has-error");
        var error = field.querySelector(".err");
        if (error) error.textContent = message;
      }
      input.setAttribute("aria-invalid", "true");
    }
    function validate() {
      var valid = true;
      var firstInvalid = null;
      rules.forEach(function (rule) {
        var input = document.getElementById(rule.id);
        if (!input) return;
        if (!rule.test(input.value)) {
          if (valid) firstInvalid = input;
          valid = false;
          showError(input, rule.message);
        } else clearError(input);
      });
      if (!valid && statusBox) {
        statusBox.hidden = false;
        statusBox.className = "form-status warn";
        statusBox.textContent = "Please check the highlighted fields and try again.";
      }
      return { valid: valid, firstInvalid: firstInvalid };
    }

    $$("input, textarea, select", form).forEach(function (input) {
      input.addEventListener("input", function () { if (input.getAttribute("aria-invalid")) clearError(input); });
      input.addEventListener("change", function () { if (input.getAttribute("aria-invalid")) clearError(input); });
    });

    function quoteDetails() {
      return {
        name: $("#qName").value.trim(),
        phone: $("#qPhone").value.trim(),
        email: $("#qEmail").value.trim(),
        service: select.value,
        details: $("#qDetails").value.trim()
      };
    }
    function openEmail() {
      var result = validate();
      if (!result.valid) { if (result.firstInvalid) result.firstInvalid.focus(); return; }
      var values = quoteDetails();
      var subject = "Quote request: " + values.service + " - " + values.name;
      var body = "Quote request - FixMate Services\r\n\r\nName: " + values.name + "\r\nPhone: " + values.phone + "\r\nEmail: " + (values.email || "n/a") + "\r\nService needed: " + values.service + "\r\nArea: " + ((D.contact || {}).area || "South & Central London") + "\r\n\r\nJob details:\r\n" + values.details;
      var gmailUrl = "https://mail.google.com/mail/?view=cm&fs=1&to=" + encodeURIComponent((D.contact || {}).email || "info@fixmateservices.co.uk") + "&su=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
      if (statusBox) {
        statusBox.hidden = false;
        statusBox.className = "form-status ok";
        statusBox.textContent = "Opening a Gmail draft. Please review it and press Send.";
      }
      window.open(gmailUrl, "_blank", "noopener");
    }

    if (fallback) fallback.addEventListener("click", function (event) { event.preventDefault(); openEmail(); });
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var result = validate();
      if (!result.valid) { if (result.firstInvalid) result.firstInvalid.focus(); return; }
      var values = quoteDetails();
      var message = "Hello FixMate Services, I'd like a quote.\n\nName: " + values.name + "\nService: " + values.service + "\nPhone: " + values.phone + "\n" + (values.email ? "Email: " + values.email + "\n" : "") + "Details: " + values.details;
      var whatsapp = (D.contact || {}).whatsapp || "447784044111";
      if (statusBox) {
        statusBox.hidden = false;
        statusBox.className = "form-status ok";
        statusBox.textContent = "Opening WhatsApp with your quote details. Press Send there to complete your request.";
      }
      window.open("https://wa.me/" + whatsapp + "?text=" + encodeURIComponent(message), "_blank", "noopener");
    });
  }

  function init() {
    renderServices();
    renderGallery();
    renderWhyUs();
    initQuoteForm();
    var year = $("#year");
    if (year) year.textContent = String(new Date().getFullYear());
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
