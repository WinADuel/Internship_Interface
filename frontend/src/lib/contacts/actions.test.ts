import { describe, expect, it } from "vitest";
import { ACTION_LABELS, ACTIONS_BY_STATUS, NUDGE_LABELS, statusLabel } from "./actions";

describe("contact actions", () => {
  it("matches the spec status-button table", () => {
    expect(ACTIONS_BY_STATUS).toEqual({
      to_contact: ["sent"],
      sent: ["followed_up", "replied", "declined"],
      followed_up: ["replied", "declined", "no_response"],
      replied: ["meeting_set", "accepted", "declined"],
      meeting: ["accepted", "declined"],
      accepted: [],
      declined: [],
    });
  });

  it("labels accepted company contacts as positive", () => {
    expect(statusLabel("accepted", "company")).toBe("Positive (referral/interview)");
    expect(statusLabel("accepted", "professor")).toBe("Accepted");
    expect(statusLabel("to_contact", "company")).toBe("To contact");
  });

  it("has labels for every action and nudge", () => {
    expect(ACTION_LABELS.no_response).toBe("No response");
    expect(ACTION_LABELS.meeting_set).toBe("Meeting set");
    expect(NUDGE_LABELS.gone_quiet).toBe("Gone quiet — close it out?");
    expect(Object.keys(NUDGE_LABELS)).toHaveLength(5);
  });
});
