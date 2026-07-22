# XT-Forge Desktop — macOS Install & First-Launch Guide

This guide is for QA engineers who want to run the XT-Forge pipeline from a
native desktop app on macOS. Everything the desktop app needs is bundled
inside the `.dmg` — you do **not** need Python, Node, Playwright, or any
developer tools installed on your Mac.

Windows users: see [SETUP.md](SETUP.md) instead.

## What is XT-Forge Desktop?

A native macOS front-end for the XT-Forge test-automation pipeline. It
mirrors the browser panel at `http://<your-django-backend>/test-analytics/`
so you can view the Jobs dashboard, monitor Execute runs, and push reports
to Jira without opening a browser tab.

Under the hood it's a small PySide6 app that talks to your XT-Forge Django
backend over HTTPS. It's not a standalone testing framework — it's a client
that surfaces what the backend already knows.

## System requirements

| Requirement       | Minimum                                                |
| ----------------- | ------------------------------------------------------ |
| Operating system  | macOS 12 Monterey (or newer)                           |
| Architecture      | **Apple Silicon** — M1, M2, M3, M4                     |
| Disk space        | ~500 MB (250 MB app + ~150 MB Playwright browsers)     |
| RAM               | 4 GB                                                   |
| Network           | HTTPS access to your XT-Forge Django backend           |
| Prerequisites     | **None** — Python is bundled inside the `.app`         |

Intel Macs are not supported in this release. If you're on an Intel Mac,
clone the repo and run the app from source instead (see the developer
README).

## Install steps

1. **Download** `XT-Forge.dmg` from your release channel (GitHub Actions
   `XT-Forge-macos` artifact, internal share drive, etc.).
2. **Double-click** the `.dmg` in Finder. A window opens with the
   `XT-Forge.app` icon and an `Applications` folder shortcut.
3. **Drag** `XT-Forge.app` onto the `Applications` shortcut.
4. **Eject** the `.dmg` (right-click the mounted volume in Finder → Eject).

## First launch — the Gatekeeper bypass

The `.app` is **not code-signed** with an Apple Developer certificate.
macOS Gatekeeper will refuse to open it on the first try with:

> "XT-Forge" can't be opened because Apple cannot check it for malicious software.

To bypass this **once** per install:

1. Open **Finder → Applications**.
2. **Right-click** `XT-Forge.app` → choose **Open**.
3. macOS shows a new dialog with an **Open** button (in addition to Cancel).
4. Click **Open**.

Subsequent launches use the normal double-click flow — you only do this
once per install.

### Alternate command-line bypass

If you know what you're doing and have Terminal open:

```bash
xattr -dr com.apple.quarantine /Applications/XT-Forge.app
```

Then double-click as normal. Same effect.

## First run — one-time bootstrap (~1 minute)

The first launch downloads the Playwright Chromium browser (~150 MB) into
`~/Library/Caches/ms-playwright/`. A modal progress dialog shows the
status. Subsequent launches skip this step.

After the bootstrap finishes:

1. The **Setup** screen asks for a backend URL. Enter your Django backend, e.g.:
   - `http://127.0.0.1:8000` (local dev — only when Django runs on your Mac)
   - `http://<server-ip>:8000` (Django on the LAN)
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

| Symptom                                                             | Likely cause + fix |
| ------------------------------------------------------------------- | ------------------ |
| `"XT-Forge" can't be opened because Apple cannot check it…`         | Expected on first launch. Right-click → Open (see above). |
| `"XT-Forge" is damaged and can't be opened.` after right-click Open | Extended quarantine attribute. Run `xattr -dr com.apple.quarantine /Applications/XT-Forge.app` in Terminal. |
| Playwright install progress dialog fails                            | Check network, then in Terminal: `python3 -m pip install playwright && python3 -m playwright install chromium`. Relaunch the app — it detects the existing install. |
| "Cannot connect to backend" on Setup screen                         | Wrong URL, firewall, corp proxy, or VPN not connected. Verify by opening the URL in Safari first. |
| "Login failed" on Login screen                                      | Your Django admin hasn't created a user for you, OR the workspace secret is wrong. Ask your admin. |
| App won't launch (silent fail)                                      | Open `~/Library/Logs/XT-Forge/desktop-debug.log` for a traceback. Also check Console.app for `com.xtforge.desktop` entries. |
| App is slow                                                         | Backend issue, not desktop. Check the backend health at `<backend-url>/admin/`. |

## Where files live

| Path                                                    | What's there                           |
| ------------------------------------------------------- | -------------------------------------- |
| `/Applications/XT-Forge.app`                            | App bundle                             |
| `~/Library/Preferences/com.xtforge.desktop.plist`       | QSettings (backend URL, bootstrap flag)|
| `~/Library/Logs/XT-Forge/desktop-debug.log`             | App log (attach to bug reports)        |
| `~/Library/Caches/ms-playwright/chromium-*/`            | Playwright Chromium (~150 MB)          |
| macOS Keychain (`XTForgeDesktop-*` entries)             | JWT session tokens (auto-managed)      |

## Updating

1. Quit XT-Forge (`Cmd+Q`).
2. Drag `XT-Forge.app` out of `/Applications` to the Trash.
3. Download the new `XT-Forge.dmg` and re-install from step 1.
4. Right-click → Open again (Gatekeeper resets on every replacement `.app`).
5. Your backend URL, bootstrap flag, and last email persist across upgrades —
   you don't need to re-enter them. The bootstrap is skipped because
   `~/Library/Caches/ms-playwright/` already has Chromium.

## Uninstall

1. Drag `/Applications/XT-Forge.app` to the Trash.
2. Optional — wipe cached files:
   ```bash
   rm -rf ~/Library/Caches/ms-playwright/
   rm -f  ~/Library/Preferences/com.xtforge.desktop.plist
   rm -rf ~/Library/Logs/XT-Forge/
   ```
3. Optional — remove Keychain entries: open Keychain Access, search for
   `XTForgeDesktop-`, delete matches.

## Bug reports

Attach these three things to a bug report:

1. `~/Library/Logs/XT-Forge/desktop-debug.log`
2. Your backend version (visible in the browser panel's footer at
   `<backend-url>/test-analytics/`)
3. A screenshot of the failure

## Not signing? Should I be worried?

The `.app` is not signed with an Apple Developer certificate ($99/yr). The
Gatekeeper "unidentified developer" warning is expected. The `.app` is
safe if it came from a trusted source — you can verify by comparing its
SHA-256 hash against the release notes. Signing + notarization is tracked
as a future improvement, not a shipping blocker for internal use.

## For developers — regenerating the app icon

The Finder + Dock icon is `desktop-app/ui/xt-forge.icns`, generated once
from `xt-forge.ico` and committed to the repo. Regenerate only when the
icon design changes:

```bash
brew install imagemagick   # if you don't have it
mkdir -p /tmp/xt-forge.iconset
for size in 16 32 128 256 512; do
  magick desktop-app/ui/xt-forge.ico -resize ${size}x${size} \
    /tmp/xt-forge.iconset/icon_${size}x${size}.png
done
magick desktop-app/ui/xt-forge.ico -resize 32x32     /tmp/xt-forge.iconset/icon_16x16@2x.png
magick desktop-app/ui/xt-forge.ico -resize 64x64     /tmp/xt-forge.iconset/icon_32x32@2x.png
magick desktop-app/ui/xt-forge.ico -resize 256x256   /tmp/xt-forge.iconset/icon_128x128@2x.png
magick desktop-app/ui/xt-forge.ico -resize 1024x1024 /tmp/xt-forge.iconset/icon_512x512@2x.png
iconutil -c icns /tmp/xt-forge.iconset -o desktop-app/ui/xt-forge.icns
```

Commit the resulting `xt-forge.icns` and re-push — CI picks it up.
