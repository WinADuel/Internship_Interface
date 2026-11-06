import { apiFetch, jsonInit } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import type {
  AnswerUpdate,
  ApplyDraft,
  ApplyProfile,
  ApplyProfileUpdate,
  DraftAiResult,
  ExtensionTokenCreated,
  ExtensionTokenInfo,
} from "../types/apply";

type Raw = Record<string, unknown>;

// `fields` (profile) and each form field's own keys stay as the API sends them:
// they're field names, not properties to rename.
function profileFrom(raw: Raw): ApplyProfile {
  return keysToCamel<ApplyProfile>(raw);
}

function draftFrom(raw: Raw): ApplyDraft {
  return keysToCamel<ApplyDraft>(raw);
}

export async function getApplyProfile(): Promise<ApplyProfile> {
  return profileFrom(await apiFetch<Raw>("/api/apply/profile"));
}

export async function updateApplyProfile(data: ApplyProfileUpdate): Promise<ApplyProfile> {
  return profileFrom(await apiFetch<Raw>("/api/apply/profile", jsonInit("PATCH", keysToSnake(data))));
}

export async function uploadResume(file: File): Promise<ApplyProfile> {
  const raw = await apiFetch<Raw>(`/api/apply/profile/resume?filename=${encodeURIComponent(file.name)}`, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  return profileFrom(raw);
}

export async function deleteResume(): Promise<ApplyProfile> {
  return profileFrom(await apiFetch<Raw>("/api/apply/profile/resume", { method: "DELETE" }));
}

export async function getApplication(postingId: number, refresh = false): Promise<ApplyDraft> {
  return draftFrom(await apiFetch<Raw>(`/api/apply/postings/${postingId}${refresh ? "?refresh=true" : ""}`));
}

export async function saveAnswers(postingId: number, answers: Record<string, AnswerUpdate>): Promise<ApplyDraft> {
  return draftFrom(await apiFetch<Raw>(`/api/apply/postings/${postingId}/answers`, jsonInit("PUT", { answers })));
}

export async function draftWithAi(postingId: number, keys?: string[]): Promise<DraftAiResult> {
  const raw = await apiFetch<Raw>(`/api/apply/postings/${postingId}/draft-ai`, jsonInit("POST", keys ? { keys } : {}));
  const result = keysToCamel<DraftAiResult>(raw);
  return { ...result, draft: draftFrom(raw.draft as Raw) };
}

export async function listExtensionTokens(): Promise<ExtensionTokenInfo[]> {
  return (await apiFetch<Raw[]>("/api/apply/extension-tokens")).map((r) => keysToCamel<ExtensionTokenInfo>(r));
}

export async function createExtensionToken(): Promise<ExtensionTokenCreated> {
  return keysToCamel<ExtensionTokenCreated>(await apiFetch<Raw>("/api/apply/extension-tokens", { method: "POST" }));
}

export async function revokeExtensionToken(id: number): Promise<ExtensionTokenInfo> {
  return keysToCamel<ExtensionTokenInfo>(await apiFetch<Raw>(`/api/apply/extension-tokens/${id}/revoke`, { method: "POST" }));
}
