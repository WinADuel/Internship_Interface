import { describe, expect, it } from "vitest";
import { fitsInGmailUrl, gmailComposeUrl } from "./gmail";

describe("gmail compose url", () => {
  it("encodes every parameter", () => {
    const url = gmailComposeUrl("a@b.edu", "Hi & hello", "Line1\nLine2");
    expect(url.startsWith("https://mail.google.com/mail/?view=cm")).toBe(true);
    expect(url).toContain("to=a%40b.edu");
    expect(url).toContain("su=Hi%20%26%20hello");
    expect(url).toContain("body=Line1%0ALine2");
  });

  it("cannot be used to smuggle extra parameters", () => {
    const url = gmailComposeUrl("a@b.edu&bcc=x@evil.com", "s", "b");
    expect(url).not.toContain("&bcc=");
  });

  it("rejects bodies too long for a URL", () => {
    expect(fitsInGmailUrl(gmailComposeUrl("a@b.edu", "s", "x".repeat(3000)))).toBe(false);
    expect(fitsInGmailUrl(gmailComposeUrl("a@b.edu", "s", "short"))).toBe(true);
  });
});
