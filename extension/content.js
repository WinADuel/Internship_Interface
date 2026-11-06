// Runs on Greenhouse, Lever and Ashby pages. Shows a small InternHelper
// panel when the page has an application form; "Fill application" fills it
// with your approved answers. You check the page and click Submit yourself.
// After the board's thank-you page appears, the job is marked Applied.

(function () {
  "use strict";

  const PENDING_KEY = "internhelper-submitted";
  const PENDING_MAX_MS = 30 * 60 * 1000;
  const { fillPage, looksSubmitted } = window.InternHelperFill;

  let panel = null;
  let statusEl = null;
  let appliedButton = null;
  let lastFillUrl = null;

  function hasForm() {
    return !!document.querySelector(
      "#application-form, form#application_form, form[action*='apply'], input[name=email], #email, #_systemfield_email, input[name=_systemfield_email]",
    );
  }

  function send(type, url) {
    return chrome.runtime.sendMessage({ type, url }).catch(() => ({ ok: false, error: "The extension was reloaded; refresh this page." }));
  }

  function setStatus(text, tone) {
    statusEl.textContent = text;
    statusEl.dataset.tone = tone || "";
  }

  function list(items) {
    items = items.map((label) => (label.length > 60 ? `${label.slice(0, 57)}…` : label));
    return items.length > 4 ? `${items.slice(0, 4).join(", ")} and ${items.length - 4} more` : items.join(", ");
  }

  async function onFill(button) {
    button.disabled = true;
    setStatus("Getting your answers from InternHelper…");
    const result = await send("fill", location.href);
    if (!result || !result.ok) {
      setStatus(result?.error || "Couldn't reach InternHelper.", "error");
      button.disabled = false;
      return;
    }
    const data = result.data;
    setStatus("Filling…");
    const report = await fillPage(document, data);
    lastFillUrl = location.href;
    const parts = [`Filled ${report.filled.length} field${report.filled.length === 1 ? "" : "s"}.`];
    if (data.message) parts.unshift(data.message);
    if (report.needsYou.length) parts.push(`Still needs you: ${list(report.needsYou)}.`);
    if (report.failed.length) parts.push(`Couldn't fill: ${list(report.failed)}. Fill these by hand.`);
    parts.push("Check everything (fields are outlined), then click Submit yourself.");
    setStatus(parts.join(" "), report.failed.length || report.needsYou.length ? "warn" : "ok");
    button.disabled = false;
    button.textContent = "Fill again";
    if (data.posting && data.posting.state !== "applied") appliedButton.hidden = false;
  }

  async function markApplied(url) {
    const result = await send("applied", url);
    if (result?.ok && result.data.status === "applied") setStatus("Marked Applied in InternHelper.", "ok");
    else if (result?.ok && result.data.status === "already_applied") setStatus("Already marked Applied in InternHelper.", "ok");
    else if (result?.ok) setStatus("This job isn't saved in InternHelper, so nothing was marked.", "warn");
    else setStatus(result?.error || "Couldn't reach InternHelper.", "error");
    if (result?.ok) appliedButton.hidden = true;
  }

  function buildPanel() {
    const host = document.createElement("div");
    host.id = "internhelper-panel";
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;";
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>
        .box { font: 13px/1.4 system-ui, sans-serif; background: #fff; color: #222; border: 1px solid #ccc;
               border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,.15); padding: 10px 12px; max-width: 300px; }
        .head { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-weight: 600; }
        button { font: inherit; padding: 4px 10px; cursor: pointer; }
        .row { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
        .close { border: none; background: none; font-size: 16px; padding: 0 4px; }
        .status { margin-top: 6px; }
        .status[data-tone=error] { color: #a00; } .status[data-tone=warn] { color: #7a4f00; } .status[data-tone=ok] { color: #14532d; }
      </style>
      <div class="box" role="region" aria-label="InternHelper">
        <div class="head"><span>InternHelper</span><button class="close" aria-label="Hide">×</button></div>
        <div class="row">
          <button class="fill">Fill application</button>
          <button class="applied" hidden>I submitted it: mark Applied</button>
        </div>
        <div class="status" role="status">Fills this form with your approved answers. It never clicks Submit.</div>
      </div>`;
    statusEl = shadow.querySelector(".status");
    appliedButton = shadow.querySelector(".applied");
    const fill = shadow.querySelector(".fill");
    fill.addEventListener("click", () => onFill(fill));
    appliedButton.addEventListener("click", () => markApplied(lastFillUrl || location.href));
    shadow.querySelector(".close").addEventListener("click", () => host.remove());
    document.documentElement.appendChild(host);
    return host;
  }

  // Remember a submit click, so the thank-you page that follows marks the job Applied.
  document.addEventListener(
    "click",
    (event) => {
      if (!lastFillUrl) return;
      const target = event.target instanceof Element ? event.target.closest("button, input[type=submit]") : null;
      if (!target) return;
      const text = (target.textContent || target.value || "").toLowerCase();
      if (target.type === "submit" || /submit/.test(text)) {
        try {
          sessionStorage.setItem(PENDING_KEY, JSON.stringify({ url: lastFillUrl, at: Date.now() }));
        } catch {
          // storage blocked: the manual button still works
        }
      }
    },
    true,
  );

  function pending() {
    try {
      const raw = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null");
      return raw && Date.now() - raw.at < PENDING_MAX_MS ? raw : null;
    } catch {
      return null;
    }
  }

  let reported = false;
  function check() {
    const submitted = pending();
    if (!reported && submitted && looksSubmitted(document, location.href)) {
      reported = true;
      try {
        sessionStorage.removeItem(PENDING_KEY);
      } catch {
        // ignore
      }
      if (!panel) panel = buildPanel();
      void markApplied(submitted.url);
      return;
    }
    if (!panel && hasForm()) panel = buildPanel();
    // Greenhouse's page re-renders the whole document when it hydrates, which drops
    // anything added to it: put the panel (and its state) back.
    else if (panel && !panel.isConnected) document.documentElement.appendChild(panel);
  }

  check();
  // Ashby and Greenhouse render their forms (and thank-you messages) after load.
  let timer = null;
  const observer = new MutationObserver(() => {
    if (timer === null) timer = setTimeout(() => ((timer = null), check()), 300);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(() => observer.disconnect(), 10 * 60 * 1000);
})();
