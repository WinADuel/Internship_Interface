import { apiFetch } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import { mapApplicationFromApi } from "./applications";
import type { Application } from "../types/application";
import type {
  DiscoveryFilters,
  PasteConfirmInput,
  PastePreview,
  Posting,
  PostingPage,
  PostingView,
  ScanStarted,
  ScanStatus,
  WatchCompany,
  WatchCompanyInput,
} from "../types/discovery";

type Raw = Record<string, unknown>;

const JSON_HEADERS = { "Content-Type": "application/json" };

/** Postings per page on the Discover lists (the backend allows 1..100). */
export const POSTINGS_PAGE_SIZE = 50;

/** The filter fields the match count sends; anything else on the argument is left out. */
const FILTER_KEYS: ReadonlyArray<keyof DiscoveryFilters> = [
  "discoveryTerms",
  "discoveryCategories",
  "discoveryIncludeKeywords",
  "discoveryWatchlistKeywords",
  "discoveryExcludeKeywords",
  "discoveryLocations",
  "discoveryHideNoSponsorship",
];

function post(body?: unknown): RequestInit {
  return body === undefined
    ? { method: "POST" }
    : { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

export function mapPostingFromApi(raw: Raw): Posting {
  const posting = keysToCamel<Posting>(raw);
  return { ...posting, locations: stringList(raw.locations), terms: stringList(raw.terms) };
}

function mapWatchCompanyFromApi(raw: Raw): WatchCompany {
  return keysToCamel<WatchCompany>(raw);
}

// --- postings -------------------------------------------------------------------

export async function listPostings(
  view: PostingView = "inbox",
  opts: { limit?: number; offset?: number } = {},
): Promise<PostingPage> {
  const params = new URLSearchParams({
    view,
    limit: String(opts.limit ?? POSTINGS_PAGE_SIZE),
    offset: String(opts.offset ?? 0),
  });
  const raw = await apiFetch<{ items: Raw[]; total: number }>(`/api/discovery/postings?${params}`);
  return { items: raw.items.map(mapPostingFromApi), total: raw.total };
}

export async function savePosting(id: number): Promise<Posting> {
  return mapPostingFromApi(await apiFetch<Raw>(`/api/discovery/postings/${id}/save`, post()));
}

export async function dismissPosting(id: number): Promise<Posting> {
  return mapPostingFromApi(await apiFetch<Raw>(`/api/discovery/postings/${id}/dismiss`, post()));
}

export async function restorePosting(id: number): Promise<Posting> {
  return mapPostingFromApi(await apiFetch<Raw>(`/api/discovery/postings/${id}/restore`, post()));
}

/** Turns a saved posting into an Applied application (201); 409 if it is not saved. */
export async function applyToPosting(id: number): Promise<Application> {
  return mapApplicationFromApi(await apiFetch<Raw>(`/api/discovery/postings/${id}/apply`, post()));
}

/** Dismisses the given Inbox postings; returns how many were dismissed. */
export async function dismissAllPostings(ids: number[]): Promise<number> {
  const raw = await apiFetch<{ dismissed: number }>("/api/discovery/postings/dismiss-all", post({ ids }));
  return raw.dismissed;
}

// --- paste a link -----------------------------------------------------------------

/** Reads a posting page without saving anything; 422 carries a readable message. */
export async function previewPaste(url: string): Promise<PastePreview> {
  return keysToCamel<PastePreview>(await apiFetch<Raw>("/api/discovery/paste/preview", post({ url })));
}

/** Saves the confirmed fields; the posting lands in Saved (201). */
export async function confirmPaste(data: PasteConfirmInput): Promise<Posting> {
  return mapPostingFromApi(await apiFetch<Raw>("/api/discovery/paste", post(keysToSnake(data))));
}

// --- watchlist ----------------------------------------------------------------------

export async function listWatchlist(): Promise<WatchCompany[]> {
  const raw = await apiFetch<Raw[]>("/api/discovery/watchlist");
  return raw.map(mapWatchCompanyFromApi);
}

/** 422 for an unsupported careers site (readable message), 409 for a duplicate. */
export async function addWatchCompany(data: WatchCompanyInput): Promise<WatchCompany> {
  return mapWatchCompanyFromApi(await apiFetch<Raw>("/api/discovery/watchlist", post(keysToSnake(data))));
}

export async function removeWatchCompany(id: number): Promise<void> {
  await apiFetch<void>(`/api/discovery/watchlist/${id}`, { method: "DELETE" });
}

// --- scan, status, match count ------------------------------------------------------

/** Starts a background scan (202); a running scan rejects with ApiError 409 "already scanning". */
export async function startScan(): Promise<ScanStarted> {
  return keysToCamel<ScanStarted>(await apiFetch<Raw>("/api/discovery/scan", post()));
}

export async function getScanStatus(): Promise<ScanStatus> {
  return keysToCamel<ScanStatus>(await apiFetch<Raw>("/api/discovery/status"));
}

/** How many Inbox postings the given (unsaved) filters would show. */
export async function getMatchCount(filters: DiscoveryFilters): Promise<number> {
  const body: Partial<DiscoveryFilters> = {};
  for (const key of FILTER_KEYS) {
    if (key in filters) (body as Record<string, unknown>)[key] = filters[key];
  }
  const raw = await apiFetch<{ count: number }>("/api/discovery/match-count", post(keysToSnake(body)));
  return raw.count;
}
