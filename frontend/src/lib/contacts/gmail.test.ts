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

  it("cannot be used to smuggle extra parameters or recipients", () => {
    expect(gmailComposeUrl("a@b.edu&bcc=x@evil.com", "s", "b")).not.toContain("bcc");
    for (const bad of ["a@b.edu,x@evil.com", "a@b.edu; x@evil.com", "Jane <a@b.edu>", "a@b.edu x@evil.com"]) {
      expect(gmailComposeUrl(bad, "s", "b")).toContain("to=&");
    }
    expect(gmailComposeUrl("", "s", "b")).toContain("to=&");
    expect(gmailComposeUrl("first.last+tag@cs.uni.edu", "s", "b")).toContain("to=first.last%2Btag%40cs.uni.edu");
  });

  it("rejects bodies too long for a URL", () => {
    expect(fitsInGmailUrl(gmailComposeUrl("a@b.edu", "s", "x".repeat(3000)))).toBe(false);
    expect(fitsInGmailUrl(gmailComposeUrl("a@b.edu", "s", "short"))).toBe(true);
  });
});
