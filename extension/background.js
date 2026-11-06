// The only part of the extension that talks to InternHelper. Content scripts
// on job-board pages ask it for the answers; the InternHelper address and the
// token live in chrome.storage.local and never reach the page.

async function settings() {
  const { baseUrl = "", token = "" } = await chrome.storage.local.get(["baseUrl", "token"]);
  return { baseUrl: baseUrl.replace(/\/+$/, ""), token };
}

async function call(path, body) {
  const { baseUrl, token } = await settings();
  if (!baseUrl || !token) {
    return { ok: false, error: "Set your InternHelper address and token in the extension's options first." };
  }
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
    });
  } catch {
    return { ok: false, error: `Couldn't reach InternHelper at ${baseUrl}. Is it running?` };
  }
  if (response.status === 401) return { ok: false, error: "InternHelper refused the token. Make a new one in Settings › Apply profile." };
  if (!response.ok) return { ok: false, error: `InternHelper answered with HTTP ${response.status}.` };
  return { ok: true, data: await response.json() };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only this extension's own pages and content scripts can message it.
  if (sender.id !== chrome.runtime.id) return false;
  const url = typeof message?.url === "string" ? message.url : "";
  if (message?.type === "fill") call("/api/extension/fill", { url }).then(sendResponse);
  else if (message?.type === "applied") call("/api/extension/applied", { url }).then(sendResponse);
  else if (message?.type === "ping") call("/api/extension/ping").then(sendResponse);
  else return false;
  return true; // answering asynchronously
});

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
