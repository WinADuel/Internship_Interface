/** Longest compose URL we trust browsers and Gmail to accept; longer drafts use Copy. */
export const MAX_GMAIL_URL_LENGTH = 2000;

/** A Gmail compose link (spec §13.6). The app never sends mail itself. */
export function gmailComposeUrl(to: string, subject: string, body: string): string {
  const params = [
    "view=cm",
    "fs=1",
    `to=${encodeURIComponent(to)}`,
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
