import { apiFetch } from "./client";
import { keysToCamel, keysToSnake } from "./case";
import type { Story, StoryInput, StoryUpdate } from "../types/interview";

type Raw = Record<string, unknown>;

const JSON_HEADERS = { "Content-Type": "application/json" };

export function mapStoryFromApi(raw: Raw): Story {
  const story = keysToCamel<Story>(raw);
  return { ...story, tags: Array.isArray(raw.tags) ? raw.tags.map(String) : [], archived: raw.archived === true };
}

export async function listStories(opts: { tag?: string; includeArchived?: boolean } = {}): Promise<Story[]> {
  const params = new URLSearchParams();
  if (opts.tag) params.set("tag", opts.tag);
  if (opts.includeArchived) params.set("include_archived", "true");
  const query = params.toString();
  const raw = await apiFetch<Raw[]>(`/api/stories${query ? `?${query}` : ""}`);
  return raw.map(mapStoryFromApi);
}

export async function createStory(data: StoryInput): Promise<Story> {
  const raw = await apiFetch<Raw>("/api/stories", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(keysToSnake(data)),
  });
  return mapStoryFromApi(raw);
}

/** PATCH; only the keys present on `data` are sent. `{ archived: true }` hides a story from the bank. */
export async function updateStory(id: number, data: StoryUpdate): Promise<Story> {
  const raw = await apiFetch<Raw>(`/api/stories/${id}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(keysToSnake(data)),
  });
  return mapStoryFromApi(raw);
}

export async function deleteStory(id: number): Promise<void> {
  await apiFetch<void>(`/api/stories/${id}`, { method: "DELETE" });
}
