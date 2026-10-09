import { isSafeHttpUrl } from "../contacts/links";
import type { InterviewKind } from "../types/interview";

/**
 * What the prep prompts are filled from. Deliberately no prep notes,
 * reflections or contact details: only the mock interview gets the titles
 * of the stories planned for the round (spec §5.7).
 */
export interface PromptContext {
  company: string;
  roleTitle: string;
  jobLink: string | null;
  roundName: string;
  kind: InterviewKind;
  durationMinutes: number | null;
  interviewerNames: string[];
  storyTitles: string[];
  outreachProfile: string;
}

export interface PrepPrompt {
  id: "company-research" | "likely-questions" | "mock-interview" | "tell-me-about-yourself" | "thank-you";
  title: string;
  prompt: string;
}

const BACKGROUND_PLACEHOLDER = "[PASTE A SHORT SUMMARY OF YOUR BACKGROUND HERE]";

const KIND_FOCUS: Record<InterviewKind, string> = {
  recruiter_screen: "Include questions about my background, motivation, availability and logistics.",
  technical: "Include the technical topics and problem types I should practise, with one example problem for each.",
  behavioral: "Focus on behavioral questions I can answer with a STAR story.",
  case: "Include the kinds of cases I might get and how to structure an answer to each.",
  onsite: "Mix behavioral, role-specific and motivation questions.",
  final: "Mix behavioral, role-specific and motivation questions, plus questions about fit with the team.",
  other: "Mix behavioral, role-specific and motivation questions.",
};

function jobLine(ctx: PromptContext): string {
  return isSafeHttpUrl(ctx.jobLink) ? `\nJob posting: ${ctx.jobLink.trim()}` : "";
}

function names(list: string[]): string {
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
}

export function companyResearchPrompt(ctx: PromptContext): string {
  return `I have an interview coming up for the ${ctx.roleTitle} role at ${ctx.company}.${jobLine(ctx)}

Help me research the company before the interview. Cover:
- what ${ctx.company} does, its main products and customers, and how it makes money;
- the team or product this role most likely belongs to;
- notable news from the last 12 months;
- its culture and values, as the company describes them;
- how its interview process is publicly described.

Use public sources, cite each one, and say when you're unsure rather than guessing.`;
}

export function likelyQuestionsPrompt(ctx: PromptContext): string {
  const length = ctx.durationMinutes ? ` It is ${ctx.durationMinutes} minutes long.` : "";
  return `I have an interview round coming up ("${ctx.roundName}") for the ${ctx.roleTitle} role at ${ctx.company}.${length}${jobLine(ctx)}

List the 10 questions I'm most likely to be asked in this round, most likely first. For each one, say in a line what the interviewer wants to learn and what a strong answer includes. ${KIND_FOCUS[ctx.kind]}`;
}

export function mockInterviewPrompt(ctx: PromptContext): string {
  const stories = ctx.storyTitles.length
    ? `\n\nStories I plan to tell (ask questions that give me a chance to use them):\n${ctx.storyTitles.map((t) => `- ${t}`).join("\n")}`
    : "";
  return `Run a mock interview with me for the "${ctx.roundName}" round of the ${ctx.roleTitle} role at ${ctx.company}.${jobLine(ctx)}

Ask me one question at a time and wait for my answer. After each answer, give short feedback: what worked, what to tighten, and a stronger version of one sentence. Then ask the next question. After about six questions, sum up my three most important things to improve.${stories}`;
}

export function tellMeAboutYourselfPrompt(ctx: PromptContext): string {
  return `Help me prepare a 60–90 second answer to "Tell me about yourself" for an interview for the ${ctx.roleTitle} role at ${ctx.company}.

My background:
${ctx.outreachProfile.trim() || BACKGROUND_PLACEHOLDER}

Structure it as present, past, future: what I'm doing now, the experience that led here, and why this role at ${ctx.company} is the next step. Keep it conversational and specific, with no cliches. Then give me a 30-second version.`;
}

export function thankYouPrompt(ctx: PromptContext): string {
  const withWhom = ctx.interviewerNames.length ? ` with ${names(ctx.interviewerNames)}` : "";
  return `Help me write a short thank-you email after my "${ctx.roundName}" interview${withWhom} for the ${ctx.roleTitle} role at ${ctx.company}.

What we talked about:
[ONE OR TWO THINGS FROM THE CONVERSATION]

Keep it under 120 words, warm but professional, and specific to the conversation. Don't repeat my whole application. Include a subject line.`;
}

export function buildPrepPrompts(ctx: PromptContext): PrepPrompt[] {
  return [
    { id: "company-research", title: "Company research", prompt: companyResearchPrompt(ctx) },
    { id: "likely-questions", title: "Likely questions for this round", prompt: likelyQuestionsPrompt(ctx) },
    { id: "mock-interview", title: "Mock interview", prompt: mockInterviewPrompt(ctx) },
    { id: "tell-me-about-yourself", title: "Tell me about yourself", prompt: tellMeAboutYourselfPrompt(ctx) },
    { id: "thank-you", title: "Thank-you note", prompt: thankYouPrompt(ctx) },
  ];
}

/** A short thank-you note for Gmail compose; the user edits it there and sends it themselves. */
export function thankYouDraft(opts: { company: string; roleTitle: string; contactName: string }): {
  subject: string;
  body: string;
} {
  const first = opts.contactName.trim().split(/\s+/)[0] || "there";
  return {
    subject: `Thank you — ${opts.roleTitle} interview`,
    body: `Hi ${first},

Thank you for taking the time to speak with me about the ${opts.roleTitle} role at ${opts.company}. I enjoyed our conversation and learning more about the team.

I'm excited about the opportunity and would be glad to share anything else that would help.

Best regards,
`,
  };
}
