type Raw = Record<string, unknown>;

export function snakeToCamel(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

export function camelToSnake(key: string): string {
  return key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

/** Shallow key rename of an API object; values are left untouched. */
export function keysToCamel<T>(raw: Raw): T {
  const out: Raw = {};
  for (const [k, v] of Object.entries(raw)) out[snakeToCamel(k)] = v;
  return out as T;
}

/** Shallow key rename for request bodies; only keys present are emitted (safe for PATCH). */
export function keysToSnake(data: object): Raw {
  const out: Raw = {};
  for (const [k, v] of Object.entries(data)) out[camelToSnake(k)] = v;
  return out;
}
