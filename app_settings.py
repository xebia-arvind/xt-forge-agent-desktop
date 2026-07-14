"""
Persistent app settings backed by QSettings.

Only stores non-secret values (backend URL, last email for prefill). Tokens go
through `auth_store.py` (OS keychain via `keyring`).
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

ORG = "XTForge"
APP = "XTForgeDesktop"


def _settings() -> QSettings:
    return QSettings(ORG, APP)


def get_backend_url() -> str:
    return str(_settings().value("backend_url", "") or "")


def set_backend_url(url: str) -> None:
    _settings().setValue("backend_url", url.rstrip("/"))


def get_last_email() -> str:
    return str(_settings().value("last_email", "") or "")


def set_last_email(email: str) -> None:
    _settings().setValue("last_email", email)


def clear_all() -> None:
    _settings().clear()
