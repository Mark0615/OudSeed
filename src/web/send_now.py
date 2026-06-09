"""Backwards-compatible re-export.

The send orchestration moved to :mod:`src.ai.workspace_reports` so the scheduled
dispatcher and the web button can share it without the web package depending on
the AI layer. Existing imports of ``src.web.send_now`` keep working.
"""

from __future__ import annotations

from src.ai.workspace_reports import (
    SendNowResult,
    build_workspace_report_config,
    send_workspace_reports_now,
)

__all__ = [
    "SendNowResult",
    "build_workspace_report_config",
    "send_workspace_reports_now",
]
