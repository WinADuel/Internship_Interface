// The Chrome extension's fill script (extension/fill.js), run in jsdom
// against the recorded Lever apply page. The live pages were checked by hand
// with extension/test/e2e.mjs; this keeps the logic from regressing.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

type Field = {
  key: string; label: string; kind: string; value: string | string[]; required: boolean; section: string;
  options: Array<{ label: string; value: string }>;
};
type Fill = {
  fillPage: (doc: Document, data: object) => Promise<{ filled: string[]; failed: string[]; needsYou: string[] }>;
  looksSubmitted: (doc: Document, url: string) => boolean;
};

const ROOT = resolve(__dirname, "../../../..");
const LEVER_PAGE = readFileSync(resolve(ROOT, "backend/tests/fixtures/apply/lever_apply_page.html"), "utf8");
const AUTH = "cards[1c719ca9-5069-4afe-9e82-39ca420e0edb][field0]";
const SPONSOR = "cards[1c719ca9-5069-4afe-9e82-39ca420e0edb][field1]";
const LANGS = "cards[a69a985a-eae9-4c14-90fb-b5a4b891523e][field0]";
const WHY = "cards[ce72d538-c9ad-41f3-8e9a-618d40c82e3a][field1]";

let fill: Fill;

beforeAll(async () => {
  // fill.js is a plain browser script: it puts its functions on window.
  const path = resolve(ROOT, "extension/fill.js");
  new Function(readFileSync(path, "utf8")).call(window);
  fill = (window as unknown as { InternHelperFill: Fill }).InternHelperFill;
});

beforeEach(() => {
  document.body.innerHTML = LEVER_PAGE.replace(/^[\s\S]*?<body>|<\/body>[\s\S]*$/g, "");
});

function f(key: string, label: string, kind: string, value: string | string[], required = false): Field {
  return { key, label, kind, value, required, section: "application", options: [] };
}

function named(name: string): HTMLInputElement {
  return document.getElementsByName(name)[0] as HTMLInputElement;
}

const RESUME = { filename: "Resume.pdf", content_type: "application/pdf", data_base64: btoa("%PDF-1.4") };

describe("extension fill script", () => {
  it("fills text, radios, checkboxes, textareas and the resume on a Lever form", async () => {
    const report = await fill.fillPage(document, {
      fields: [
        f("name", "Full name", "text", "Dana Lee", true),
        f("email", "Email", "text", "dana@example.com", true),
        f("urls[LinkedIn]", "LinkedIn URL", "text", "https://linkedin.com/in/dana"),
        f(AUTH, "Are you legally authorized to work in the country for which you are applying?", "select", "Yes", true),
        f(SPONSOR, "Will you now or in the future require sponsorship?", "select", "No", true),
        f(LANGS, "Language Skill(s)", "multiselect", ["English (ENG)", "Mandarin (MAN)"], true),
        f(WHY, "Why do you want to work at Palantir?", "textarea", "I like hard problems."),
        f("resume", "Resume/CV", "file", "Resume.pdf"),
        f("phone", "Phone", "text", ""),
        f("location", "Current location", "text", "", true),
      ],
      profile: {},
      resume: RESUME,
    });
    expect(named("name").value).toBe("Dana Lee");
    expect(named("email").value).toBe("dana@example.com");
    expect(named("urls[LinkedIn]").value).toBe("https://linkedin.com/in/dana");
    const checked = (name: string) =>
      (Array.from(document.getElementsByName(name)) as HTMLInputElement[]).filter((i) => i.checked).map((i) => i.value);
    expect(checked(AUTH)).toEqual(["Yes"]);
    expect(checked(SPONSOR)).toEqual(["No"]);
    expect(checked(LANGS)).toEqual(["English (ENG)", "Mandarin (MAN)"]);
    expect((document.getElementsByName(WHY)[0] as HTMLTextAreaElement).value).toBe("I like hard problems.");
    expect(report.needsYou).toEqual(["Current location"]);
    // jsdom has no DataTransfer, so the resume is reported as not attached rather than claimed.
    expect(report.failed).toEqual(["Resume/CV"]);
  });

  it("never touches a submit button", async () => {
    let submitted = false;
    document.querySelectorAll("form").forEach((form) => form.addEventListener("submit", () => (submitted = true)));
    document.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => (submitted = true)));
    await fill.fillPage(document, { fields: [f("name", "Full name", "text", "Dana Lee")], profile: {}, resume: null });
    expect(submitted).toBe(false);
  });

  it("falls back to the label when the board renamed a field", async () => {
    document.body.innerHTML = `<label for="x1">LinkedIn Profile</label><input id="x1" type="text">
      <label>Gender <select id="g"><option value="">Select</option><option value="m">Male</option><option value="f">Female</option></select></label>`;
    const report = await fill.fillPage(document, {
      fields: [f("old_key", "LinkedIn Profile", "text", "https://linkedin.com/in/dana"), f("gone", "Gender", "select", "Female")],
      profile: {},
      resume: null,
    });
    expect((document.getElementById("x1") as HTMLInputElement).value).toBe("https://linkedin.com/in/dana");
    expect((document.getElementById("g") as HTMLSelectElement).value).toBe("f");
    expect(report.filled).toHaveLength(2);
  });

  it("fills just the profile when the job isn't saved in InternHelper", async () => {
    const report = await fill.fillPage(document, {
      fields: [],
      profile: { first_name: "Dana", last_name: "Lee", email: "dana@example.com", github_url: "https://github.com/dana" },
      resume: null,
    });
    expect(named("name").value).toBe("Dana Lee");
    expect(named("urls[GitHub]").value).toBe("https://github.com/dana");
    expect(report.filled).toHaveLength(3);
  });

  it("recognizes the boards' thank-you pages", () => {
    document.body.innerHTML = "<h2>Thank you for applying.</h2>";
    expect(fill.looksSubmitted(document, "https://job-boards.greenhouse.io/acme/jobs/1")).toBe(true);
    document.body.innerHTML = "<p>Apply for this job</p>";
    expect(fill.looksSubmitted(document, "https://jobs.lever.co/acme/x/thanks")).toBe(true);
    expect(fill.looksSubmitted(document, "https://jobs.lever.co/acme/x/apply")).toBe(false);
  });
});
