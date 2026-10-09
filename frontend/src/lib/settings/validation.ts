/**
 * Splits FastAPI 422 `detail` items into messages for the given body fields
 * (the first message per field) and the rest as plain text. Pydantic's
 * "Value error, " prefix is dropped.
 */
export function splitValidation<F extends string>(
  detail: unknown[],
  known: ReadonlySet<F>,
): { fields: Partial<Record<F, string>>; other: string[] } {
  const fields: Partial<Record<F, string>> = {};
  const other: string[] = [];
  for (const item of detail) {
    const { loc, msg } = (item ?? {}) as { loc?: unknown; msg?: unknown };
    if (typeof msg !== "string") continue;
    const text = msg.replace(/^Value error, /, "");
    const field = Array.isArray(loc) && loc[0] === "body" ? loc[1] : undefined;
    if (typeof field === "string" && known.has(field as F)) fields[field as F] ??= text;
    else other.push(text);
  }
  return { fields, other };
}
