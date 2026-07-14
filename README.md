# XT-Forge Desktop

PySide6 desktop client for the XT-Forge Django pipeline. Talks to the same backend the browser panel uses (`/test-analytics/*`, `/test-generation/*`, `/runners/*`, `/integrations/jira/*`, `/auth/login/`) via JWT-authenticated HTTP APIs. Cross-platform — ships as a `.dmg` on macOS and a `.exe` (Inno Setup) on Windows.

> **Are you an end user, not a developer?** See [**SETUP.md**](SETUP.md) for the install-and-first-launch walkthrough. The `.exe` bundles Python + PySide6 + Playwright's pip package; Chromium auto-downloads on first launch. No terminal commands needed.

## Scope (Phase 7)

Full parity with the Django Jobs dashboard + Execute panel. Sidebar order mirrors the browser: **Analytics → Jobs** (landing), **Workflow → Worklist**, **Pipeline → Feature → Manual Tests → Plan → Review → Execute**. Config, Generate, and Healer views are intentionally hidden — same as the Django panel post-Phase 6.4.

## Dev setup

```bash
cd desktop-app
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python main.py
```

First launch shows a setup screen — enter the backend URL (e.g. `http://127.0.0.1:8000`). Second launch skips setup and goes straight to login.

## Build installers locally

macOS (from a Mac):

```bash
cd desktop-app
pyinstaller packaging/pyinstaller_mac.spec
bash packaging/build_dmg.sh          # produces dist/XT-Forge.dmg
```

Windows (from Windows with Inno Setup 6 installed):

```bat
cd desktop-app
pyinstaller packaging\pyinstaller_win.spec
iscc packaging\installer.iss          :: produces dist\XT-Forge-Setup.exe
```

CI builds both automatically on push — see `.github/workflows/desktop-build.yml`.

## Repo layout

```
desktop-app/
├── main.py                # QApplication bootstrap
├── main_window.py         # MainWindow (sidebar + stacked panels)
├── api_client.py          # requests.Session with Bearer + 401-retry
├── app_settings.py        # QSettings wrapper (backend URL persistence)
├── auth_store.py          # keyring wrapper (JWT tokens)
├── panels/
│   ├── setup.py           # first-launch backend URL screen
│   ├── login.py           # email / password / workspace ID
│   ├── worklist.py        # Jira issues → Start pipeline
│   ├── feature.py         # Feature Author run/approve/reject
│   ├── manual_tests.py    # Manual Tests stage
│   ├── plan.py            # Plan stage
│   ├── review.py          # Artifacts review
│   └── execute.py         # Cucumber runner + live log tail (SSE)
├── workers/
│   └── sse_thread.py      # QThread streaming /runners/jobs/<id>/stream/
├── ui/style.qss           # Qt stylesheet (matches the browser panel look)
└── packaging/
    ├── pyinstaller_mac.spec
    ├── pyinstaller_win.spec
    ├── installer.iss      # Inno Setup script (Windows)
    └── build_dmg.sh       # create-dmg wrapper (macOS)
```
