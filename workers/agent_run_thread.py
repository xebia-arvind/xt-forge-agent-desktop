"""
Background QThread that runs a single LLM agent stage (Feature / Manual /
Plan / Artifact) via the sync HTTP client without blocking the Qt event loop.

Phase 12.3 — previously, `_stage_base.py::_run` called `api.run_stage(...)`
directly on the UI thread. Because the underlying `requests` call blocks for
the full 30-120 s LLM response, the Qt event loop was frozen and any
inline spinner never animated. Moving the call here lets Qt keep pumping
paint events → the QProgressBar in the panel animates while the LLM runs.

Mirrors the pattern in `workers/sse_thread.py`: signals for succeeded /
failed, the thread owns its API handle, exceptions never leak to the UI
thread.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QThread, Signal

from api_client import APIClient, APIError


class AgentRunThread(QThread):
    """
    Run one `api.run_stage(job_id, stage_key)` call off the main thread.

    Signals:
        succeeded(object)  — the raw response dict from the backend
        failed(str)        — human-readable error message; already truncated

    The caller is responsible for keeping a reference to the thread alive
    until `finished` fires (Qt cleans up threads that get garbage-collected
    mid-run with a hard crash — see `_stage_base._agent_thread`).
    """

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        api: APIClient,
        job_id: str,
        stage_key: str,
        body: Optional[dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.api = api
        self.job_id = job_id
        self.stage_key = stage_key
        self.body = body

    def run(self) -> None:
        try:
            result = self.api.run_stage(self.job_id, self.stage_key, self.body)
            self.succeeded.emit(result)
        except APIError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — never propagate to UI thread
            self.failed.emit(f"Unexpected error: {exc}")
