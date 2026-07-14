"""
Background QThread that streams Server-Sent Events from the Django runner.

The `/runners/jobs/<id>/stream/` endpoint emits frames like:

    event: log
    data: <one line of playwright output>

    event: done
    data: {"state": "SUCCEEDED", "returncode": 0}

We parse those frames with a tiny state machine and emit two Qt signals so
the Execute panel can append log lines to a text widget without blocking the
UI thread.
"""
from __future__ import annotations

import json
from typing import Dict, Optional

import httpx
from PySide6.QtCore import QThread, Signal


class SSELogThread(QThread):
    line = Signal(str)          # one log line
    done = Signal(dict)         # {"state": "...", "returncode": int}
    error = Signal(str)         # human-readable message

    def __init__(self, stream_url: str, auth_header: Dict[str, str], parent=None):
        super().__init__(parent)
        self.stream_url = stream_url
        self.auth_header = dict(auth_header)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: C901 (state machine)
        headers = {"Accept": "text/event-stream", **self.auth_header}
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("GET", self.stream_url, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = resp.read().decode("utf-8", errors="replace")
                        self.error.emit(f"Stream failed HTTP {resp.status_code}: {body[:300]}")
                        return

                    current_event: Optional[str] = None
                    for raw in resp.iter_lines():
                        if self._stop:
                            return
                        # httpx.iter_lines returns str already-decoded.
                        line = raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")
                        if line == "":
                            # Blank line = end of an event. Reset.
                            current_event = None
                            continue
                        if line.startswith(":"):
                            # comment / keep-alive
                            continue
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                            continue
                        if line.startswith("data:"):
                            payload = line[5:].lstrip()
                            if current_event == "log":
                                self.line.emit(payload)
                            elif current_event == "done":
                                try:
                                    self.done.emit(json.loads(payload))
                                except json.JSONDecodeError:
                                    self.done.emit({"raw": payload})
                                return
        except httpx.HTTPError as exc:
            self.error.emit(f"Stream error: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"Unexpected error: {exc}")
