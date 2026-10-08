/** Only http(s) links are ever rendered as anchors (defense in depth on top of the server filter). */
export function isSafeHttpUrl(url: string | null | undefined): url is string {
  return typeof url === "string" && /^https?:\/\//i.test(url.trim());
}
