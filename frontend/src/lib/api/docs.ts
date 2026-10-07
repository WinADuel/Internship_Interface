import { apiFetch } from "./client";

export async function getDocContent(docRef: string): Promise<string> {
  const data = await apiFetch<{ content: string }>(
    `/api/docs/content?doc_ref=${encodeURIComponent(docRef)}`,
  );
  return data.content;
}

/** Browser URL for a doc ref: a full docs.google.com URL is kept; a bare id is built into an edit URL. */
export function googleDocUrl(docRef: string): string {
  if (docRef.startsWith("https://docs.google.com/")) return docRef;
  return `https://docs.google.com/document/d/${encodeURIComponent(docRef)}/edit`;
}
