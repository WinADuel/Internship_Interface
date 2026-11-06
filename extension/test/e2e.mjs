// Manual end-to-end check: loads the extension into Chromium, points it at a
// running InternHelper, opens live application pages and fills them. It
// never clicks Submit. Usage:
//   INTERNHELPER_URL=http://127.0.0.1:8000 INTERNHELPER_TOKEN=ih_... node e2e.mjs <job url> [...]
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const here = dirname(fileURLToPath(import.meta.url));
const base = process.env.INTERNHELPER_URL || "http://127.0.0.1:8000";
const token = process.env.INTERNHELPER_TOKEN;
const urls = process.argv.slice(2);
const shots = process.env.SHOTS_DIR || tmpdir();

// A copy whose manifest already allows the test InternHelper address (the
// real extension asks for it on its options page).
const dir = mkdtempSync(join(tmpdir(), "ih-ext-"));
cpSync(join(here, ".."), dir, { recursive: true, filter: (p) => !p.includes(`${join(here)}`) });
const manifest = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
manifest.host_permissions.push(`${new URL(base).origin}/*`);
writeFileSync(join(dir, "manifest.json"), JSON.stringify(manifest));

const context = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "ih-profile-")), {
  headless: false,
  args: [`--headless=new`, `--disable-extensions-except=${dir}`, `--load-extension=${dir}`],
  viewport: { width: 1280, height: 1000 },
});
let [worker] = context.serviceWorkers();
if (!worker) worker = await context.waitForEvent("serviceworker");
await worker.evaluate(([b, t]) => chrome.storage.local.set({ baseUrl: b, token: t }), [base, token]);

for (const [i, url] of urls.entries()) {
  const page = await context.newPage();
  page.on("console", (m) => process.env.DEBUG && console.log("  console:", m.text()));
  await page.goto(url, { waitUntil: "load" });
  const fill = page.locator("#internhelper-panel").locator("button.fill");
  await fill.waitFor({ timeout: 20000 });
  await fill.click();
  const status = page.locator("#internhelper-panel").locator(".status");
  await page
    .waitForFunction(
      () => /Check everything|Couldn't|refused|reach/.test(document.querySelector("#internhelper-panel")?.shadowRoot?.querySelector(".status")?.textContent || ""),
      null,
      { timeout: 90000 },
    )
    .catch(() => console.log("  (timed out waiting for the fill to finish)"));
  console.log(`\n${url}\n  ${await status.textContent()}`);
  const values = await page.evaluate(() =>
    Array.from(document.querySelectorAll("input:not([type=hidden]), textarea, select"))
      .filter((el) => (el.type === "radio" || el.type === "checkbox" ? el.checked : el.type === "file" ? el.files.length : el.value))
      .map((el) => `${el.id || el.name}: ${el.type === "file" ? el.files[0].name : el.type === "radio" || el.type === "checkbox" ? el.value : el.value}`.slice(0, 110)),
  );
  const chosen = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".select__single-value, .select__multi-value__label")).map((el) => el.textContent),
  );
  console.log("  inputs: " + values.join("\n          "));
  if (chosen.length) console.log("  picked: " + chosen.join(" | "));
  await page.screenshot({ path: join(shots, `fill-${i + 1}.png`), fullPage: true });
}
await context.close();
