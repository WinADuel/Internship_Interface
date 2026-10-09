import type { Application } from "../types/application";
import type { Contact } from "../types/contact";
import type { Posting, ScanStatus, WatchCompany } from "../types/discovery";
import type {
  InterviewRound,
  InterviewRoundDetail,
  InterviewRoundListItem,
  PrepBrief,
  Story,
} from "../types/interview";

export function fakeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    company: "Acme",
    roleTitle: "SWE Intern",
    dateApplied: null,
    status: "wishlist",
    jobLink: null,
    notes: null,
    resumeVersion: null,
    contactPerson: null,
    salaryRange: null,
    location: null,
    source: null,
    priority: "medium",
    followUpDate: null,
    interviewDatetime: null,
    googleDocLink: null,
    archived: false,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function fakeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: 1,
    kind: "professor",
    name: "Jane Lee",
    organization: "Stanford",
    department: null,
    title: null,
    labName: null,
    email: null,
    emailConfidence: "not_found",
    websiteUrl: null,
    profileUrl: null,
    applicationId: null,
    relevanceNote: null,
    researchSummary: null,
    recentWork: null,
    sources: [],
    draftSubject: null,
    draftBody: null,
    draftEdited: false,
    followupSubject: null,
    followupBody: null,
    followupEdited: false,
    draftReadyAt: null,
    status: "to_contact",
    closedReason: null,
    priority: "medium",
    sentAt: null,
    followedUpAt: null,
    repliedAt: null,
    meetingAt: null,
    nudgeSnoozedUntil: null,
    notes: null,
    origin: "manual",
    archived: false,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    nudge: null,
    ...overrides,
  };
}

export function fakePosting(overrides: Partial<Posting> = {}): Posting {
  return {
    id: 1,
    source: "simplify",
    company: "Stripe",
    title: "SWE Intern",
    locations: ["NYC", "Remote"],
    url: "https://stripe.com/jobs/1",
    terms: ["Summer 2027"],
    category: "Software",
    sponsorship: null,
    datePosted: "2026-10-01T00:00:00Z",
    firstSeenAt: "2026-10-02T00:00:00Z",
    lastSeenAt: "2026-10-03T00:00:00Z",
    closed: false,
    state: "new",
    stateChangedAt: "2026-10-02T00:00:00Z",
    applicationId: null,
    watchCompanyId: null,
    claudeScore: null,
    claudeNote: null,
    ...overrides,
  };
}

export function fakeWatchCompany(overrides: Partial<WatchCompany> = {}): WatchCompany {
  return {
    id: 4,
    name: "Stripe",
    ats: "greenhouse",
    boardToken: "stripe",
    careersUrl: "https://boards.greenhouse.io/stripe",
    addedAt: "2026-10-01T00:00:00Z",
    lastCheckedAt: null,
    lastError: null,
    openMatches: 0,
    ...overrides,
  };
}

export function fakeScanStatus(overrides: Partial<ScanStatus> = {}): ScanStatus {
  return { lastScanAt: null, lastScanError: null, scanning: false, inboxCount: 0, ...overrides };
}

export function fakeRound(overrides: Partial<InterviewRound> = {}): InterviewRound {
  return {
    id: 1,
    applicationId: 1,
    kind: "technical",
    title: null,
    scheduledAt: null,
    durationMinutes: null,
    format: null,
    location: null,
    interviewers: null,
    state: "scheduled",
    outcome: null,
    prepNotes: null,
    questionsToAsk: null,
    reflection: null,
    checklist: [],
    thankYouSentAt: null,
    createdAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

export function fakeRoundListItem(overrides: Partial<InterviewRoundListItem> = {}): InterviewRoundListItem {
  return {
    ...fakeRound(),
    company: "Acme",
    roleTitle: "SWE Intern",
    checklistDone: 0,
    checklistTotal: 0,
    thankYouDue: false,
    ...overrides,
  };
}

export function fakeRoundDetail(overrides: Partial<InterviewRoundDetail> = {}): InterviewRoundDetail {
  return { ...fakeRoundListItem(), contacts: [], stories: [], ...overrides };
}

export function fakeStory(overrides: Partial<Story> = {}): Story {
  return {
    id: 1,
    title: "Shipped the search rewrite",
    situation: null,
    task: null,
    action: null,
    result: null,
    tags: [],
    archived: false,
    createdAt: "2026-10-01T00:00:00Z",
    updatedAt: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

export function fakeBrief(overrides: Partial<PrepBrief> = {}): PrepBrief {
  return {
    body: "Acme builds rockets.",
    sources: [],
    createdAt: "2026-10-05T00:00:00Z",
    updatedAt: "2026-10-05T00:00:00Z",
    ...overrides,
  };
}
