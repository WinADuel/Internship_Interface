# Phase 5 Report: Discover Inbox Ranking

| | |
|---|---|
| **Status** | Complete on branch `phase-5-inbox-ranking`. The owner reads this report and merges the PR after Phases 3 and 4 (PRs #3, #4); nothing has been merged to `main`. |
| **Built** | 2026-10-09, overnight, at the owner's request ("i would like for A B and C to all be set up if possible"). The design uses the defaults in its §2; the owner reviews them with this PR. |
| **Branch** | `phase-5-inbox-ranking`, stacked on `phase-4-interview-prep`. Until PRs #3 and #4 are merged, this PR's diff also contains them. |
| **Spec** | [`docs/superpowers/specs/2026-10-09-inbox-ranking-design.md`](../superpowers/specs/2026-10-09-inbox-ranking-design.md) |
| **Plan** | [`docs/superpowers/plans/2026-10-09-inbox-ranking-phase5.md`](../superpowers/plans/2026-10-09-inbox-ranking-phase5.md) (5 tasks) |
| **Detailed log** | [`phase-5-progress.md`](phase-5-progress.md) |
| **Tests at finish** | Backend: 1841 passing on PostgreSQL 16 (Phase 4: 1711). Frontend: 566 passing (Phase 4: 527). `svelte-check` 0/0, build clean, `alembic check` clean. |

---

## 1. What Phase 5 delivers

The Discover Inbox opens on **Best match** instead of newest first.

- **Your ranking preferences** (Settings → Discover → Ranking): roles you want, skills, preferred locations, preferred companies, companies to avoid, and dealbreaker words. A live "Top picks now: N" count updates as you type.
- **An instant match score** (0–100) on every posting, worked out in the app from those preferences. Every row has a **Why?** that lists the reasons ("Title matches 'machine learning'", "New York", "posted in the last 3 days", "Dealbreaker: 'unpaid'"). Changing preferences re-scores everything at once: about half a second for 5,000 postings.
- **A second opinion from Claude.** Each day the Claude routine reviews the 40 most promising postings it hasn't seen (you can change the number, or set 0 to turn it off). It can open a posting's page to read the full description, then writes its own score and a one-line note. Claude's score shows with a small **C** and orders the Inbox when present. If you change your preferences, older Claude scores are greyed ("preferences changed since") and offered to Claude again.
- **Top picks**: a chip that shows only postings scoring 70 or more, with their count.
- **Newest**: a toggle back to the old order.
- The Dashboard **New postings** widget shows your top 5 by Best match.
- With no preferences set, everything scores 50 and the order is newest first, exactly as before.
- **No new Google permission.** The app's own score works on the Mac and PC today; Claude's needs the server, like the rest of the routine.

## 2. How it was built

Backend tasks ran in a separate worktree while Phase 4 was finishing, then the frontend. Phase 4 was merged in twice to keep the branches in step. The lead reviewed every report and recorded the rulings.

- **End-to-end walk** against a real backend with 300 seeded postings (no network) and a simulated Claude routine. It found three small bugs: a blank Claude note rejected a whole batch, a freshness reason that disagreed with the row's date, and an out-of-date Settings description. All are fixed.
- **Review.** One Important finding: a preference change saved while a scan was running was undone by the rest of the scan. Five Minor findings: Claude scores posted after a preference change counted as fresh, the daily freshness refresh could be skipped for days, "NY" matched "Sunnyvale", Inbox actions could clash with a reload, and two bulk writes could deadlock. All are fixed with tests.

| Task | Commits |
|---|---|
| Design, plan, progress log | `3fb48f5`, `4179d9f` |
| 1. Preferences, local score, migration 0008 | `025eeb8` |
| 2. Best match / Newest, Top picks | `07faf4e` |
| 3. Claude ranking routes and routine step | `5da22f8` |
| 4. Frontend (and applied postings as examples) | `0ad673b`, `12058e2`, `9be854b` |
| 5. End-to-end fixes and docs | `142394e`, `410e7a2`, `74f5703`, `f796074` |
| Review fixes | `a707717`, `cfcfc92` |

## 3. Decisions worth knowing

- **Keywords match whole words**, so "go" doesn't match "Google" and "NY" doesn't match "Sunnyvale". Add "New York" as well as "NY" if you want both.
- **Dealbreakers sink, they don't hide.** A dealbreaker or avoided company scores 0 and goes to the bottom with the reason shown. The existing exclude keywords still hide postings completely.
- **Claude learns your taste lightly**: each run sees the titles of your 20 most recent saved or applied postings and 20 dismissals.
- **What Claude sees:** your outreach profile, your ranking preferences, and the public posting data. It never sends your profile to any site.

## 4. Known limitations

- Postings carry only list data (title, company, location, dates). The app's score can't read job descriptions; Claude's can.
- Claude ranking hasn't run for real yet. It starts after the deploy, as the routine's last step.

## 5. What's next

- Merge in order: #3, #4, #5, then #6 (Gmail sync).
- After the deploy, set your ranking preferences, then check the Inbox after the first Claude run.
