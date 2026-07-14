# XT-Forge Desktop — Install & First-Launch Guide

This guide is for QA engineers who want to run the XT-Forge pipeline from a
native desktop app instead of the browser panel. Everything the desktop app
needs is bundled inside the installer — you do **not** need Python, Node,
Playwright, or any developer tools installed on your machine.

## What is XT-Forge Desktop?

A Windows-native front-end for the XT-Forge test-automation pipeline. It
mirrors the browser panel at `http://<your-django-backend>/test-analytics/`
so you can view the Jobs dashboard, monitor Execute runs, and push reports
to Jira without opening a browser tab.

Under the hood it's a small PySide6 app that talks to your XT-Forge Django
backend over HTTPS. It's not a standalone testing framework — it's a client
that surfaces what the backend already knows.

## System requirements

| Requirement       | Minimum                                        |
| ----------------- | ---------------------------------------------- |
| Operating system  | Windows 10 (build 1809) or Windows 11 — 64-bit |
| Disk space        | ~250 MB                                        |
| RAM               | 4 GB                                           |
| Network           | HTTPS access to your XT-Forge Django backend   |
| Prerequisites     | **None** — Python is bundled inside the `.exe` |

Not required:

- Python / PySide6 / Qt — bundled inside the installer
- Playwright / Chromium / Node.js — the desktop is a thin HTTP client;
  browsers are used server-side by the Django backend, never on the
  operator's machine. Tests run wherever qcluster runs.

## Install steps

1. **Download** `XT-Forge-Setup.exe` from your release channel (GitHub Releases,
   internal share drive, etc.).
2. **Double-click** the installer.
3. **Accept the "Unverified publisher" prompt.**
   - Click **More info**, then **Run anyway**.
   - This is expected — the installer isn't code-signed with a paid
     certificate. It is safe if you got the file from a trusted source.
4. Follow the wizard: default install path is `C:\Program Files\XT-Forge`
   (or `%LOCALAPPDATA%\Programs\XT-Forge` when you're not admin).
5. Leave **"Create a desktop icon"** checked if you want one.
6. Click **Install**. The wizard finishes in ~30 seconds.
7. Leave **"Launch XT-Forge"** checked and click **Finish**.

## First launch

1. The **Setup** screen asks for a backend URL. Enter your Django backend, e.g.:
   - `http://127.0.0.1:8000` (local dev — only when Django runs on the same box)
   - `http://<your-server-ip>:8000` (Django on the LAN)
   - `https://xt-forge.your-company.com` (production)
2. Click **Continue**. The app tests the connection and remembers the URL.
3. **Login screen**: enter your email, password, and workspace secret. Your
   admin provisions these in Django admin (`/admin/clients/users/`).
4. Click **Sign in**. On success, you land on the **Jobs Dashboard** — the
   same view as `http://<backend>/test-analytics/jobs/` in the browser.

## Daily use

- **📈 Jobs (landing page)** — every pipeline job with stage-progression
  pills, filters, and actions. Click **▶ Run smoke** on a green job for a
  fast regression check, or **🚀 Push** to send the report to Jira.
- **🗂 Worklist** — Jira ticket search. Start a new pipeline from a ticket.
- **🧬 Feature → ▶ Execute** — the six-stage pipeline. Same flow as browser.

The sidebar layout matches the browser panel exactly. If you know your
way around the browser UI you already know your way around this one.

## Troubleshooting

| Symptom                                       | Likely cause + fix |
| --------------------------------------------- | ------------------ |
| "Unverified publisher" warning on install     | Expected — the installer isn't code-signed. Click **More info** → **Run anyway**. Safe if you got the `.exe` from a trusted source. |
| "Cannot connect to backend" on Setup screen   | Wrong URL, firewall, or VPN not connected. Verify by opening the URL in a browser first. |
| "Login failed" on Login screen                | Your Django admin hasn't created a user for you, OR the workspace secret is wrong. Ask your admin. |
| App won't start after install                 | Check `%USERPROFILE%\AppData\Local\XT-Forge\logs\desktop-debug.log` for a traceback. Common cause: Windows Defender / EDR flagging PyInstaller-bundled `.exe`. Add an exception for `%LOCALAPPDATA%\Programs\XT-Forge\` in your antivirus. |
| Job listing is empty                          | The backend may have zero jobs beyond STAGE_INTAKE — the desktop follows the same Phase 6.5.1 filter as the browser (hides intake stubs). Start a fresh pipeline from Worklist. |
| Slow response times                           | Backend issue, not desktop. Check the backend health at `<backend-url>/admin/`. |

## Where files live

| Path                                                    | What's there                           |
| ------------------------------------------------------- | -------------------------------------- |
| `%LOCALAPPDATA%\Programs\XT-Forge\`                     | App binary + PyInstaller bundle        |
| `%APPDATA%\XTForge\XTForgeDesktop\`                     | QSettings (backend URL, last email)    |
| `%LOCALAPPDATA%\XT-Forge\logs\desktop-debug.log`        | App log (open this when reporting bugs)|
| Windows Credential Manager (`XTForgeDesktop-*`)         | JWT session tokens (auto-managed)      |

## Updating

1. Uninstall the old version: **Settings → Apps → XT-Forge → Uninstall**.
2. Download the new `XT-Forge-Setup.exe` and re-install.
3. Your backend URL and last email persist across upgrades — you don't
   need to re-enter them.

## Uninstall

1. **Settings → Apps → XT-Forge → Uninstall** removes the app binary.
2. To wipe saved credentials, delete the `XTForgeDesktop-*` entries in
   Windows Credential Manager.

## Bug reports

Attach these three things to a bug report:

1. `%LOCALAPPDATA%\XT-Forge\logs\desktop-debug.log`
2. Your backend version (visible in the browser panel's footer)
3. A screenshot of the failure

## Not signing? Should I be worried?

The installer is not code-signed with a paid Authenticode certificate. The
Windows SmartScreen "Unverified publisher" warning is expected. The `.exe`
is safe if it came from a trusted source — you can verify by comparing its
SHA-256 hash against the release notes. Signing costs $100-400/year and is
tracked as a future improvement, not a shipping blocker for internal use.
