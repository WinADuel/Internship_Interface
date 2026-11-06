# InternHelper autofill (Chrome extension)

Fills Greenhouse, Lever and Ashby job applications with the answers you
approved in InternHelper. **It never clicks Submit.** You check the page and
submit it yourself; after the board's thank-you page appears, the job is
marked Applied in InternHelper.

## How it fits together

1. In InternHelper, save a posting on the Discover page, then press
   **Prepare** on it. InternHelper reads that job's application form from the
   job board and fills in what it can from your apply profile (Settings ›
   Apply profile) and your saved answers. Optionally, your local AI drafts
   the open questions.
2. Review and edit the answers on that page, then press **Open application**.
3. On the company's page, the InternHelper panel (bottom right) has
   **Fill application**. It fills the form with your approved answers and
   outlines every field it touched in green, and the required ones it
   couldn't fill in amber.
4. Check the page, fill what's left, and click Submit yourself.

On a Greenhouse, Lever or Ashby job that isn't saved in InternHelper, the
panel still fills your name, email, phone and links from your profile.

## Setup (once, about 2 minutes)

1. **Trust InternHelper's local certificate** (local copy only; skip this on
   the server, which has a real certificate). Caddy signs `https://localhost`
   with its own certificate authority, and Chrome extensions can't click past
   the warning the way you can. From your InternHelper folder:

   ```sh
   docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ./caddy-root.crt
   rm ./caddy-root.crt
   ```

   On Windows: double-click `caddy-root.crt`, **Install Certificate** ›
   Local Machine › "Trusted Root Certification Authorities". Restart Chrome.
2. **Make a token:** InternHelper › Settings › Apply profile › Chrome
   extension tokens › **Create token**. Copy it.
3. **Load the extension:** open `chrome://extensions`, turn on **Developer
   mode** (top right), click **Load unpacked** and choose this `extension`
   folder.
4. **Connect it:** click the extension's icon (or its **Details** ›
   **Extension options**). Enter your InternHelper address (for example
   `https://localhost`) and the token, then **Save and test**. Chrome asks
   once to let it reach that address. "Connected to InternHelper" means it's
   ready.

After you `git pull` a newer version, press the reload arrow on the
extension's card in `chrome://extensions`.

## What it can and can't fill

- **Fills:** text boxes, long answers, dropdowns (including Greenhouse's
  searchable ones), Yes/No buttons, radio buttons and checkboxes, and your
  resume upload.
- **Leaves for you:** anything you left blank in InternHelper, location boxes
  that need you to pick a suggestion from a list (on some boards), cover
  letters, captchas, and Submit.
- **Workday** and other careers sites aren't supported: each needs an account
  per company and often a captcha.

## Privacy

The extension only runs on `job-boards.greenhouse.io`, `boards.greenhouse.io`,
`jobs.lever.co` and `jobs.ashbyhq.com`, plus the InternHelper address you
give it. Its token can only read your prepared answers and mark a job
Applied; it can't reach anything else in InternHelper, and you can revoke it
in Settings. The address and token are stored in Chrome's extension storage,
never on the job board's page.

## Testing

`frontend/src/lib/apply/extensionFill.test.ts` runs `fill.js` against a
recorded Lever form in the frontend test suite. `test/e2e.mjs` loads the
extension into Chromium against a running InternHelper and fills live job
pages (never submitting); see the comment at its top.
