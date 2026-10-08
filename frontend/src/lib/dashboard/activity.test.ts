import { describe, expect, it } from "vitest";
import { mergeActivity } from "./activity";
import type { ActivityEntry } from "../types/application";
import type { ContactActivityEntry } from "../types/contact";

const app = (company: string, changedAt: string): ActivityEntry => ({
  applicationId: 1, company, roleTitle: "SWE", oldStatus: "wishlist", newStatus: "applied", changedAt,
});
const contact = (name: string, changedAt: string): ContactActivityEntry => ({
  contactId: 1, name, organization: "MIT", kind: "professor", oldStatus: "to_contact", newStatus: "sent", changedAt,
});

describe("mergeActivity", () => {
  it("interleaves both sources newest first and respects limit", () => {
    const merged = mergeActivity(
      [app("Acme", "2026-10-01T10:00:00Z"), app("Globex", "2026-10-03T10:00:00Z")],
      [contact("Jane", "2026-10-02T10:00:00Z"), contact("Bob", "2026-10-04T10:00:00Z")],
      3,
    );
    expect(merged.map((m) => m.label)).toEqual(["Bob (MIT)", "Globex — SWE", "Jane (MIT)"]);
    expect(merged.map((m) => m.kind)).toEqual(["contact", "application", "contact"]);
  });

  it("handles empty sources", () => {
    expect(mergeActivity([], [], 5)).toEqual([]);
    expect(mergeActivity([app("Acme", "2026-10-01T10:00:00Z")], [], 5)).toHaveLength(1);
  });
});
