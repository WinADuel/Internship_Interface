export interface PromptTemplate {
  id: string;
  title: string;
  prompt: string;
}

export const promptTemplates: PromptTemplate[] = [
  {
    id: "draft-essay",
    title: "Draft an essay from a prompt and my background",
    prompt: `I'm applying for an internship and need a first draft of an essay.

Essay prompt:
[PASTE THE ESSAY PROMPT HERE]

Role and company:
[COMPANY, ROLE, AND A FEW LINES FROM THE JOB DESCRIPTION]

My background (experience, projects, skills, what motivates me):
[PASTE YOUR BACKGROUND HERE]

Write a first draft in my voice. Keep it succinct, specific, and authentic. Use concrete examples from my background rather than generic claims, avoid cliches, and stay within [WORD LIMIT] words.`,
  },
  {
    id: "review-essay",
    title: "Review this essay for succinct, authentic writing",
    prompt: `Please review my essay for succinct, authentic writing.

Essay prompt:
[PASTE THE ESSAY PROMPT HERE]

My essay:
[PASTE YOUR ESSAY HERE]

Point out anything wordy, vague, generic, or cliched, and anything that doesn't sound like a real person. Suggest specific tighter rewrites that keep my voice, and tell me whether it answers the prompt directly. Don't invent experiences I haven't mentioned.`,
  },
];
