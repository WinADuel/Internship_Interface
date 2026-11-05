/** Whether a posting's link is a Greenhouse, Lever or Ashby job, the boards auto-apply can read. */
const GREENHOUSE_HOSTS = new Set(["boards.greenhouse.io", "job-boards.greenhouse.io"]);
const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

export function canAutoApply(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return false;
  const host = parsed.hostname.toLowerCase();
  const path = parsed.pathname;
  if (GREENHOUSE_HOSTS.has(host)) {
    return /^\/[^/]+\/jobs\/\d+\/?$/.test(path) || (/^\/embed\/job_app\/?$/.test(path) && parsed.searchParams.has("token"));
  }
  if (host === "jobs.lever.co") return new RegExp(`^/[^/]+/${UUID}(/apply)?/?$`).test(path);
  if (host === "jobs.ashbyhq.com") return new RegExp(`^/[^/]+/${UUID}(/application)?/?$`).test(path);
  return false;
}
