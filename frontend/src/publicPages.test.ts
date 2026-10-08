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

  it("names both Google permissions and how to revoke them", () => {
    expect(html).toContain("drive.readonly");
    expect(html).toContain("drive.file");
    expect(html).toContain("https://myaccount.google.com/permissions");
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
