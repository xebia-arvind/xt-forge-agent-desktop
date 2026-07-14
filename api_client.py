"""
HTTP client for the XT-Forge Django backend.

One `requests.Session` per app instance. JWT is cached in memory (mirrored to
the keychain via `auth_store` on login). Every non-login call goes through
`_authed_request`, which:
    1. attaches `Authorization: Bearer <access>`
    2. on 401 → re-logins using the stored credentials, retries once
    3. on second 401 → raises `AuthError` so the UI can bounce to the login screen

The backend has no /auth/refresh/ endpoint today; refresh = re-POST /auth/login/
with the cached (email, password, client_secret). We keep the password in RAM
only for as long as the session is alive.

Set env `XTFORGE_DEBUG=1` to print every request+response to stderr — handy
when a 401 shows up and you need to see the exact Bearer being sent.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

_DEBUG = os.environ.get("XTFORGE_DEBUG") == "1"


def _dlog(msg: str) -> None:
    if _DEBUG:
        print(f"[api_client] {msg}", file=sys.stderr, flush=True)


class APIError(RuntimeError):
    """Non-2xx response the caller should surface as a toast/dialog."""

    def __init__(self, status: int, detail: str, url: str = ""):
        super().__init__(f"HTTP {status} — {detail[:200]} ({url})")
        self.status = status
        self.detail = detail
        self.url = url


class AuthError(APIError):
    """Raised when the backend rejects our credentials — UI should show login."""


@dataclass
class Session:
    email: str = ""
    client_name: str = ""
    client_secret: str = ""
    access: str = ""
    refresh: str = ""
    # Password stays in RAM only. Cleared on logout.
    _password: str = field(default="", repr=False)


class APIClient:
    """
    Wraps `requests.Session` with a JWT-aware `_authed_request`.

    Construct with the backend URL (e.g. `http://127.0.0.1:8000`). Call
    `login(...)` before hitting any protected endpoint. Every method that talks
    to a protected endpoint raises `APIError` on non-2xx or `AuthError` if the
    server rejects the token after a refresh attempt.
    """

    def __init__(self, backend_url: str, timeout: float = 20.0):
        self.backend_url = backend_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.state = Session()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def login(self, email: str, password: str, client_secret: str) -> Dict[str, Any]:
        """POST /auth/login/. Populates in-memory state on success."""
        url = self._url("/auth/login/")
        try:
            resp = self.session.post(
                url,
                json={"email": email, "password": password, "client_secret": client_secret},
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise APIError(0, f"Could not reach {url}: {exc}", url) from exc

        if resp.status_code != 200:
            raise AuthError(resp.status_code, resp.text, url)

        try:
            body = resp.json()
        except ValueError:
            raise AuthError(resp.status_code, "Login response was not JSON", url)

        tokens = body.get("tokens") or {}
        access = tokens.get("access") or ""
        if not access:
            raise AuthError(500, "Login response missing tokens.access", url)

        self.state = Session(
            email=email,
            client_name=(body.get("client") or {}).get("name", "") or "",
            client_secret=client_secret,
            access=access,
            refresh=tokens.get("refresh") or "",
            _password=password,
        )
        return body

    def restore_session(self, access: str, refresh: str, email: str, client_secret: str, client_name: str) -> None:
        """Rehydrate from the keychain — no network call. Password stays empty."""
        self.state = Session(
            email=email,
            client_name=client_name,
            client_secret=client_secret,
            access=access,
            refresh=refresh,
            _password="",
        )

    def logout(self) -> None:
        self.state = Session()

    def is_logged_in(self) -> bool:
        return bool(self.state.access)

    # ------------------------------------------------------------------
    # Protected calls
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        # `urljoin` mangles absolute paths — do it by hand.
        return f"{self.backend_url}{path if path.startswith('/') else '/' + path}"

    def _refresh_token(self) -> None:
        """
        No /auth/refresh/ endpoint on the server today, so we re-POST /auth/login/
        using the cached in-memory password. If the password isn't available
        (restored from keychain with no re-login yet), raise AuthError.
        """
        if not self.state._password:
            raise AuthError(401, "Session expired and no password cached — re-login required")
        self.login(self.state.email, self.state._password, self.state.client_secret)

    def _authed_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        url = self._url(path)

        def _send() -> requests.Response:
            token_preview = (self.state.access[:12] + "…" + self.state.access[-6:]) if self.state.access else "<empty>"
            _dlog(f"→ {method} {url}  Bearer={token_preview}  body={json_body!r}")
            headers = {"Authorization": f"Bearer {self.state.access}"}
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            r = self.session.request(
                method,
                url,
                json=json_body,
                params=params,
                headers=headers,
                stream=stream,
                timeout=timeout if timeout is not None else self.timeout,
            )
            _dlog(f"← {r.status_code} {r.headers.get('content-type', '')}  body={r.text[:200]!r}")
            return r

        if not self.state.access:
            raise AuthError(401, "Not logged in", url)

        try:
            resp = _send()
        except requests.RequestException as exc:
            raise APIError(0, f"Network error: {exc}", url) from exc

        if resp.status_code == 401:
            # First 401 — try one refresh + retry. If refresh has no password
            # cached (cold cookie hydrate), surface immediately.
            body_before = resp.text[:400]
            try:
                self._refresh_token()
            except AuthError:
                raise
            try:
                resp = _send()
            except requests.RequestException as exc:
                raise APIError(0, f"Network error on retry: {exc}", url) from exc
            if resp.status_code == 401:
                # Include the server's actual detail so 'client_secret mismatch'
                # vs 'invalid token' vs 'no user' is diagnosable in the UI.
                raise AuthError(
                    401,
                    f"Backend still rejected after refresh. "
                    f"Server said: {resp.text[:300]!r}. "
                    f"Pre-refresh body: {body_before!r}",
                    url,
                )

        return resp

    def _json(self, resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def _raise_if_bad(self, resp: requests.Response) -> None:
        if resp.status_code >= 400:
            raise APIError(resp.status_code, resp.text, resp.url)

    # ------------------------------------------------------------------
    # Jira
    # ------------------------------------------------------------------
    def jira_connection(self) -> Dict[str, Any]:
        resp = self._authed_request("GET", "/integrations/jira/connection/")
        self._raise_if_bad(resp)
        return self._json(resp)

    def jira_search(self, jql: str, max_results: int = 25) -> Dict[str, Any]:
        resp = self._authed_request(
            "POST",
            "/integrations/jira/search/",
            json_body={"jql": jql, "max_results": max_results},
        )
        self._raise_if_bad(resp)
        return self._json(resp)

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------
    def start_pipeline(
        self,
        jira_issue_key: str,
        feature_name: str = "",
        base_url: str = "",
        seed_urls: Optional[list] = None,
    ) -> Dict[str, Any]:
        body = {
            "jira_issue_key": jira_issue_key,
            "feature_name": feature_name or jira_issue_key,
        }
        if base_url:
            body["base_url"] = base_url
        if seed_urls:
            body["seed_urls"] = seed_urls
        resp = self._authed_request(
            "POST",
            "/test-generation/pipeline-jobs/",
            json_body=body,
        )
        self._raise_if_bad(resp)
        return self._json(resp)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        resp = self._authed_request("GET", f"/test-generation/jobs/{job_id}/")
        self._raise_if_bad(resp)
        return self._json(resp)

    def list_jobs(self) -> list:
        """
        GET /test-generation/jobs/ — returns the Jobs-dashboard row set
        for the active tenant. Phase 6.5.1 excludes STAGE_INTAKE stubs
        server-side, so the desktop gets the same clean list as the
        browser panel with zero extra filtering.

        Each row is a lightweight dict (job_id, feature_name, status,
        stage, jira_issue_key, created_on). For richer per-job detail
        (stage_execute_output, execute_iteration) call `get_job(id)`.
        """
        resp = self._authed_request("GET", "/test-generation/jobs/")
        self._raise_if_bad(resp)
        data = self._json(resp)
        # Endpoint returns a JSON array; guard against unexpected shapes.
        return data if isinstance(data, list) else []

    STAGES = ("feature", "manual-tests", "plan", "artifacts", "execute")

    def run_stage(self, job_id: str, stage: str, body: Optional[dict] = None) -> Dict[str, Any]:
        if stage not in self.STAGES:
            raise ValueError(f"Unknown stage: {stage}")
        resp = self._authed_request(
            "POST",
            f"/test-generation/jobs/{job_id}/stage/{stage}/run/",
            json_body=body or {},
            # Agent stages can take a while; give them more room than the default.
            timeout=180.0,
        )
        self._raise_if_bad(resp)
        return self._json(resp)

    def approve_stage(self, job_id: str, stage: str, body: Optional[dict] = None) -> Dict[str, Any]:
        if stage not in self.STAGES:
            raise ValueError(f"Unknown stage: {stage}")
        resp = self._authed_request(
            "POST",
            f"/test-generation/jobs/{job_id}/stage/{stage}/approve/",
            json_body=body or {},
        )
        self._raise_if_bad(resp)
        return self._json(resp)

    # ------------------------------------------------------------------
    # Runner log stream helper
    # ------------------------------------------------------------------
    def runner_stream_url(self, runner_job_id: int) -> str:
        return self._url(f"/runners/jobs/{runner_job_id}/stream/")

    def bearer_header(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.state.access}"} if self.state.access else {}
