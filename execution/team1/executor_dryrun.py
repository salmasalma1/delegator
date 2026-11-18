# Adapted from the Team 1 executor, with their permission. All changes are marked CHANGED(team2).
"""An executor that records what it would do and touches nothing. Used until the desktop executor (Sprint B)."""
from __future__ import annotations

import threading
from typing import Any, Callable

from contracts import ActionResult, ToolCall  # CHANGED(team2): Team 1's installed contracts package, not ..contracts
from . import apps  # CHANGED(team2): local shim, for the same no_application / unknown_app refusals as the desktop one


class DryRunExecutor:
    """results: 1-based call index -> forced status ('error' / 'blocked'), to test failure paths.
    on_execute(call, index): test hook that runs while the action 'happens' (press stop, simulate a crash)."""

    def __init__(self, results: dict[int, str] | None = None,
                 on_execute: Callable[[ToolCall, int], None] | None = None):
        self.results = results or {}
        self.on_execute = on_execute
        self.calls: list[ToolCall] = []
        self.apps: list[str | None] = []
        self.released = 0

    def execute(self, call: ToolCall, *, observation: dict[str, Any] | None, stop: threading.Event,
                app: str | None = None) -> ActionResult:
        before = observation["screenshot_id"] if observation else None
        if stop.is_set():
            return ActionResult(call_id=call.call_id, status="skipped", tool=call.tool, before_id=before,
                                error="stopped before any input was sent")
        # CHANGED(team2): refuse what the desktop executor refuses before it looks at the screen, so a dry run
        # shows the same refusals as a live run would
        refusal = None
        if call.tool not in ("open_app", "wait"):
            if not app:
                refusal = f"no_application: {call.tool} needs an application; none was given"
            elif not apps.processes_for(app):
                refusal = f"unknown_app: {app!r} is not a known application ({', '.join(apps.PROCESSES)})"
        if refusal:  # CHANGED(team2)
            return ActionResult(call_id=call.call_id, status="blocked", tool=call.tool, before_id=before,
                                target_element_id=call.target_element_id, error=refusal)
        self.calls.append(call)
        self.apps.append(app)
        index = len(self.calls)
        if self.on_execute:
            self.on_execute(call, index)
        status = self.results.get(index, "ok")
        error = None if status == "ok" else ("stale: observation too old (dry-run)" if status == "blocked"
                                             else f"dry-run forced {status}")
        return ActionResult(call_id=call.call_id, status=status, tool=call.tool, before_id=before,
                            target_element_id=call.target_element_id, error=error)

    def release_all(self) -> None:
        self.released += 1
