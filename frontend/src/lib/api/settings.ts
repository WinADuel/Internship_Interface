import { apiFetch } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import type {
  AppSettings,
  AppSettingsUpdate,
  ClaudeTokenCreated,
  ClaudeTokenInfo,
  SheetSyncResult,
} from "../types/contact";

type Raw = Record<string, unknown>;

export async function getSettings(): Promise<AppSettings> {
  return keysToCamel<AppSettings>(await apiFetch<Raw>("/api/settings"));
}

export async function updateSettings(data: AppSettingsUpdate): Promise<AppSettings> {
  const raw = await apiFetch<Raw>("/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(keysToSnake(data)),
  });
  return keysToCamel<AppSettings>(raw);
}

export async function listClaudeTokens(): Promise<ClaudeTokenInfo[]> {
  const raw = await apiFetch<Raw[]>("/api/settings/claude-tokens");
  return raw.map((r) => keysToCamel<ClaudeTokenInfo>(r));
}

export async function createClaudeToken(): Promise<ClaudeTokenCreated> {
  return keysToCamel<ClaudeTokenCreated>(await apiFetch<Raw>("/api/settings/claude-tokens", { method: "POST" }));
}

export async function revokeClaudeToken(id: number): Promise<ClaudeTokenInfo> {
  const raw = await apiFetch<Raw>(`/api/settings/claude-tokens/${id}/revoke`, { method: "POST" });
  return keysToCamel<ClaudeTokenInfo>(raw);
}

export async function syncSheetNow(): Promise<SheetSyncResult> {
  return keysToCamel<SheetSyncResult>(await apiFetch<Raw>("/api/settings/sheet-sync", { method: "POST" }));
}
