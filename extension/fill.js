// Fills a Greenhouse, Lever or Ashby application form with the answers
// InternHelper sends. It types into fields and picks options; it never
// clicks Submit or anything that sends the form.
//
// Each field from InternHelper has the board's own key: on Greenhouse that is
// the input's id, on Lever its name, on Ashby its id or name. When the key
// isn't on the page (the board changed its markup) the field's label is
// matched instead.

(function (root) {
  "use strict";

  const WAIT_MS = 1500;
  const STEP_MS = 50;

  function norm(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9+]+/g, " ")
      .trim();
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitFor(fn, ms = WAIT_MS) {
    const end = Date.now() + ms;
    for (;;) {
      const found = fn();
      if (found) return found;
      if (Date.now() >= end) return null;
      await sleep(STEP_MS);
    }
  }

  // --- finding a field ---------------------------------------------------------

  function byId(doc, id) {
    try {
      return doc.getElementById(id);
    } catch {
      return null;
    }
  }

  function controlsIn(el) {
    if (!el) return [];
    return Array.from(el.querySelectorAll("input:not([type=hidden]), textarea, select"));
  }

  function labelText(el) {
    if (!el) return "";
    if (el.labels && el.labels.length) return el.labels[0].textContent || "";
    const wrapping = el.closest("label");
    if (wrapping) return wrapping.textContent || "";
    return el.getAttribute("aria-label") || "";
  }

  function container(el) {
    return (
      el.closest(
        ".field, .application-question, li, fieldset, [class*='fieldEntry'], [class*='question'], .select, .text-input-wrapper",
      ) ||
      el.parentElement?.parentElement ||
      el.parentElement ||
      el
    );
  }

  function byLabel(doc, label) {
    const want = norm(label).slice(0, 80);
    if (!want) return null;
    const candidates = Array.from(doc.querySelectorAll("label, legend, .application-label, [class*='heading']"));
    const match = candidates.find((l) => norm(l.textContent).startsWith(want));
    if (!match) return null;
    if (match.htmlFor) {
      const target = byId(doc, match.htmlFor);
      if (target) return target;
    }
    const inside = controlsIn(match)[0];
    if (inside) return inside;
    return controlsIn(container(match))[0] || null;
  }

  /** The element (and, for radios and checkboxes, the group) for a field. */
  function locate(doc, field) {
    let el = byId(doc, field.key);
    let group = [];
    const named = Array.from(doc.getElementsByName(field.key));
    if (!el && named.length) el = named[0];
    if (el && el.tagName !== "INPUT" && el.tagName !== "TEXTAREA" && el.tagName !== "SELECT") {
      // An id on a wrapper (some Ashby fields): use its control, or keep the wrapper for buttons.
      group = controlsIn(el);
      el = group.length === 1 ? group[0] : el;
    }
    if (!el) el = byLabel(doc, field.label);
    if (!el) return null;
    if (el.type === "radio" || el.type === "checkbox") {
      group = named.length > 1 ? named : el.name ? Array.from(doc.getElementsByName(el.name)) : [el];
    }
    return { el, group };
  }

  // --- setting values ------------------------------------------------------------------

  function setNative(el, value) {
    const proto = el.tagName === "TEXTAREA" ? root.HTMLTextAreaElement.prototype : root.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new root.Event("input", { bubbles: true }));
    el.dispatchEvent(new root.Event("change", { bubbles: true }));
  }

  function blur(el) {
    el.dispatchEvent(new root.Event("blur", { bubbles: true }));
    el.dispatchEvent(new root.FocusEvent("focusout", { bubbles: true }));
  }

  function bestMatch(items, label, textOf) {
    const want = norm(label);
    if (!want) return null;
    const exact = items.find((i) => norm(textOf(i)) === want);
    if (exact) return exact;
    const starts = items.filter((i) => norm(textOf(i)).startsWith(want));
    if (starts.length === 1) return starts[0];
    if (starts.length > 1) {
      // "United States +1" over "United States Minor Outlying Islands +1".
      const lengths = starts.map((i) => norm(textOf(i)).length);
      const shortest = Math.min(...lengths);
      if (lengths.filter((n) => n === shortest).length === 1) return starts[lengths.indexOf(shortest)];
    }
    const contains = items.filter((i) => norm(textOf(i)).includes(want));
    return contains.length === 1 ? contains[0] : null;
  }

  function fillSelect(select, value) {
    const option = bestMatch(Array.from(select.options), value, (o) => o.textContent || o.value);
    if (!option) return false;
    select.value = option.value;
    select.dispatchEvent(new root.Event("input", { bubbles: true }));
    select.dispatchEvent(new root.Event("change", { bubbles: true }));
    return true;
  }

  function choiceText(input) {
    return labelText(input) || input.value;
  }

  function fillChoices(group, values) {
    const wanted = Array.isArray(values) ? values : [values];
    let done = 0;
    for (const value of wanted) {
      const input = bestMatch(group, value, choiceText);
      if (!input) continue;
      if (!input.checked) input.click();
      done += 1;
    }
    return done === wanted.length && done > 0;
  }

  function click(el) {
    for (const type of ["mousedown", "mouseup", "click"]) {
      el.dispatchEvent(new root.MouseEvent(type, { bubbles: true, cancelable: true, button: 0 }));
    }
  }

  function visibleOptions(doc) {
    return Array.from(doc.querySelectorAll("[role='option'], .select__option"));
  }

  /** A react-select style combobox (Greenhouse's selects, some Ashby fields): open, type, pick. */
  async function fillCombobox(doc, input, values) {
    const wanted = Array.isArray(values) ? values : [values];
    let done = 0;
    for (const value of wanted) {
      input.focus();
      const control = input.closest(".select__control, [class*='control']") || input;
      click(control);
      input.dispatchEvent(new root.KeyboardEvent("keydown", { bubbles: true, key: "ArrowDown" }));
      // Typing narrows long lists (schools, countries) to the match.
      setNative(input, value);
      const option = await waitFor(() => bestMatch(visibleOptions(doc), value, (o) => o.textContent));
      if (option) {
        click(option);
        done += 1;
      } else {
        setNative(input, "");
        input.dispatchEvent(new root.KeyboardEvent("keydown", { bubbles: true, key: "Escape" }));
      }
      await sleep(STEP_MS);
    }
    blur(input);
    return done === wanted.length && done > 0;
  }

  /** Ashby's Yes / No buttons. */
  function fillButtons(scope, value) {
    const buttons = Array.from(scope.querySelectorAll("button"));
    const button = bestMatch(buttons, value, (b) => b.textContent);
    if (!button) return false;
    if (button.getAttribute("aria-pressed") !== "true") button.click();
    return true;
  }

  function fileFrom(resume) {
    const bytes = Uint8Array.from(root.atob(resume.data_base64), (c) => c.charCodeAt(0));
    return new root.File([bytes], resume.filename, { type: resume.content_type });
  }

  function fillFile(input, resume) {
    if (!resume || !root.DataTransfer) return false;
    const transfer = new root.DataTransfer();
    transfer.items.add(fileFrom(resume));
    input.files = transfer.files;
    input.dispatchEvent(new root.Event("input", { bubbles: true }));
    input.dispatchEvent(new root.Event("change", { bubbles: true }));
    return true;
  }

  function isEmpty(value) {
    return Array.isArray(value) ? value.length === 0 : !String(value || "").trim();
  }

  async function fillField(doc, field, resume) {
    const found = locate(doc, field);
    if (!found) return { status: "missing" };
    const { el, group } = found;
    const value = field.value;
    let ok = false;
    if (field.kind === "file") {
      const input = el.type === "file" ? el : container(el).querySelector("input[type=file]");
      ok = !!input && fillFile(input, resume);
      return { status: ok ? "filled" : "failed", el: input || el };
    }
    if (el.tagName === "SELECT") ok = fillSelect(el, Array.isArray(value) ? value[0] : value);
    else if (group.length) ok = fillChoices(group, value);
    else if (el.getAttribute && el.getAttribute("role") === "combobox") ok = await fillCombobox(doc, el, value);
    else if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      setNative(el, Array.isArray(value) ? value.join(", ") : value);
      blur(el);
      ok = true;
    } else {
      // A wrapper with buttons (Ashby yes/no) or choices inside.
      const choices = controlsIn(el).filter((c) => c.type === "radio" || c.type === "checkbox");
      ok = choices.length ? fillChoices(choices, value) : fillButtons(el, Array.isArray(value) ? value[0] : value);
    }
    return { status: ok ? "filled" : "failed", el };
  }

  // --- profile only (the job isn't saved in InternHelper) ---------------------------------

  const PROFILE_RULES = [
    { keys: ["first_name"], label: /^(legal )?first name/, value: (p) => p.first_name },
    { keys: ["last_name"], label: /^(legal )?last name/, value: (p) => p.last_name },
    { keys: ["name", "_systemfield_name"], label: /^(full |legal )?name$/, value: (p) => [p.first_name, p.last_name].filter(Boolean).join(" ") },
    { keys: ["email", "_systemfield_email"], label: /^e ?mail/, value: (p) => p.email },
    { keys: ["phone"], label: /^phone/, value: (p) => p.phone },
    { keys: ["org"], label: /^current company/, value: (p) => p.current_company },
    { keys: ["urls[LinkedIn]"], label: /linkedin/, value: (p) => p.linkedin_url },
    { keys: ["urls[GitHub]"], label: /github/, value: (p) => p.github_url },
    { keys: ["urls[Portfolio]"], label: /^(website|portfolio)/, value: (p) => p.website_url },
  ];

  function profileFields(doc, profile) {
    const fields = [];
    const controls = Array.from(doc.querySelectorAll("input[type=text], input[type=email], input[type=tel], input:not([type])"));
    for (const rule of PROFILE_RULES) {
      const value = rule.value(profile || {});
      if (!value) continue;
      let key = rule.keys.find((k) => byId(doc, k) || doc.getElementsByName(k).length);
      if (!key) {
        const el = controls.find((c) => rule.label.test(norm(labelText(c))));
        if (!el) continue;
        key = el.id || el.name;
        if (!key) continue;
      }
      fields.push({ key, label: key, kind: "text", value, required: false, section: "application", options: [] });
    }
    return fields;
  }

  // --- the whole page ----------------------------------------------------------------

  function mark(el, ok) {
    if (!el || !el.style) return;
    el.style.outline = ok ? "2px solid #2e9d4f" : "2px solid #e0a100";
    el.style.outlineOffset = "1px";
  }

  /**
   * Fills every field that has a value. Returns what happened, so the panel
   * can say what was filled and what still needs the owner.
   */
  async function fillPage(doc, data) {
    const fields = data.fields && data.fields.length ? data.fields.slice() : profileFields(doc, data.profile);
    // Greenhouse asks for the phone number's country in a field its API doesn't list.
    const country = data.profile && data.profile.country;
    if (country && byId(doc, "country") && !fields.some((f) => f.key === "country")) {
      fields.unshift({ key: "country", label: "Country", kind: "select", value: country, required: false, options: [] });
    }
    const report = { filled: [], failed: [], needsYou: [] };
    for (const field of fields) {
      if (isEmpty(field.value)) {
        if (field.required) {
          report.needsYou.push(field.label);
          const found = locate(doc, field);
          if (found) mark(found.el, false);
        }
        continue;
      }
      let result;
      try {
        result = await fillField(doc, field, data.resume);
      } catch {
        result = { status: "failed" };
      }
      if (result.status === "filled") {
        report.filled.push(field.label);
        mark(result.el, true);
      } else {
        report.failed.push(field.label);
        if (result.el) mark(result.el, false);
      }
    }
    return report;
  }

  // Thank-you pages after a submit, on all three boards.
  const CONFIRMATION = /thank(s| you) for (applying|your (application|interest))|application (has been |was )?(submitted|received)|we('ve| have) received your application/i;

  function looksSubmitted(doc, url) {
    if (/\/thanks\/?$|\/confirmation\/?$|\/application\/success/i.test(new URL(url).pathname)) return true;
    const text = (doc.body && doc.body.innerText) || (doc.body && doc.body.textContent) || "";
    return CONFIRMATION.test(text.slice(0, 20000));
  }

  const api = { fillPage, fillField, locate, looksSubmitted, profileFields, norm };
  root.InternHelperFill = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
