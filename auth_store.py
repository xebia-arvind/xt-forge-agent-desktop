"""
JWT token storage via the OS keychain.

Uses `keyring` — on macOS this is Keychain, on Windows the Credential Manager.
Falls back to a plaintext file under `QStandardPaths.AppDataLocation` when the
keyring backend is not available (e.g. some Linux CI environments).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import keyring
from PySide6.QtCore import QStandardPaths

SERVICE = "XTForgeDesktop"
_KEY_ACCESS = "access_token"
_KEY_REFRESH = "refresh_token"
_KEY_META = "session_meta"  # JSON blob: email, client_name, client_secret


def _fallback_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base:
        base = str(Path.home() / ".xtforge-desktop")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p / "session.json"


def _fallback_read() -> dict:
    fp = _fallback_path()
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fallback_write(data: dict) -> None:
    fp = _fallback_path()
    try:
        fp.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(fp, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def _kr_set(key: str, value: str) -> bool:
    try:
        keyring.set_password(SERVICE, key, value)
        return True
    except Exception:
        return False


def _kr_get(key: str) -> Optional[str]:
    try:
        return keyring.get_password(SERVICE, key)
    except Exception:
        return None


def _kr_del(key: str) -> None:
    try:
        keyring.delete_password(SERVICE, key)
    except Exception:
        pass


def save_session(access: str, refresh: str, email: str, client_name: str, client_secret: str = "") -> None:
    # Phase 18 — client_secret is now optional. Desktop users log in with
    # email+password only; the JWT (access/refresh) carries client_id, so a
    # stored secret is no longer required for the session to work.
    meta = json.dumps({"email": email, "client_name": client_name, "client_secret": client_secret})
    ok = _kr_set(_KEY_ACCESS, access) and _kr_set(_KEY_REFRESH, refresh) and _kr_set(_KEY_META, meta)
    if not ok:
        _fallback_write({
            _KEY_ACCESS: access,
            _KEY_REFRESH: refresh,
            _KEY_META: {"email": email, "client_name": client_name, "client_secret": client_secret},
        })


def load_session() -> Optional[dict]:
    access = _kr_get(_KEY_ACCESS)
    refresh = _kr_get(_KEY_REFRESH)
    meta_raw = _kr_get(_KEY_META)
    if access and meta_raw:
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}
        return {
            "access": access,
            "refresh": refresh or "",
            "email": meta.get("email", ""),
            "client_name": meta.get("client_name", ""),
            "client_secret": meta.get("client_secret", ""),
        }
    # Fallback file
    data = _fallback_read()
    if not data.get(_KEY_ACCESS):
        return None
    meta = data.get(_KEY_META) or {}
    return {
        "access": data.get(_KEY_ACCESS, ""),
        "refresh": data.get(_KEY_REFRESH, ""),
        "email": meta.get("email", ""),
        "client_name": meta.get("client_name", ""),
        "client_secret": meta.get("client_secret", ""),
    }


def clear_session() -> None:
    for k in (_KEY_ACCESS, _KEY_REFRESH, _KEY_META):
        _kr_del(k)
    fp = _fallback_path()
    if fp.exists():
        try:
            fp.unlink()
        except OSError:
            pass
