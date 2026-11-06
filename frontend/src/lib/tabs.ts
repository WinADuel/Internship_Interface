/**
 * Where a key press moves focus in a tab list of `count` tabs, from tab `index`:
 * the arrows wrap around, Home and End jump to the ends. null for any other key.
 */
export function tabKeyTarget(key: string, index: number, count: number): number | null {
  const last = count - 1;
  if (key === "ArrowRight") return index === last ? 0 : index + 1;
  if (key === "ArrowLeft") return index === 0 ? last : index - 1;
  if (key === "Home") return 0;
  if (key === "End") return last;
  return null;
}
