# Changes to the Team 1 executor (made by Team 2)

`execution/team1/executor_desktop.py` and `executor_dryrun.py` are adapted from the Team 1 executor, with Team 1's permission. Every edit is marked in the code with `# CHANGED(team2): <why>`, so it can be found with:

```
grep -n "CHANGED(team2)" execution/team1/*.py
```

The first commit on the branch (`execution/team1: add Team 1 desktop and dry-run executors, unmodified`) holds the files exactly as received, so `git diff <that commit> -- execution/team1/` shows every change. Line numbers below refer to the adapted files.

## executor_desktop.py

| Line(s) | Change | Why |
|---|---|---|
| 1 | Header comment | Marks the file as adapted, with permission. |
| 14 | `import os` | Needed to read `NELLY_LIVE_INPUT` / `NELLY_DRY_RUN`. |
| 19 | `from .. import apps` → `from . import apps` | Delegator has no parent `apps` package; uses the local shim `execution/team1/apps.py`. |
| 20 | `from ..contracts import …` → `from contracts import …` | Uses Team 1's installed `contracts` package (on the path through the `.pth` file). The shim is deliberately not called `contracts`, so it can't shadow yours. |
| 21 | `from ..vision_path import …` → `from .vision_path import …` | Local shim; a no-op, because Team 1's package is already importable. |
| 26 | `FOCUS_CODES = ("focus_guard", "focus_changed")` | These are reported as `wrong_window`, our reject code (see line 105). |
| 29–31 | `live_requested()` | Real input only when `NELLY_LIVE_INPUT=1` and `NELLY_DRY_RUN` is not set (same rule as our interim executor). |
| 59–62 | `fake_backends_live` argument, `self._fakes_live` | Test-only opt-in: lets tests run the input logic on **injected fake** window and input backends without `NELLY_LIVE_INPUT`. It is ignored unless both backends are injected, so the real backends always need `NELLY_LIVE_INPUT=1`. |
| 78 | `sent, done` flags | Track whether input may have been sent and whether it finished, for the `finally` block. |
| 81–82 | Dry-run gate at the top of `execute()` | Dry run by default. Without live input every tool except `wait` is refused as `dry_run` before anything is touched (no launch, no focus change, no input). |
| 91–92 | Refuse when no application is given (`no_application`) | Before, with `app=None`, any unprotected window in front received the click or keys. |
| 93–94 | Refuse when the application is unknown (`unknown_app`) | An unknown name gave an empty process set and fell into the same "any unprotected window" path. |
| 99, 101 | `sent = True` / `done = True` around `_act()` | See `finally` (line 116). |
| 105–106 | `focus_guard` / `focus_changed` → `blocked` with error `wrong_window: <original code>: <detail>` | Our reject code is `wrong_window`; the original code stays in the detail text. |
| 111–115 | `except Exception` | Before, only `Blocked` and `Stopped` were caught. Now every exception becomes a result: pyautogui's `FailSafeException` (mouse in a corner) → `skipped` ("stopped by the user"), anything else → `error` with the exception type and message. |
| 116–118 | `finally`: release modifiers if input was interrupted | Ctrl/Shift/Alt/Win must never stay held after an error, stop or refusal in the middle of input. Not done after a normal finish, so no extra key-ups are sent. |
| 120–121 | `_live()` | `NELLY_LIVE_INPUT=1`, or the test-only fake-backend opt-in. |
| 123–128 | `_release_modifiers()` | Calls `inputs.release_modifiers()` (falls back to `release_all()`), never raises. |
| 297–299 | `Win32Windows.activate()` docstring | Updated: the Alt-tap fallback is gone. |
| 321–323 | Removed the Alt key-tap fallback (`keybd_event(0x12, …)` down/up, then `SetForegroundWindow`) | That Alt key went to whatever window was in front. Only AttachThreadInput + SetForegroundWindow remain; if the window does not come forward, `activate()` returns False and the focus guard refuses (`wrong_window: focus_guard: …`). |
| 507–508 | `PyAutoGuiInput.release_modifiers()` | Key-ups for Ctrl/Shift/Alt/Win only, no mouse events (`release_all()` also sends mouse-ups). |

## executor_dryrun.py

| Line(s) | Change | Why |
|---|---|---|
| 1 | Header comment | Marks the file as adapted, with permission. |
| 8 | `from ..contracts import …` → `from contracts import …` | Team 1's installed `contracts` package. |
| 9 | `from . import apps` | Needed for the refusals below. |
| 30–40 | Refuse `no_application` / `unknown_app` for every tool except `open_app` and `wait` | A dry run shows the same refusals as a live run, so tests catch them without real input. |

## New files (Team 2, not from Team 1)

- `execution/team1/apps.py`: shim for your `apps` module:
  - `app_key`, `processes_for`, `LAUNCH`, `LAUNCH_ARGS`, `PROCESSES`, and one editable `PROTECTED_PROCESSES` set.
  - `LAUNCH` holds only notepad, explorer and calculator (the same as our interim executor).
  - On Windows 10, the Calculator window belongs to `applicationframehost.exe`, which is not listed, so input to Calculator is refused there.
- `execution/team1/vision_path.py`: `ensure_vision_on_path()` returns None.
- `execution/team1/__init__.py`: package marker.
- `execution/team1_bridge.py` (outside this folder): translates our request and result format to your `ToolCall` / `ActionResult`.

## Not changed

- The focus guard logic itself:
  - process check
  - bring-to-front and re-check
  - `_still_in_front()` before every batch of input
  - protected-process refusal
  - pointer actions require the observation to come from the same app
- Point resolution through `CoordinateManager.resolve_target_point()` and your rejection codes (`stale`, `window_resized`, `off_screen`, …).
- The stop token checks, the 200-character typing chunks, and the `Stopped` → `skipped` path with `release_all()`.
- `open_app` launching, the retry-within-60 s behaviour and the launch timeout.
- `SendInputKeyboard` (Unicode typing, chords, timings), clipboard paste with restore, `copy_element_text`, scroll.
- pyautogui is still imported lazily (only when `PyAutoGuiInput` is created); `FAILSAFE` stays on.
- `DryRunExecutor`'s recording, forced results and `on_execute` hook.
- `ActionResult` / `ToolCall` themselves (yours, unchanged).
