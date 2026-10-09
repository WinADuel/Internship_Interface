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
});
