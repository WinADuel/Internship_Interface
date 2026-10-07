const REQUEST_PARTS = new Set(["body", "query", "path", "header", "cookie"]);

function formatValidationItem(item: unknown): string | null {
  if (typeof item === "string") return item || null;
  if (!item || typeof item !== "object") return null;
  const { loc, msg } = item as { loc?: unknown; msg?: unknown };
  if (typeof msg !== "string" || !msg) return null;
  const text = msg.replace(/^Value error, /, "");
  const path = Array.isArray(loc)
    ? loc.filter((part, i) => !(i === 0 && typeof part === "string" && REQUEST_PARTS.has(part)))
    : [];
  return path.length ? `${path.join(".")}: ${text}` : text;
}

/** Human-readable text for an error `detail`: a string as is, a FastAPI 422 array as "field: message" lines. */
function describeDetail(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map(formatValidationItem).filter((p): p is string => p !== null);
    if (parts.length) return parts.join("; ");
  }
  return `Request failed (${status})`;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(describeDetail(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

let refreshInFlight: Promise<boolean> | null = null;

function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch("/api/auth/refresh", { method: "POST", credentials: "include" })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isAuthPath = path.startsWith("/api/auth/");
  let response = await fetch(path, { ...options, credentials: "include" });
  if (response.status === 401 && !isAuthPath) {
    if (await refreshOnce()) {
      response = await fetch(path, { ...options, credentials: "include" });
    }
    if (response.status === 401) onUnauthorized?.();
  }
  if (!response.ok) {
    let detail: unknown = response.statusText || "Request failed";
    try {
      const body = await response.json();
      if (body && typeof body === "object" && "detail" in body) detail = body.detail;
    } catch {
      // non-JSON error body; keep fallback detail
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
