import type { EmailSuggestion, GmailAccount, HighlightTab, SuggestionKind, SuggestionState } from "../types/email";

/** What the email is, as a short tag on its card. */
export const KIND_LABELS: Record<SuggestionKind, string> = {
  confirmation: "Application received",
  rejection: "Rejection",
  interview: "Interview",
  assessment: "Online assessment",
  offer: "Offer",
  contact_reply: "Contact replied",
  contact_sent: "You emailed a contact",
  new_application: "New application",
};

/** What Accept does for each kind (spec §4 "Suggested actions"). */
export const ACTION_LABELS: Record<SuggestionKind, string> = {
  confirmation: "Mark applied",
  rejection: "Move to Rejected",
  interview: "Add an interview round",
  assessment: "Add a note and a follow-up in 7 days",
  offer: "Move to Offer",
  contact_reply: "Mark replied",
  contact_sent: "Mark sent",
  new_application: "Add to tracker",
};

export const STATE_LABELS: Record<SuggestionState, string> = {
  pending: "Waiting for you",
  accepted: "Accepted",
  dismissed: "Dismissed",
  auto_applied: "Applied automatically",
  stale: "Out of date",
};

/** The Open in Gmail link, only when it really points at Gmail over https; else null. */
export function safeGmailUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "mail.google.com" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** "Name <address>", or just whichever is known. */
export function senderLabel(s: Pick<EmailSuggestion, "fromName" | "fromEmail">): string {
  const name = s.fromName.trim();
  const email = s.fromEmail.trim();
  if (name && email && name.toLowerCase() !== email.toLowerCase()) return `${name} <${email}>`;
  return name || email || "Unknown sender";
}

const APPLICATION_KINDS: ReadonlySet<SuggestionKind> = new Set<SuggestionKind>([
  "confirmation",
  "rejection",
  "interview",
  "assessment",
  "offer",
]);

/** "Dana Lee, MIT", or just the name when the organization is blank. */
export function contactLabel(contact: NonNullable<EmailSuggestion["contact"]>): string {
  const organization = contact.organization.trim();
  return organization ? `${contact.name}, ${organization}` : contact.name;
}

/**
 * What the email was matched to: "Acme — SWE Intern" (with "via Dana Lee"
 * when a contact sent it), a contact, or the company to add.
 * `withApplication: false` leaves the application out (the application's
 * own panel), keeping the contact.
 */
export function matchLabel(s: EmailSuggestion, { withApplication = true } = {}): string | null {
  if (s.kind === "new_application") {
    const company = s.proposedCompany ?? "Unknown company";
    return s.proposedRole ? `${company} — ${s.proposedRole}` : company;
  }
  const application = withApplication && s.application ? `${s.application.company} — ${s.application.roleTitle}` : null;
  if (APPLICATION_KINDS.has(s.kind) && application) {
    return s.contact ? `${application} via ${s.contact.name}` : application;
  }
  if (s.contact) return contactLabel(s.contact);
  return application;
}

/** The sender's name, else the address: the short form for a one-line row. */
export function senderName(s: Pick<EmailSuggestion, "fromName" | "fromEmail">): string {
  return s.fromName.trim() || s.fromEmail.trim() || "Unknown sender";
}

/** "Oct 14": the day an email arrived, in the viewer's time zone; unparseable text is returned as is. */
export function shortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * What a Dashboard row names: the contact ("Dana Lee, MIT") on the Cold
 * emails tab, the application ("Acme — SWE Intern") on the others.
 */
export function highlightMatch(s: EmailSuggestion, tab: HighlightTab): string | null {
  if (tab === "replies" && s.contact) return contactLabel(s.contact);
  if (s.application) return `${s.application.company} — ${s.application.roleTitle}`;
  return matchLabel(s);
}

/** An inbox's address, or what to call one carried over from before it was known. */
export function inboxLabel(account: Pick<GmailAccount, "email">): string {
  return account.email ?? "Gmail inbox, address shown after the next sync";
}
