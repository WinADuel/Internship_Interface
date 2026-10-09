import type { EmailSuggestion, SuggestionKind, SuggestionState } from "../types/email";

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

/** What the email was matched to: "Acme — SWE Intern", a contact, or the company to add. */
export function matchLabel(s: EmailSuggestion): string | null {
  if (s.kind === "new_application") {
    const company = s.proposedCompany ?? "Unknown company";
    return s.proposedRole ? `${company} — ${s.proposedRole}` : company;
  }
  if (s.contact) return `${s.contact.name}, ${s.contact.organization}`;
  if (s.application) return `${s.application.company} — ${s.application.roleTitle}`;
  return null;
}
