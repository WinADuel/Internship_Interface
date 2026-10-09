# Putting the tracker on a server

This guide puts the tracker on the internet at your own address, like `https://yourdomain.com`.
Then you can use one tracker from your phone, your MacBook and your Windows PC.

You only do steps 1 to 10 once. Step 11 is for later, when you update or fix things.

**Before you start**

- Allow an afternoon. Most of it is waiting (domain, builds).
- The commands are for your **Mac**. Open **Terminal**: press Cmd+Space, type `Terminal`, press Enter.
- Anything in `<angle brackets>` is a placeholder. Replace the whole thing, brackets too.
  For example, `ssh root@<IP>` becomes `ssh root@203.0.113.10`.
- Copy commands exactly. To paste into Terminal, press Cmd+V.
- You'll make several secrets. Keep a password manager open (1Password, Bitwarden, iCloud Keychain's Passwords app...).
  Never send a secret by chat or email.

**What it costs**

| What | Price |
|---|---|
| Server (DigitalOcean droplet, 1 GB) | $6 a month |
| Domain (`.com` at Porkbun) | about $11 a year |
| DigitalOcean weekly backups (optional) | about $1.20 a month |

---

## 1. Accounts and the domain

1. **Student credit (if you qualify).** Go to [education.github.com/pack](https://education.github.com/pack) and click **Get student benefits**.
   Sign in with your GitHub account and verify you're a student. Approval can take a few days.
   Once approved, find **DigitalOcean** in the pack and follow its link to claim the credit.
2. **DigitalOcean account.** Sign up at [digitalocean.com](https://www.digitalocean.com).
   If you got the student offer, sign up through its link so the credit applies.
   DigitalOcean still asks for a card or PayPal.
3. **Buy the domain.** Go to [porkbun.com](https://porkbun.com), search for the name you want, and buy the `.com`.
   WHOIS privacy is free and on by default. Leave auto-renew on.

   *Alternative:* Cloudflare Registrar also works. There, the DNS record in step 4 must be set to **DNS only** (grey cloud), not **Proxied** (orange cloud).
   Otherwise the server can't get its HTTPS certificate.

**What you should see:** you can log in to DigitalOcean, and Porkbun lists your domain under **Domain Management**.

---

## 2. SSH key and the droplet

An SSH key lets your Mac log in to the server without a password. You make it once.

1. In Terminal on your Mac:

   ```
   ssh-keygen -t ed25519 -C "tracker"
   ```

   - "Enter file in which to save the key": just press Enter (keeps the default, `~/.ssh/id_ed25519`).
     If it says the file already exists, you already have a key: type `n` and use that one.
   - "Enter passphrase": type a passphrase, press Enter, then type it again. Save it in your password manager.
     (Nothing shows while you type. That's normal.)
2. Copy the **public** half of the key:

   ```
   pbcopy < ~/.ssh/id_ed25519.pub
   ```

   Nothing prints. The key is now on your clipboard. (The file without `.pub` is the private key. Never share it.)
3. In DigitalOcean, click **Create → Droplets**, and choose:
   - **Region:** New York (any New York datacenter).
   - **Image:** OS → **Ubuntu**, version **24.04 (LTS) x64**.
   - **Size:** Droplet Type **Basic**, CPU options **Regular** (SSD), then the **$6/mo** plan (1 GB / 1 CPU, 25 GB disk).
   - **Authentication method:** **SSH Key** → **New SSH Key**. Paste (Cmd+V) into the box, name it `MacBook`, and click **Add SSH Key**.
     Make sure it's ticked.
   - **Backups:** optional. Weekly backups cost about $1.20 a month. They're a second safety net; the app makes its own backups too.
   - **Hostname:** `tracker`.
4. Click **Create Droplet**. After a minute it shows an **IPv4** address, like `203.0.113.10`.
   Save it in your password manager. This guide calls it `<IP>`.

You can make the droplet bigger later (2 GB, $12 a month) if builds run out of memory: droplet → **Resize**. Nothing needs reinstalling.

**If it goes wrong:** if you forgot the SSH key and picked a password, destroy the droplet (droplet → **Destroy**) and create it again with the key. It only costs a few cents.

---

## 3. Set up the server (`bootstrap.sh`)

This runs once. It makes a `deploy` user for you to log in as, turns off password and root login, turns on the firewall, installs Docker, turns on automatic security updates, adds swap space and sets the time zone.

1. On your Mac, go to your copy of the repo and get the latest code. Use your real folder:

   ```
   cd ~/Internship_Interface
   git checkout main
   git pull
   ```
2. Copy the script to the server:

   ```
   scp ops/server/bootstrap.sh root@<IP>:
   ```

   The first time, it asks "Are you sure you want to continue connecting (yes/no/[fingerprint])?". Type `yes` and press Enter.
   Then it asks for your SSH key's passphrase.
3. Log in to the server as root and run it:

   ```
   ssh root@<IP>
   bash bootstrap.sh
   ```

   This uses the time zone `America/Chicago`. For another one, add its name: `bash bootstrap.sh America/New_York`.
   (To see what it would do without changing anything: `bash bootstrap.sh --dry-run`.)

   It takes a few minutes. Each step starts with `==>`.

**What you should see** at the end:

```
==> Done
    user:      deploy, with sudo and Docker; SSH key copied from root
    SSH:       keys only, no root login
    firewall:  on; open: 22/tcp (SSH), 80/tcp, 443/tcp, 443/udp
    ...
Next:
    1. Keep this root window open. In a NEW terminal on your Mac, check you can log in:
         ssh deploy@<IP>
```

4. **Keep the root window open.** Open a **new** Terminal window (Cmd+N) and log in as `deploy`:

   ```
   ssh deploy@<IP>
   ```

   You should get a prompt like `deploy@tracker:~$`. Check Docker works: `docker compose version` prints a version.
5. Only now, close the root window (type `exit`). From now on you always log in as `deploy`.
   Root login is off: `ssh root@<IP>` now says "Permission denied".

**If it goes wrong**

- `ERROR: this script is written for Ubuntu 24.04` → the droplet has another system. Destroy it and create it with Ubuntu 24.04 (LTS).
- `WARNING: root has no SSH key ... root and password login stay ON` → the droplet was made without your key. Destroy it and create it again with the key (step 2).
- `ssh deploy@<IP>` doesn't work → don't close the root window. In it, run `bash bootstrap.sh` again and read any `ERROR` or `WARNING`.
  If you're locked out completely, destroy the droplet and start step 2 again. Nothing is on it yet.
- Running `bootstrap.sh` twice is safe. It skips what's already done.

**Tip:** to stop your Mac asking for the key passphrase every time, run `ssh-add --apple-use-keychain ~/.ssh/id_ed25519` once.

---

## 4. Point the domain at the server (DNS)

You can do this while `bootstrap.sh` runs.

1. In Porkbun, open **Domain Management**, find your domain and click **DNS** (under its details).
2. Delete Porkbun's parking records if they're there: an **ALIAS** record on your bare domain and a **CNAME** record for `*`, both pointing at `pixie.porkbun.com`.
   Click the trash icon next to each.
3. Add one record:
   - **Type:** `A`
   - **Host:** leave it blank (that means the bare domain, `yourdomain.com`)
   - **Answer:** your `<IP>`
   - **TTL:** `600`

   Click **Add**.
4. Skip `www`. The server only answers on the bare domain, so a `www` record isn't needed. Don't add an `AAAA` record either.
5. Check it from your Mac. Repeat every few minutes until it prints your IP:

   ```
   dig +short yourdomain.com
   ```

**What you should see:** just your IP, like `203.0.113.10`. It usually takes 5 to 30 minutes, sometimes a few hours.

**If it goes wrong:** if it prints another address too, a parking record is still there. Delete it.
If nothing prints after a few hours, check the record's Host is blank and the Answer is the droplet's IPv4.

---

## 5. Deploy key and the code

The server downloads the code from GitHub with a **deploy key**. It can only read this one repo and can never change it.

Do all of this logged in as `deploy` (`ssh deploy@<IP>`).

1. Make the key (no passphrase, so the server can use it by itself):

   ```
   ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
   cat ~/.ssh/github_deploy.pub
   ```

   It prints one line starting with `ssh-ed25519`. Select the whole line and copy it (Cmd+C).
2. On GitHub, open the repo **WinADuel/Internship_Interface** → **Settings** → **Deploy keys** → **Add deploy key**.
   - **Title:** `tracker server`
   - **Key:** paste the line.
   - Leave **Allow write access** unticked.

   Click **Add key**.
3. Tell SSH on the server to use this key for GitHub. Paste all five lines at once:

   ```
   cat >> ~/.ssh/config <<'EOF'
   Host github.com
     IdentityFile ~/.ssh/github_deploy
     IdentitiesOnly yes
   EOF
   chmod 600 ~/.ssh/config
   ```
4. Test it:

   ```
   ssh -T git@github.com
   ```

   The first time, it asks to trust github.com. GitHub's real ED25519 fingerprint is `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`.
   If yours matches, type `yes`.

   **What you should see:** `Hi WinADuel/Internship_Interface! You've successfully authenticated, but GitHub does not provide shell access.`
5. Download the code:

   ```
   git clone git@github.com:WinADuel/Internship_Interface.git ~/Internship_Interface
   cd ~/Internship_Interface
   ```

**If it goes wrong:** `Permission denied (publickey)` means GitHub doesn't know the key.
Check you pasted the whole `.pub` line into **Deploy keys** on the right repo, and that `~/.ssh/config` has the lines above (`cat ~/.ssh/config`).

---

## 6. The server's `.env` file

`.env` holds the server's settings and secrets. It never goes into git.

1. Make it from the example and make it private:

   ```
   cd ~/Internship_Interface
   cp .env.example .env
   chmod 600 .env
   ```
2. Make the new secrets. Run each command on the server. Each prints a random value. The server gets its own new secrets; don't reuse the ones from your Mac or PC.

   ```
   openssl rand -hex 16
   ```
   → the database password.

   ```
   openssl rand -hex 48
   ```
   → `JWT_SECRET`.

   ```
   openssl rand -base64 32 | tr '+/' '-_'
   ```
   → `TOKEN_ENCRYPTION_KEY`. Run it a **second** time for `BACKUP_ENCRYPTION_KEY` (they must be different).
3. Open the file in the editor:

   ```
   nano .env
   ```

   Move with the arrow keys. Delete the old value with Backspace. Paste with Cmd+V. Set each line like this:

   - `DOMAIN=yourdomain.com` (just the name: no `https://`, no slash)
   - `CONTACT_EMAIL=` your email. It is shown on the public About and Privacy pages, and Google needs it there to publish the app (step 8).
   - `POSTGRES_USER` and `POSTGRES_DB`: leave as they are.
   - `POSTGRES_PASSWORD=` the database password.
   - `DATABASE_URL=`: replace `change-me-db-password` with the **same** database password. Keep the rest of the line.
   - `JWT_SECRET=` its value.
   - `TOKEN_ENCRYPTION_KEY=` its value.
   - `BACKUP_ENCRYPTION_KEY=` its value. This turns on the encrypted backup copies in Google Drive.
   - `GOOGLE_CLIENT_ID=` and `GOOGLE_CLIENT_SECRET=`: copy them from the `.env` on your Windows PC (the repo folder there).
     Put them in your password manager on the PC, then paste them from the password manager here. Never through chat or email.
   - `GOOGLE_REDIRECT_URI=https://yourdomain.com/api/docs/google/callback`
   - `COOKIE_SECURE=true`
   - `TZ=America/Chicago` (or your time zone)

   Save with Ctrl+O, then Enter. Exit with Ctrl+X.
4. Check it:

   ```
   grep change-me .env
   ls -l .env
   ```

   **What you should see:** the `grep` prints nothing, and `ls` shows `-rw-------` at the start.
5. **Save the finished `.env` in your password manager.** Run `cat .env`, copy everything it prints into a secure note called "Tracker server .env", then run `clear`.
   It holds `TOKEN_ENCRYPTION_KEY` and `BACKUP_ENCRYPTION_KEY`. Without them, the encrypted data and the Drive backups can never be read again.

---

## 7. First deploy

1. As `deploy`:

   ```
   cd ~/Internship_Interface
   ops/server/deploy.sh
   ```

   The first time, it skips the backup (`first deploy: no database yet, skipping backup`) and builds everything.
   On a 1 GB droplet that takes several minutes, often 10 or more. Let it run.

   **What you should see** at the end:

   ```
   ==> Waiting up to 120s for https://yourdomain.com/api/health
       healthy
   ==> Deployed
   ```

   It also prints "To go back to the previous code". You can ignore that the first time.
2. Create your account:

   ```
   docker compose exec backend python -m app.cli create-user --username <you>
   ```

   - Type a password twice (nothing shows while you type).
   - It prints a QR code. If it looks broken, make the window bigger or zoom out (Cmd+-).
   - Scan it with your authenticator app. It's a **new** entry, separate from your Mac/PC copies (they have their own accounts).
     If your app allows it, rename it to something like "Tracker server".
   - Type the 6-digit code. **What you should see:** `Account ready. Log in at /#/login.`
3. Open `https://yourdomain.com` on your Mac, your PC and your phone, and log in.
4. On your iPhone: in **Safari**, tap **Share** → **Add to Home Screen** → **Add**. The tracker now opens from its own icon.

**If it goes wrong**

- `ERROR: .env still has change-me placeholders: ...` → step 6 isn't finished. `nano .env` and fill in the names it lists.
- `ERROR: DOMAIN in .env is still the example` → set `DOMAIN` to your domain.
- `ERROR: CONTACT_EMAIL in .env is still an example address` → set `CONTACT_EMAIL` to your email.
- `ERROR: cannot talk to Docker.` → log out (`exit`) and log back in (`ssh deploy@<IP>`), then try again.
- `did not answer within 120s` → usually the HTTPS certificate. DNS must point at the droplet (step 4) before the first deploy.
  Check `dig +short yourdomain.com` shows your IP and `docker compose logs caddy --tail 50`.
  Caddy keeps retrying by itself. Once DNS is right, the site starts working within a few minutes; you don't need to deploy again.
- The build stops with "killed" or "out of memory" → resize the droplet to 2 GB (step 2), then run `ops/server/deploy.sh` again.

---

## 8. Google: publish the app and connect

The server needs its own address in the Google Cloud project you already use (`internship-tracker`).
Publishing the app stops Google from logging you out of Google every 7 days.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and pick the **internship-tracker** project at the top.
2. Open **Google Auth Platform** from the menu. (Older screens call it **APIs & Services → OAuth consent screen**.)
3. **Clients** → click your web client.
   Under **Authorized redirect URIs**, click **Add URI** and paste `https://yourdomain.com/api/docs/google/callback`.
   Keep the `localhost` one, which your Mac and PC copies use. Click **Save**.
4. **Branding**:
   - **Application home page:** `https://yourdomain.com/about.html`
   - **Application privacy policy link:** `https://yourdomain.com/privacy.html`
   - **Authorized domains:** click **Add domain** and type `yourdomain.com`.
   - Don't upload a logo. A logo makes Google ask for a review.

   Click **Save**. Open both links in your browser first to check they load.
5. **Audience** → **Publish app** → **Confirm**. The status changes from "Testing" to "In production".
6. In the tracker, go to **Settings → Backup sheet** and press **Sync now**. It fails with "google not connected" and shows a **Connect Google** link. Click it.
   (The **Connect Google Docs** link on the Essays page does the same.)
   - Google shows **"Google hasn't verified this app"**. That's expected for a personal app. Click **Advanced** → **Go to ... (unsafe)**.
   - Tick every permission box, then **Continue**.

   You land back on the Essays page. Now that the app is published, this connection doesn't expire after 7 days.
7. Back in **Settings → Backup sheet**, press **Sync now**. **What you should see:** "Backup sheet synced." and an **Open backup sheet** link.
8. In **Settings → Backups**, press **Back up now**. "Last backup" changes to "just now" (or a minute ago).
   This copy stays on the server. The encrypted copy in your Google Drive comes with the nightly backup at 02:30.
   Until then the card says "Last off-site copy: none yet". The next morning it shows a time, and Drive has a folder **Internship Tracker Backups**.
   If the card instead says off-site copies are off, check `BACKUP_ENCRYPTION_KEY` is set in `.env` (then run `ops/server/deploy.sh` to apply it) and that Google is connected.

**If it goes wrong:** Google says `Error 400: redirect_uri_mismatch` → the URI in step 3 and `GOOGLE_REDIRECT_URI` in `.env` must match exactly: `https`, no `www`, no slash at the end.
Google can take a few minutes to apply a new URI.

### Turn on Gmail sync (optional)

Gmail sync reads the headers and Gmail's short preview of your recent Inbox and Sent mail, spots application updates and contact replies, and lists them on the **Email updates** page for you to accept or dismiss.
It never downloads message bodies and never sends email. Skip this part if you don't want it; everything else works without it.

Gmail's read permission (`gmail.readonly`) is one Google calls *restricted*. A public app with it needs Google's security review, but a personal app (you, plus fewer than 100 users) doesn't: you just click through the "Google hasn't verified this app" screen once, as in step 6 above.

1. In [console.cloud.google.com](https://console.cloud.google.com), with the **internship-tracker** project picked, open **APIs & Services → Library**, search for **Gmail API**, open it and click **Enable**.
2. Open **Google Auth Platform → Data Access** → **Add or remove scopes**. Find `.../auth/gmail.readonly` (filter for "gmail.readonly"), tick it, click **Update**, then **Save**.
   - If the console then wants a review before the app can stay published, remove the scope again and save: the tracker asks for it at sign-in anyway, and the unverified-app screen covers it.
3. In the tracker, go to **Settings → Gmail** and click **Connect Gmail**.
   - Google shows **"Google hasn't verified this app"** again. Click **Advanced** → **Go to ... (unsafe)**.
   - Tick the box that lets the app **read your email**, then **Continue**.

   You land back on Settings with "Gmail connected", and the card says **Gmail: Connected**.
   If it says Gmail wasn't connected, the box wasn't ticked: click **Connect Gmail** and try again.
4. Tick **Sync Gmail** and click **Save Gmail settings**. The defaults are fine: check every 30 minutes, and look back 30 days on the first sync.
   Leave **Apply some updates automatically** off at first; turn it on later if you want confirmations and contact replies applied without asking (rejections, interviews, assessments and offers always wait for you).
5. Press **Sync now**. **What you should see:** "Checked N emails: M updates found." and **Email updates** in the menu with a count when there is something to review.
   After this, the `gmail-sync` service checks by itself on the interval you chose.

**Good to know:**
- Changing your Google account password disconnects Gmail sync (Google's rule for mail access). Settings then shows "Last sync failed: reconnect Google and allow Gmail in Settings" with a **Reconnect Gmail** link; click it and go through step 3 again.
- To stop it, untick **Sync Gmail**. To withdraw the permission completely, remove the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions) (that also disconnects Docs and backups until you connect Google again).
- The console clicks above were written from Google's documentation and are confirmed during the live setup; if a screen looks different, the names (Gmail API, Data Access, `gmail.readonly`) stay the same.

---

## 9. The daily Claude job

The routine researches your Research Queue every morning: people to contact, and the company briefs you ask for from an interview's prep page (**Ask Claude for a brief**). It runs in the cloud and needs the server's address.

1. In the tracker: **Settings → Claude tokens → Create token**. Copy the token now; it's shown once.
2. Set up the routine as described in the appendix of
   [`ops/claude-routine/outreach-job.md`](../../ops/claude-routine/outreach-job.md#appendix-setting-up-the-routine-for-the-user), with:
   - `APP_BASE_URL=https://yourdomain.com`
   - `CLAUDE_TOKEN=` the token from step 1.

   Keep both in the routine's settings, never in the repo.

   The routine runs in a cloud environment that may only reach some websites.
   In that environment's network access settings, allow your domain (`yourdomain.com`), or its requests to the tracker are blocked.
3. Run it once by hand and check the Research Queue page. To test a brief, press **Ask Claude for a brief** on any interview round's prep page first; after the run, the brief shows on that page.

The routine's last step ranks your Discover Inbox: it reviews the highest-scoring Inbox postings it hasn't reviewed yet (40 a day by default) and gives each its own score and note (marked **C** in the Inbox). Change the number, or set 0 to turn ranking off, in **Settings → Ranking → Postings Claude reviews per day**.

---

## 10. Uptime alert

A free check that emails you if the site goes down.

1. Sign up at [uptimerobot.com](https://uptimerobot.com) (free plan).
2. Click **New monitor** (or **Add New Monitor**):
   - **Monitor type:** HTTP(s)
   - **Friendly name:** `Tracker`
   - **URL:** `https://yourdomain.com/api/health`
   - **Monitoring interval:** 5 minutes
   - **Alert contacts:** your email (tick it).
3. Click **Create Monitor**. After a few minutes it shows **Up**.

---

## 11. Day to day

Always start by logging in and going to the repo folder:

```
ssh deploy@<IP>
cd ~/Internship_Interface
```

### Deploy after a merge

```
ops/server/deploy.sh
```

It backs up the database, gets the newest `main` from GitHub, rebuilds and checks the site.
At the end it prints the command that undoes this deploy. Copy it into your notes before you close the window.

### Roll back

Run the command the deploy printed under "To undo this deploy". It looks like this:

```
ops/server/deploy.sh --restore /backups/pre-deploy/tracker-<date>.dump <previous commit>
```

It does the whole rollback in one go: it backs up the data as it is now, goes back to the previous code,
puts back the database as it was just before the bad deploy, starts the app and checks the site.
It asks you to type the database name (`internship_tracker`) first.

Why the database too: a new version can change how the data is stored (a migration).
The old version may not start on the changed database, so going back to the old code alone can leave the site down.
Putting back the backup from just before the deploy fixes that.
The catch: anything you changed in the tracker since that deploy is lost.

The deploy also printed a shorter command, `ops/server/deploy.sh <previous commit>`.
It goes back to the old code and keeps the data as it is now.
Use it only if you know the bad deploy didn't change the database. If you're not sure, use the command above.

Changed your mind? The rollback prints its own "To undo" command at the end, like any deploy.

### Restore a backup

The server's own backups are in `~/Internship_Interface/backups/` (`nightly/`, `pre-deploy/` and `manual/`).
They belong to root, so list them with `sudo`, and restore through the script:

```
sudo ls -lh backups/nightly
ops/server/restore.sh backups/nightly/tracker-<date>.dump
```

The time in the file name is UTC (the `Z`). For example, `tracker-20261008T073000Z.dump` is 02:30 Chicago time in summer.

The script checks the file, then asks you to type the database name (`internship_tracker`) to confirm.
It saves a copy of the current data first, replaces everything, and restarts the app.
**What you should see:** `==> Restored`. If the restore fails, the old data stays as it was.

**From a Google Drive copy** (if the server's own backups are gone):

1. In Google Drive, open **Internship Tracker Backups** and download the newest `tracker-....dump.enc` to your Mac.
2. Copy it to the server, from your Mac:

   ```
   scp ~/Downloads/tracker-<date>.dump.enc deploy@<IP>:
   ```
3. On the server:

   ```
   cd ~/Internship_Interface
   ops/server/restore.sh ~/tracker-<date>.dump.enc
   ```

   It needs the same `BACKUP_ENCRYPTION_KEY` in `.env` that made the copy.

### Read the logs

```
docker compose ps
docker compose logs backend --tail 50
docker compose logs caddy --tail 50
```

`docker compose ps` should show every service `Up`, and the backend `(healthy)`.

### Disk space

```
df -h /
```

Look at **Use%**. Above 80%, clear out old Docker build leftovers:

```
docker image prune -f
docker builder prune -f
```

These never touch your data.

### Good to know

- **Backups:** every night at 02:30, the server keeps 14 nightly backups, 5 pre-deploy and 5 manual ones.
  Drive keeps the newest 30 encrypted copies. A backup bigger than 100 MB isn't copied to Drive; Settings → Backups then shows an error. (Yours is far smaller.)
- **Security updates** install by themselves. If one needs a reboot, the server restarts at 04:30 and the app comes back on its own.
- **Keep `.env` safe:** it lives on the server (only `deploy` can read it) and in your password manager. Update the password manager copy whenever you change it.
- **From the Windows PC:** PowerShell has `ssh` built in. Make a key there with `ssh-keygen -t ed25519 -C "tracker-pc"`,
  copy it with `Get-Content ~\.ssh\id_ed25519.pub | Set-Clipboard`, then on the server (from your Mac) add it as a new line in `~/.ssh/authorized_keys` with `nano`.

### Troubleshooting

| Problem | What to check |
|---|---|
| The site doesn't load | `dig +short yourdomain.com` shows the droplet's IP (DNS). `docker compose ps` shows everything `Up`. The firewall allows 80 and 443 (`sudo ufw status`). |
| Certificate or "not secure" errors | DNS must point at the droplet before the first deploy. `docker compose logs caddy --tail 50` shows why. Caddy retries by itself once DNS is right. |
| The build runs out of memory ("killed") | Resize the droplet to 2 GB in DigitalOcean (droplet → **Resize**), then `ops/server/deploy.sh` again. |
| Google says `redirect_uri_mismatch` | `GOOGLE_REDIRECT_URI` in `.env` and the URI in Google Cloud (step 8) must match exactly. After editing `.env`, run `ops/server/deploy.sh` to apply it. |
| Login gives an error (500) after moving servers | `TOKEN_ENCRYPTION_KEY` changed. See [Moving to a new server](../../README.md#moving-to-a-new-server) in the README. |
| `deploy.sh` says files were changed on the server | Someone edited code on the server. Undo it with `git checkout -- <file>`. |
| `bootstrap.sh` stops with "Could not get lock /var/lib/dpkg/lock-frontend" | A new droplet installs its first security updates right after it starts. The script waits up to 10 minutes for them. If it still stops, wait a few more minutes and run `bash bootstrap.sh` again. |
| Settings → Gmail shows "reconnect Google and allow Gmail" | Gmail access was removed or your Google password changed. Click **Reconnect Gmail** and tick the read-your-email box (step 8, "Turn on Gmail sync"). |
| Settings shows "Off-site copy failed" | Read the message. If it ends in "reconnect Google in Settings", connect Google again with **Connect Google Docs** on the Essays page (step 8). |
