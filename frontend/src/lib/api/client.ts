export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, credentials: "include" });
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
