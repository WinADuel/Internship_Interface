/** Longest compose URL we trust browsers and Gmail to accept; longer drafts use Copy. */
export const MAX_GMAIL_URL_LENGTH = 2000;

// One plain address, mirroring the backend's ingest rule. Gmail decodes `to=`
// and splits on commas/semicolons, so anything else could add recipients.
const SINGLE_ADDRESS = /^[A-Za-z0-9.!#$*+/^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/;

export function isSingleAddress(value: string): boolean {
  return SINGLE_ADDRESS.test(value);
}

/**
 * A Gmail compose link (spec §13.6). The app never sends mail itself.
 * A `to` that isn't exactly one address is left out; the user fills it in.
 */
export function gmailComposeUrl(to: string, subject: string, body: string): string {
  const params = [
    "view=cm",
    "fs=1",
    `to=${isSingleAddress(to) ? encodeURIComponent(to) : ""}`,
    `su=${encodeURIComponent(subject)}`,
    `body=${encodeURIComponent(body)}`,
  ];
  return `https://mail.google.com/mail/?${params.join("&")}`;
}

export function fitsInGmailUrl(url: string): boolean {
  return url.length <= MAX_GMAIL_URL_LENGTH;
}

/** Shown before opening a compose link for a pattern-guessed address (spec §13.6). */
export const GUESS_WARNING = "This address is a guess and may bounce. Open anyway?";
