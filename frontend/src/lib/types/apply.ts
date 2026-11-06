/** The apply profile's standard answers, keyed as the API names them. */
export interface ApplyProfileFields {
  first_name: string;
  last_name: string;
  preferred_name: string;
  email: string;
  phone: string;
  city: string;
  state: string;
  country: string;
  linkedin_url: string;
  github_url: string;
  website_url: string;
  current_company: string;
  school: string;
  degree: string;
  major: string;
  gpa: string;
  graduation_month: string;
  graduation_year: string;
  work_authorized: "" | "yes" | "no";
  needs_sponsorship: "" | "yes" | "no";
  willing_to_relocate: "" | "yes" | "no";
  how_heard: string;
  pronouns: string;
  gender: string;
  race: string;
  hispanic_latino: string;
  veteran: string;
  disability: string;
  lgbtq: string;
}

export interface SavedAnswer {
  question: string;
  answer: string;
}

export interface ApplyProfile {
  fields: ApplyProfileFields;
  savedAnswers: SavedAnswer[];
  resumeFilename: string | null;
  resumeUploadedAt: string | null;
  llmUrl: string;
  llmModel: string;
}

export interface ApplyProfileUpdate {
  fields?: ApplyProfileFields;
  savedAnswers?: SavedAnswer[];
  llmUrl?: string;
  llmModel?: string;
}

export type FieldKind = "text" | "textarea" | "select" | "multiselect" | "boolean" | "file";
export type AnswerSource = "" | "profile" | "saved" | "ai" | "you";

export interface FormOption {
  label: string;
  value: string;
}

export interface FormField {
  key: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  options: FormOption[];
  section: "application" | "demographic";
  description: string;
  value: string | string[];
  source: AnswerSource;
}

export interface ApplyDraft {
  postingId: number;
  company: string;
  title: string;
  postingState: string;
  ats: string;
  applyUrl: string;
  fetchedAt: string;
  updatedAt: string;
  fields: FormField[];
  resumeFilename: string | null;
  llmReady: boolean;
}

export interface AnswerUpdate {
  value: string | string[];
  remember?: boolean;
}

export interface DraftAiResult {
  drafted: string[];
  failed: string[];
  error: string | null;
  draft: ApplyDraft;
}

export interface ExtensionTokenInfo {
  id: number;
  tokenPrefix: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
}

export interface ExtensionTokenCreated extends ExtensionTokenInfo {
  token: string;
}
