import { describe, expect, it } from "vitest";
import { gmailComposeUrl } from "../contacts/gmail";
import { buildPrepPrompts, thankYouDraft, type PromptContext } from "./prompts";

const ctx: PromptContext = {
  company: "Globex",
  roleTitle: "Data Intern",
  jobLink: "https://globex.example.com/jobs/1",
  roundName: "Coding round 2",
  kind: "technical",
  durationMinutes: 45,
  interviewerNames: ["Ana Lee", "Bo Chen", "Cy"],
  storyTitles: ["Outage at 2am", "Team conflict"],
  outreachProfile: "CS junior at State U; built a search engine.",
};

const byId = (c: PromptContext) => Object.fromEntries(buildPrepPrompts(c).map((p) => [p.id, p]));

describe("prep prompts", () => {
  it("offers the five prompts in order", () => {
    expect(buildPrepPrompts(ctx).map((p) => p.title)).toEqual([
      "Company research",
      "Likely questions for this round",
      "Mock interview",
      "Tell me about yourself",
      "Thank-you note",
    ]);
  });

  it("fills the company research prompt", () => {
    expect(byId(ctx)["company-research"].prompt).toBe(`I have an interview coming up for the Data Intern role at Globex.
Job posting: https://globex.example.com/jobs/1

Help me research the company before the interview. Cover:
- what Globex does, its main products and customers, and how it makes money;
- the team or product this role most likely belongs to;
- notable news from the last 12 months;
- its culture and values, as the company describes them;
- how its interview process is publicly described.

Use public sources, cite each one, and say when you're unsure rather than guessing.`);
  });

  it("fills the likely questions prompt with the round and a focus for its kind", () => {
    expect(byId(ctx)["likely-questions"].prompt).toBe(`I have an interview round coming up ("Coding round 2") for the Data Intern role at Globex. It is 45 minutes long.
Job posting: https://globex.example.com/jobs/1

List the 10 questions I'm most likely to be asked in this round, most likely first. For each one, say in a line what the interviewer wants to learn and what a strong answer includes. Include the technical topics and problem types I should practise, with one example problem for each.`);
    const behavioral = byId({ ...ctx, kind: "behavioral", durationMinutes: null, jobLink: null })["likely-questions"].prompt;
    expect(behavioral).toContain('("Coding round 2") for the Data Intern role at Globex.\n\nList');
    expect(behavioral).toMatch(/STAR story\.$/);
  });

  it("fills the mock interview prompt with the planned story titles only", () => {
    expect(byId(ctx)["mock-interview"].prompt).toBe(`Run a mock interview with me for the "Coding round 2" round of the Data Intern role at Globex.
Job posting: https://globex.example.com/jobs/1

Ask me one question at a time and wait for my answer. After each answer, give short feedback: what worked, what to tighten, and a stronger version of one sentence. Then ask the next question. After about six questions, sum up my three most important things to improve.

Stories I plan to tell (ask questions that give me a chance to use them):
- Outage at 2am
- Team conflict`);
    expect(byId({ ...ctx, storyTitles: [] })["mock-interview"].prompt).not.toContain("Stories");
  });

  it("uses the outreach profile for Tell me about yourself, or a placeholder", () => {
    expect(byId(ctx)["tell-me-about-yourself"].prompt).toBe(`Help me prepare a 60–90 second answer to "Tell me about yourself" for an interview for the Data Intern role at Globex.

My background:
CS junior at State U; built a search engine.

Structure it as present, past, future: what I'm doing now, the experience that led here, and why this role at Globex is the next step. Keep it conversational and specific, with no cliches. Then give me a 30-second version.`);
    expect(byId({ ...ctx, outreachProfile: "  " })["tell-me-about-yourself"].prompt).toContain(
      "My background:\n[PASTE A SHORT SUMMARY OF YOUR BACKGROUND HERE]\n",
    );
  });

  it("fills the thank-you prompt with the interviewers' names", () => {
    expect(byId(ctx)["thank-you"].prompt).toBe(`Help me write a short thank-you email after my "Coding round 2" interview with Ana Lee, Bo Chen and Cy for the Data Intern role at Globex.

What we talked about:
[ONE OR TWO THINGS FROM THE CONVERSATION]

Keep it under 120 words, warm but professional, and specific to the conversation. Don't repeat my whole application. Include a subject line.`);
    expect(byId({ ...ctx, interviewerNames: ["Ana Lee"] })["thank-you"].prompt).toContain("interview with Ana Lee for");
    expect(byId({ ...ctx, interviewerNames: [] })["thank-you"].prompt).toContain('"Coding round 2" interview for');
  });

  it("never includes a non-http job link", () => {
    for (const p of buildPrepPrompts({ ...ctx, jobLink: "javascript:alert(1)" })) {
      expect(p.prompt).not.toContain("javascript:");
    }
  });
});

describe("thank-you draft", () => {
  it("drafts a short note addressed by first name", () => {
    const draft = thankYouDraft({ company: "Globex", roleTitle: "Data Intern", contactName: "Ana Lee" });
    expect(draft.subject).toBe("Thank you — Data Intern interview");
    expect(draft.body).toBe(`Hi Ana,

Thank you for taking the time to speak with me about the Data Intern role at Globex. I enjoyed our conversation and learning more about the team.

I'm excited about the opportunity and would be glad to share anything else that would help.

Best regards,
`);
    expect(thankYouDraft({ company: "G", roleTitle: "R", contactName: " " }).body.startsWith("Hi there,")).toBe(true);
  });

  it("builds the Gmail compose URL with the shared helper", () => {
    const draft = thankYouDraft({ company: "Globex", roleTitle: "Data Intern", contactName: "Ana Lee" });
    const url = gmailComposeUrl("ana@globex.com", draft.subject, draft.body);
    expect(url).toBe(
      "https://mail.google.com/mail/?view=cm&fs=1&to=ana%40globex.com" +
        `&su=${encodeURIComponent("Thank you — Data Intern interview")}&body=${encodeURIComponent(draft.body)}`,
    );
  });
});
