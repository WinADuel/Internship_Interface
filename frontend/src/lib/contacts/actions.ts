import type { ContactAction, ContactKind, ContactStatus, NudgeKind } from "../types/contact";

/** The status-button table (spec §13.3); same as the backend's ACTIONS_BY_STATUS. */
export const ACTIONS_BY_STATUS: Record<ContactStatus, ContactAction[]> = {
  to_contact: ["sent"],
  sent: ["followed_up", "replied", "declined"],
  followed_up: ["replied", "declined", "no_response"],
  replied: ["meeting_set", "accepted", "declined"],
  meeting: ["accepted", "declined"],
  accepted: [],
  declined: [],
};

export const STATUS_ORDER: ContactStatus[] = [
  "to_contact",
  "sent",
  "followed_up",
  "replied",
  "meeting",
  "accepted",
  "declined",
];

export const ACTION_LABELS: Record<ContactAction, string> = {
  sent: "Sent",
  followed_up: "Followed up",
  replied: "Replied",
  meeting_set: "Meeting set",
  accepted: "Accepted",
  declined: "Declined",
  no_response: "No response",
};

const STATUS_LABELS: Record<ContactStatus, string> = {
  to_contact: "To contact",
  sent: "Sent",
  followed_up: "Followed up",
  replied: "Replied",
  meeting: "Meeting",
  accepted: "Accepted",
  declined: "Declined",
};

export function statusLabel(status: ContactStatus, kind: ContactKind): string {
  if (status === "accepted" && kind === "company") return "Positive (referral/interview)";
  return STATUS_LABELS[status];
}

export const NUDGE_LABELS: Record<NudgeKind, string> = {
  unsent: "Did you send this?",
  followup_due: "Follow-up due",
  gone_quiet: "Gone quiet — close it out?",
  replied_stale: "Any update?",
  meeting_outcome: "How did it go?",
};
