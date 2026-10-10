// String unions mirror the backend enums exactly (app/models/posting.py, watch_company.py).
export type PostingSource =
  | "simplify"
  | "vanshb03"
  | "list"
  | "greenhouse"
  | "lever"
  | "ashby"
  | "workday"
  | "pasted";
export type PostingState = "new" | "saved" | "dismissed" | "applied";
export type PostingView = "inbox" | "saved" | "dismissed";
export type WatchAts = "greenhouse" | "lever" | "ashby" | "workday";
/** Inbox order: best score first (the default), or newest first. */
export type PostingSort = "best" | "newest";

/** A discovered posting. Every text field comes from an untrusted source: render as plain text. */
export interface Posting {
  id: number;
  source: PostingSource;
  company: string;
  title: string;
  locations: string[];
  url: string;
  terms: string[];
  category: string | null;
  sponsorship: string | null;
  datePosted: string | null;
  firstSeenAt: string;
  lastSeenAt: string;
  closed: boolean;
  state: PostingState;
  stateChangedAt: string;
  applicationId: number | null;
  watchCompanyId: number | null;
  /** The app's own 0–100 match score and why (short reasons, at most six). */
  localScore: number | null;
  localReasons: string[];
  /** The daily Claude routine's score and one-line note; the note is untrusted text. */
  claudeScore: number | null;
  claudeNote: string | null;
  claudeScoredAt: string | null;
  /** The ranking preferences changed after Claude scored this posting. */
  claudeStale: boolean;
}

export interface PostingPage {
  items: Posting[];
  total: number;
  /** Inbox only: how many Inbox postings are Top picks; null for other views. */
  topPicks: number | null;
}

/** What `POST /paste/preview` read from the page; the user may edit it before confirming. */
export interface PastePreview {
  company: string;
  title: string;
  locations: string[];
  url: string;
  datePosted: string | null;
  source: PostingSource;
}

/** Body of `POST /paste` (the confirmed, possibly edited, fields). */
export interface PasteConfirmInput {
  url: string;
  company: string;
  title: string;
  locations?: string[];
  datePosted?: string | null;
}

export interface WatchCompany {
  id: number;
  name: string;
  ats: WatchAts;
  boardToken: string;
  careersUrl: string;
  addedAt: string;
  lastCheckedAt: string | null;
  lastError: string | null;
  openMatches: number;
}

export interface WatchCompanyInput {
  careersUrl: string;
  name?: string | null;
}

export interface ScanStarted {
  started: boolean;
}

export interface ScanStatus {
  lastScanAt: string | null;
  lastScanError: string | null;
  scanning: boolean;
  inboxCount: number;
}

/** The filter fields, named as on `AppSettings`; the body of the live match count. */
export interface DiscoveryFilters {
  discoveryTerms: string[];
  discoveryCategories: string[];
  discoveryIncludeKeywords: string[];
  discoveryWatchlistKeywords: string[];
  discoveryExcludeKeywords: string[];
  discoveryLocations: string[];
  discoveryHideNoSponsorship: boolean;
}

/** The ranking keyword lists, named as on `AppSettings`; the body of the live Top picks count. */
export interface RankingPrefs {
  rankingRoleKeywords: string[];
  rankingSkillKeywords: string[];
  rankingPreferredLocations: string[];
  rankingPreferredCompanies: string[];
  rankingAvoidCompanies: string[];
  rankingDealbreakerKeywords: string[];
}

/** Every user-editable ranking setting (part of `AppSettings`). */
export interface RankingSettings extends RankingPrefs {
  rankingClaudeDailyLimit: number;
}

/** Every user-editable discovery setting (part of `AppSettings`). */
export interface DiscoverySettings extends DiscoveryFilters {
  discoveryListUrls: string[];
  discoveryScanHours: number;
}
