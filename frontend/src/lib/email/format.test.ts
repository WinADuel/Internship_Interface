import { describe, expect, it } from "vitest";
import { fakeSuggestion } from "../testing/fixtures";
import { matchLabel, safeGmailUrl, senderLabel } from "./format";

describe("safeGmailUrl", () => {
  it("keeps https Gmail links", () => {
    expect(safeGmailUrl("https://mail.google.com/mail/u/0/#all/abc123")).toBe(
      "https://mail.google.com/mail/u/0/#all/abc123",
    );
  });

  it.each([
    "http://mail.google.com/mail/u/0/#all/abc",
    "https://mail.google.com.evil.example/x",
    "https://evil.example/?https://mail.google.com/",
    "javascript:alert(1)",
    "",
    "not a url",
  ])("refuses %s", (url) => {
    expect(safeGmailUrl(url)).toBeNull();
  });
});

describe("senderLabel", () => {
  it("shows name and address, or whichever is known", () => {
    expect(senderLabel({ fromName: "Acme Recruiting", fromEmail: "jobs@acme.com" })).toBe(
      "Acme Recruiting <jobs@acme.com>",
    );
    expect(senderLabel({ fromName: "", fromEmail: "jobs@acme.com" })).toBe("jobs@acme.com");
    expect(senderLabel({ fromName: "jobs@acme.com", fromEmail: "jobs@acme.com" })).toBe("jobs@acme.com");
    expect(senderLabel({ fromName: " ", fromEmail: "" })).toBe("Unknown sender");
  });
});

describe("matchLabel", () => {
  it("names the application, the contact, or the company to add", () => {
    expect(matchLabel(fakeSuggestion())).toBe("Acme — SWE Intern");
    expect(
      matchLabel(
        fakeSuggestion({
          kind: "contact_reply",
          contact: { id: 4, name: "Dana Lee", organization: "MIT", status: "sent" },
        }),
      ),
    ).toBe("Dana Lee, MIT");
    expect(
      matchLabel(
        fakeSuggestion({ kind: "new_application", application: null, applicationId: null, proposedCompany: "Rivian", proposedRole: "Software Intern" }),
      ),
    ).toBe("Rivian — Software Intern");
    expect(matchLabel(fakeSuggestion({ application: null, applicationId: null }))).toBeNull();
  });

  it("names the application first and the contact after it for an application update", () => {
    const contact = { id: 4, name: "Dana Lee", organization: "Acme", status: "sent" as const };
    expect(matchLabel(fakeSuggestion({ kind: "rejection", contact, contactId: 4 }))).toBe("Acme — SWE Intern via Dana Lee");
    // Without the application, the contact.
    expect(matchLabel(fakeSuggestion({ kind: "interview", contact, contactId: 4, application: null }))).toBe(
      "Dana Lee, Acme",
    );
    expect(matchLabel(fakeSuggestion({ kind: "offer", contact, contactId: 4 }), { withApplication: false })).toBe(
      "Dana Lee, Acme",
    );
    expect(matchLabel(fakeSuggestion({ kind: "offer" }), { withApplication: false })).toBeNull();
    // A contact's own reply names the contact even when it has an application.
    expect(matchLabel(fakeSuggestion({ kind: "contact_reply", contact, contactId: 4 }))).toBe("Dana Lee, Acme");
  });

  it("leaves out a blank organization instead of a dangling comma", () => {
    const contact = { id: 4, name: "Dana Lee", organization: " ", status: "sent" as const };
    expect(matchLabel(fakeSuggestion({ kind: "contact_reply", contact, contactId: 4 }))).toBe("Dana Lee");
    expect(matchLabel(fakeSuggestion({ kind: "contact_sent", contact: { ...contact, organization: "" } }))).toBe("Dana Lee");
  });
});
