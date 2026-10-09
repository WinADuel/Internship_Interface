# Phase 4 Report: Interview Prep

| | |
|---|---|
| **Status** | Complete on branch `phase-4-interview-prep`. The owner reads this report and merges the PR after Phase 3 (PR #3); nothing has been merged to `main`. |
| **Built** | 2026-10-09, overnight, at the owner's request ("i would like for A B and C to all be set up if possible"). The design uses the defaults in its §2; the owner reviews them with this PR. |
| **Branch** | `phase-4-interview-prep`, cut from `phase-3-deploy` at `b49f4ec`. Until PR #3 is merged, this PR's diff also contains Phase 3. |
| **Spec** | [`docs/superpowers/specs/2026-10-09-interview-prep-design.md`](../superpowers/specs/2026-10-09-interview-prep-design.md) |
| **Plan** | [`docs/superpowers/plans/2026-10-09-interview-prep-phase4.md`](../superpowers/plans/2026-10-09-interview-prep-phase4.md) (8 tasks) |
| **Detailed log** | [`phase-4-progress.md`](phase-4-progress.md): every task, finding and ruling |
| **Tests at finish** | Backend: 1711 passing on real PostgreSQL 16 (Phase 3: 1537). Frontend: 527 passing (Phase 3: 440). `svelte-check` 0 errors, 0 warnings. Build clean. `alembic check` clean. |

---

## 1. What Phase 4 delivers

The **Interview Prep** menu item, "Coming soon" since Phase 1, now works.

- **Interview rounds.** An application can have several rounds (recruiter screen, technical, behavioural, case, onsite, final, other), each with a date, length, format, meeting link or address, and interviewers. Add them from the application panel or the Interview Prep page.
  - The application's **Next interview** is now worked out from its rounds (the earliest still scheduled), so the Dashboard reminders and the backup sheet keep working. Existing interview dates became rounds when the database was upgraded.
  - When an application with rounds is still before the Interview stage, the panel offers **Move to Interview**. Nothing changes status by itself.
- **A prep page for every round**, with:
  - a countdown and **Add to calendar** (an `.ics` file for Apple Calendar, Google Calendar or Outlook);
  - a checklist that starts with six sensible items;
  - prep notes and questions to ask, which save as you type;
  - the stories you plan to tell, picked from a **story bank** of STAR-format stories you reuse across interviews;
  - the interviewers, linked to your contacts;
  - a **company brief** written by the daily Claude routine when you press **Ask Claude for a brief**;
  - copy buttons for five ready-made Claude prompts filled in with the company and role: company research, likely questions for the round, a mock interview, "tell me about yourself" (from your outreach profile) and a thank-you note;
  - after the interview: mark it done, record the outcome and how it went, and **Draft thank-you** for each interviewer, which opens Gmail with a short note for you to edit and send.
- **Dashboard:** a new **Upcoming interviews** widget shows the next 14 days with checklist progress, and flags any thank-you that is due (for 3 days after a round).
- **Backup sheet:** a new **Interviews** tab. Prep notes and reflections are not exported.
- **No new Google permission.** The company brief needs the server, like the rest of the Claude routine; everything else works on the Mac and PC today.

## 2. How it was built

The plan's 8 tasks ran with up to two implementers in parallel: the backend in the main checkout and the frontend in a separate worktree, built against the spec's route list and merged once both were done. The lead reviewed every report and diff and recorded each ruling in the progress log.

Then:
- **End-to-end walk.** The merged app ran against a real database in headless Chromium through every feature, including a simulated Claude routine posting a brief. It found one bug, which predates Phase 4: a contact created with a typed email was saved as "email not found". It is fixed.
- **Whole-branch review.** One reviewer covered the backend and docs, another the frontend. Two Important findings, both fixed with tests:
  - rolling the database back to Phase 3 after requesting a brief would have broken the Research Queue page;
  - a slow save could undo a checklist tick made while it was in flight.
  The ten Minor findings (row locks for two simultaneous saves, sheet syncs on every autosave, autosave edge cases, a silent failure on very long thank-you drafts, a duplicate contact on retry, frozen countdowns) are all fixed too.

| Task | Commits |
|---|---|
| Design, plan, progress log | `512716f`, `fe94e62` |
| 1. Data model, migration 0007, service core | `3ca4668` |
| 2. Routes and calendar export | `6ea6d94` |
| 3. Claude company brief | `84534fe` |
| 4. Interviews tab in the backup sheet | `4c657f2` |
| 5–7. Frontend (merged in `64eb18f`) | `4ca76c1`, `c1f5796`, `0ee591c` |
| 8. End-to-end fix, docs | `d01bfbf`, `b74fd17` |
| Review fixes | `75067f9`, `f04e08e` |

## 3. Decisions worth knowing

- **Next interview is derived.** You edit rounds, not the date on the application. The create form still accepts a date and turns it into the first round.
- **One "Mark sent" per round**, with a separate Draft thank-you per interviewer.
- **The calendar file's link** to the prep page uses the site address from `GOOGLE_REDIRECT_URI`, which is your domain on the server and `localhost` on the Mac and PC.
- **The Claude routine sees only the company, role and job link** for a brief, never your notes, stories or contacts. Its text is shown as plain text, and only http(s) links are kept.

## 4. Known limitations

- The company brief needs the server and the Claude routine; until then a request waits in the queue.
- The prep page shows one console error (a 404 for "no brief yet"); it is harmless.
- Two checklist ticks sent at the same instant from two devices can arrive at the server in either order; the last one wins.
- Not tested against the real Claude routine yet; that happens after the deploy.

## 5. What's next

- Phase 5 (Discover inbox ranking) and Phase 6 (Gmail sync) were built the same night on top of this branch; merge in order: #3, #4, #5, #6.
- After the deploy, run the Claude routine once and check that a requested brief arrives.
