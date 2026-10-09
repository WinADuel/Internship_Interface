// @vitest-environment node
/// <reference types="node" />
// Static checks on the public pages Caddy serves outside the app (Phase 3 spec §4.5).
// They load no scripts and carry no inline styles, so the site-wide CSP needs no exceptions.
import { readFileSync } from "node:fs";

const publicDir = new URL("../public/", import.meta.url);
const read = (name: string) => readFileSync(new URL(name, publicDir), "utf8");

describe.each(["about.html", "privacy.html"])("public page %s", (name) => {
  const html = read(name);

  it("loads no scripts", () => {
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  it("has no inline styles", () => {
    expect(html).not.toMatch(/<style/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
  });

  it("uses the shared stylesheet", () => {
    expect(html).toContain('<link rel="stylesheet" href="/static.css">');
  });

  it("links to the other public page and to the app", () => {
    const other = name === "about.html" ? "/privacy.html" : "/about.html";
    expect(html).toContain(`href="${other}"`);
    expect(html).toContain('href="/"');
  });

  it("fills the contact email from CONTACT_EMAIL, escaped, with a fallback", () => {
    expect(html).toContain('{{with env "CONTACT_EMAIL"}}');
    expect(html).toContain("{{. | html}}");
    expect(html).toContain("{{else}}the site owner{{end}}");
  });
});

describe("privacy page", () => {
  const html = read("privacy.html");

  it("names every Google permission and how to revoke them", () => {
    expect(html).toContain("drive.readonly");
    expect(html).toContain("drive.file");
    expect(html).toContain("gmail.readonly");
    expect(html).toContain("https://myaccount.google.com/permissions");
  });

  it("says what Gmail sync reads and keeps, that it is optional, and how to turn it off", () => {
    expect(html).toContain("optional, off by default");
    expect(html).toMatch(/What is read:[\s\S]*preview text Gmail itself provides/);
    expect(html).toContain("Message bodies and attachments are never");
    expect(html).toMatch(/What is kept:[\s\S]*match a tracked application or\s+contact/);
    // Not only tracked mail: new-company detection keeps details too, and says so.
    expect(html).toMatch(/What is kept:[\s\S]*company the owner doesn't track yet/);
    expect(html).not.toContain("only for an email that matches a tracked application or");
    expect(html).toMatch(/What it is used for:[\s\S]*marking a contact as emailed[\s\S]*adding a company not yet tracked/);
    expect(html).toContain("Mail that matches nothing is not stored");
    expect(html).toMatch(/How to turn it off:[\s\S]*Sync Gmail/);
    expect(html).toContain("no email data is ever given to it");
  });

  it("says what cookies and browser storage are for", () => {
    expect(html).toContain("Cookies are used only to keep you signed in");
    expect(html).toContain("dashboard layout is saved in your own browser");
    expect(html).not.toContain("The only cookie is the login session");
  });

  it("says the owner's Claude assistant uses a revocable token and never reads Google data", () => {
    expect(html).toMatch(/Claude assistant[\s\S]*token the owner can revoke[\s\S]*never reads Google data/);
  });

  it("has a last-updated date", () => {
    expect(html).toMatch(/Last updated: \d{4}-\d{2}-\d{2}/);
  });
});

describe("static.css", () => {
  it("exists", () => {
    expect(read("static.css")).toContain("body");
  });
});
