const form = document.getElementById("form");
const baseInput = document.getElementById("baseUrl");
const tokenInput = document.getElementById("token");
const status = document.getElementById("status");

function show(text, ok) {
  status.textContent = text;
  status.className = ok ? "ok" : "err";
}

chrome.storage.local.get(["baseUrl", "token"]).then(({ baseUrl = "", token = "" }) => {
  baseInput.value = baseUrl;
  tokenInput.value = token;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  let origin;
  try {
    const url = new URL(baseInput.value.trim());
    if (url.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(url.hostname)) {
      show("Use an https:// address (http:// only works for localhost).", false);
      return;
    }
    origin = url.origin;
  } catch {
    show("That isn't a web address.", false);
    return;
  }
  const token = tokenInput.value.trim();
  if (!token.startsWith("ih_")) {
    show("Extension tokens start with ih_. Make one in InternHelper's Settings.", false);
    return;
  }
  // Chrome asks you once to let the extension reach your InternHelper address.
  const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
  if (!granted) {
    show("The extension needs permission to reach your InternHelper address.", false);
    return;
  }
  await chrome.storage.local.set({ baseUrl: origin, token });
  const result = await chrome.runtime.sendMessage({ type: "ping" });
  if (result?.ok) show("Connected to InternHelper. Open a job application to fill it.", true);
  else show(result?.error || "Couldn't reach InternHelper.", false);
});
