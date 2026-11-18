"""The desktop executor: the only code that moves the mouse or presses keys.

Safety rules, in order, before any input:
1. the stop token is checked before every input event, and release_all() lets go of every held key / button;
2. focus guard: keyboard and mouse go only to the step's app (by process name). If another window is in front, the
   executor brings the app forward and checks again; it never types into a protected window (Claude, terminals);
3. pointer targets: the observation must show that same app, and Team 1's CoordinateManager.resolve_target_point()
   turns the element into a checked physical point (stale / moved / resized / off-screen -> 'blocked');
4. PyAutoGUI's fail-safe stays on: moving the mouse into a screen corner aborts the action.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Protocol

from .. import apps
from ..contracts import ActionResult, ToolCall
from ..vision_path import ensure_vision_on_path

POINTER = {"click_element": "left", "double_click_element": "double", "right_click_element": "right",
           "triple_click_element": "triple"}
KEY_MAP = {"win": "winleft"}


class Blocked(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class Windows(Protocol):
    def foreground(self) -> dict[str, Any] | None: ...              # {"hwnd", "process", "title"}
    def windows_of(self, processes: frozenset[str]) -> list[int]: ...
    def activate(self, hwnd: int) -> bool: ...
    def launch(self, target: str, args: str = "") -> None: ...


class Input(Protocol):
    def click(self, point: Any, kind: str) -> tuple[int, int]: ...
    def write(self, text: str) -> None: ...                 # any Unicode text, whatever the keyboard layout
    def hotkey(self, keys: list[str]) -> None: ...          # virtual keys: Ctrl+S is Ctrl+S on every layout
    def scroll(self, direction: str, amount: int, point: Any | None) -> None: ...
    def release_all(self) -> None: ...


class DesktopExecutor:
    def __init__(self, *, windows: Windows | None = None, inputs: Input | None = None, coords: Any = None,
                 launch_timeout_s: float = 8.0, poll_s: float = 0.2, launch_settle_s: float = 1.0,
                 focus_settle_s: float = 0.3, sleep=time.sleep):
        self.windows = windows or Win32Windows()
        self.inputs = inputs or PyAutoGuiInput()
        self.coords = coords
        self.launch_timeout_s, self.poll_s, self.sleep = launch_timeout_s, poll_s, sleep
        self.launch_settle_s, self.focus_settle_s = launch_settle_s, focus_settle_s
        self.log: list[dict[str, Any]] = []
        self._locked: int | None = None          # hwnd that must stay in front while this action sends input
        self._launched: dict[str, float] = {}    # app -> when this executor last launched it

    # ------------------------------------------------------------------ port
    def execute(self, call: ToolCall, *, observation: dict[str, Any] | None, stop: threading.Event,
                app: str | None = None) -> ActionResult:
        before = observation.get("screenshot_id") if observation else None
        base = dict(call_id=call.call_id, tool=call.tool, before_id=before, target_element_id=call.target_element_id)
        point = None
        try:
            self._check_stop(stop)
            if call.tool == "open_app":
                note = self._open_app(call.args["name"], stop)
                self._wait(self.launch_settle_s, stop)       # a just-launched app drops keys until it is ready
                self.log.append({"tool": call.tool, "note": note})
                return ActionResult(status="ok", **base)
            if call.tool == "wait":
                self._wait(float(call.args["seconds"]), stop)
                return ActionResult(status="ok", **base)
            self._focus(app, observation, pointer=call.target_element_id is not None)
            if call.target_element_id is not None:
                point = self._resolve(observation, call.target_element_id)
            self._check_stop(stop)
            self._act(call, point, stop)
            self.log.append({"tool": call.tool, "app": app, "point": point.xy if point else None})
            return ActionResult(status="ok", screen_point=point.xy if point else None, **base)
        except Blocked as exc:
            return ActionResult(status="blocked", error=str(exc), **base)
        except Stopped:
            self.release_all()
            return ActionResult(status="skipped", error="stopped by the user", **base)

    def release_all(self) -> None:
        self.inputs.release_all()

    # ------------------------------------------------------------------ steps
    def _check_stop(self, stop: threading.Event) -> None:
        if stop.is_set():
            raise Stopped()

    def _wait(self, seconds: float, stop: threading.Event) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._check_stop(stop)
            self.sleep(min(0.1, max(0.0, end - time.monotonic())))

    def _open_app(self, name: str, stop: threading.Event) -> str:
        key = apps.app_key(name)
        if key is None:
            raise Blocked("unknown_app", f"{name!r} is not an in-scope app ({', '.join(apps.LAUNCH)})")
        procs = apps.PROCESSES[key]
        existing = set(self.windows.windows_of(procs))
        recent = self._launched.get(key)
        if recent and time.monotonic() - recent < 60 and existing:
            # Launched moments ago (a retry): bring that window forward instead of opening yet another one.
            if any(self.windows.activate(h) for h in self.windows.windows_of(procs)):
                return "launched earlier in this task, brought to front"
        self.windows.launch(apps.LAUNCH[key], apps.LAUNCH_ARGS.get(key, ""))
        self._launched[key] = time.monotonic()
        deadline = time.monotonic() + self.launch_timeout_s
        while time.monotonic() < deadline:
            self._check_stop(stop)
            fg = self.windows.foreground()
            if fg and fg["process"].lower() in procs:
                return "launched and in front"
            new = [h for h in self.windows.windows_of(procs) if h not in existing]
            if new and self.windows.activate(new[0]):
                return "launched, brought to front"
            self.sleep(self.poll_s)
        # The app may have opened a tab in a window that already existed (Windows 11 Notepad does).
        for hwnd in self.windows.windows_of(procs):
            if self.windows.activate(hwnd):
                return "existing window brought to front"
        raise Blocked("focus_guard", f"{key} did not come to the front within {self.launch_timeout_s:.0f} s")

    def _focus(self, app: str | None, observation: dict[str, Any] | None, *, pointer: bool) -> None:
        procs = apps.processes_for(app)
        self._locked = None
        fg = self.windows.foreground()
        if fg is None:
            raise Blocked("focus_guard", "no foreground window")
        if procs:
            if fg["process"].lower() not in procs:
                if not any(self.windows.activate(h) for h in self.windows.windows_of(procs)):
                    raise Blocked("focus_guard", f"{app} is not open or cannot be brought to the front")
                self.sleep(self.focus_settle_s)
                fg = self.windows.foreground()
                if fg is None or fg["process"].lower() not in procs:
                    raise Blocked("focus_guard", f"{app} did not stay in front")
                if pointer:   # the elements were read from another window: look again first
                    raise Blocked("focus_changed", f"{app} was brought to the front; re-read the screen")
            if pointer:
                seen = ((observation or {}).get("window") or {}).get("process", "").lower()
                if seen not in procs:
                    raise Blocked("focus_changed", f"the screen was read from {seen or 'an unknown window'}, "
                                                   f"not {app}")
        else:
            if fg["process"].lower() in apps.PROTECTED_PROCESSES:
                raise Blocked("focus_guard", f"{fg['process']} is protected and no app was named for this step")
            seen_hwnd = ((observation or {}).get("window") or {}).get("hwnd")
            if seen_hwnd and seen_hwnd != fg["hwnd"]:
                raise Blocked("focus_changed", "the foreground window changed since the screen was read")
        if fg["process"].lower() in apps.PROTECTED_PROCESSES:
            raise Blocked("focus_guard", f"{fg['process']} is protected")
        self._locked = fg["hwnd"]

    def _still_in_front(self) -> None:
        """Right before each batch of input: the user (or a pop-up) may have moved the focus since the guard."""
        if self._locked is None:
            return
        fg = self.windows.foreground()
        if fg is None or fg["hwnd"] != self._locked:
            raise Blocked("focus_changed", "the foreground window changed while the action was running")

    def _resolve(self, observation: dict[str, Any] | None, element_id: str):
        if observation is None:
            raise Blocked("no_target", "no observation to resolve the element in")
        ensure_vision_on_path()
        from contracts import ScreenObservation
        if self.coords is None:
            from nelly_vision.coordinates import CoordinateManager
            self.coords = CoordinateManager()
        try:
            return self.coords.resolve_target_point(ScreenObservation.model_validate(observation), element_id)
        except Exception as exc:          # Team 1's TargetRejected carries a code: stale, window_resized, off_screen...
            code = getattr(exc, "code", None)
            if code:
                raise Blocked(code, str(exc)) from None
            raise

    def _act(self, call: ToolCall, point, stop: threading.Event) -> None:
        args = call.args
        self._still_in_front()
        if call.tool == "copy_element_text":
            # Empty the clipboard first, so an old clipboard text can never pass the copy check as if just copied.
            getattr(self.inputs, "clear_clipboard", lambda: None)()
            self.inputs.click(point, "triple")                 # select the element's line
            self.sleep(0.15)
            self._still_in_front()
            self.inputs.hotkey(["ctrl", "c"])
            self.sleep(0.2)                                    # let the app put it on the clipboard
        elif call.tool in POINTER:
            self.inputs.click(point, POINTER[call.tool])
        elif call.tool == "type_text":
            if point is not None:
                self.inputs.click(point, "left")
            if args.get("clear_first"):
                self._still_in_front()
                self.inputs.hotkey(["ctrl", "a"])
            text = args["text"]
            for i in range(0, len(text), 200):             # chunks: stop and focus are re-checked inside long text
                self._check_stop(stop)
                self._still_in_front()
                self.inputs.write(text[i:i + 200])
        elif call.tool == "press_keys":
            self.inputs.hotkey([KEY_MAP.get(k, k) for k in args["keys"]])
        elif call.tool == "scroll":
            self.inputs.scroll(args["direction"], int(args.get("amount", 3)), point)
        else:
            raise Blocked("unsupported_tool", f"{call.tool} has no desktop implementation")


class Stopped(Exception):
    pass


# ---------------------------------------------------------------------- real backends
class Win32Windows:
    def __init__(self):
        ensure_vision_on_path()
        from nelly_vision.capture import set_dpi_awareness
        set_dpi_awareness()

    def foreground(self) -> dict[str, Any] | None:
        from nelly_vision.capture import foreground_window
        w = foreground_window()
        return {"hwnd": w.hwnd, "process": w.process or "", "title": w.title} if w else None

    def windows_of(self, processes: frozenset[str]) -> list[int]:
        import psutil
        import win32gui
        import win32process
        found: list[int] = []

        def visit(hwnd, _):
            if not (win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd)):
                return True
            try:
                name = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
            except Exception:
                return True
            if name in processes:
                found.append(hwnd)
            return True

        win32gui.EnumWindows(visit, None)
        return found

    def activate(self, hwnd: int) -> bool:
        """Bring a window forward from a background process: attach to the foreground thread's input, then
        SetForegroundWindow; fall back to the Alt-tap rule Windows applies to background processes."""
        import win32api
        import win32con
        import win32gui
        import win32process
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            fg = win32gui.GetForegroundWindow()
            if fg == hwnd:
                return True
            me, them = win32api.GetCurrentThreadId(), win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
            attached = bool(them) and them != me and _attach(me, them, True)
            try:
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    _attach(me, them, False)
        except Exception:
            pass
        time.sleep(0.15)
        if win32gui.GetForegroundWindow() != hwnd:
            try:
                win32api.keybd_event(0x12, 0, 0, 0)       # Alt down / up
                win32api.keybd_event(0x12, 0, 2, 0)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.15)
            except Exception:
                pass
        return win32gui.GetForegroundWindow() == hwnd

    def launch(self, target: str, args: str = "") -> None:
        import os
        if args:
            os.startfile(target, arguments=args)            # ShellExecute with arguments (Python >= 3.10)
        else:
            os.startfile(target)                            # ShellExecute: App Paths names and URIs


def _open_clipboard(cb, tries: int = 5) -> bool:
    for _ in range(tries):                                  # another app may hold it for a moment
        try:
            cb.OpenClipboard()
            return True
        except Exception:
            time.sleep(0.05)
    return False


def _attach(me: int, them: int, on: bool) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.AttachThreadInput(me, them, on))


VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10, "winleft": 0x5B, "win": 0x5B, "enter": 0x0D, "tab": 0x09,
      "esc": 0x1B, "backspace": 0x08, "delete": 0x2E, "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25,
      "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
      **{f"f{i}": 0x6F + i for i in range(1, 13)},
      **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"}}
EXTENDED = {0x2E, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x5B}


class SendInputKeyboard:
    """Keyboard through Win32 SendInput. PyAutoGUI maps characters through the *active* layout and silently drops
    what that layout cannot produce: with Arabic (0x401) active, 'Hello NELLY' arrived as one space and the 's' of
    Ctrl+Shift+S vanished. Text goes as Unicode characters, chords as virtual keys: both work on any layout."""

    def __init__(self, delay_s: float = 0.025, hold_s: float = 0.006):
        # Measured on Windows 11 Notepad: a 4 ms burst turned "Hello NELLY" into "Hello LLLLY" (late VK_PACKET
        # handling); one key-down / key-up pair per character with these gaps types it exactly.
        self.hold_s = hold_s
        import ctypes
        from ctypes import wintypes
        ulong_ptr = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", UNION)]

        self.ctypes, self.INPUT, self.KEYBDINPUT, self.UNION = ctypes, INPUT, KEYBDINPUT, UNION
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.delay_s = delay_s

    def _key(self, vk: int = 0, scan: int = 0, flags: int = 0):
        return self.INPUT(type=1, u=self.UNION(ki=self.KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))

    def _send(self, *events) -> None:
        arr = (self.INPUT * len(events))(*events)
        if self.user32.SendInput(len(events), arr, self.ctypes.sizeof(self.INPUT)) != len(events):
            raise OSError(f"SendInput was blocked (error {self.ctypes.get_last_error()}): is the target elevated?")

    def type(self, text: str) -> None:
        """Slow path, used when the clipboard cannot be borrowed. Notepad garbles keys queued while it is busy
        (right after a space it checks the previous word), so pause longer at word boundaries."""
        UNICODE, UP = 0x0004, 0x0002
        for ch in text:
            if ch == "\n":
                self.chord(["enter"])
                continue
            data = ch.encode("utf-16-le")
            units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]   # 2 beyond the BMP
            self._send(*[self._key(scan=u, flags=UNICODE) for u in units])
            time.sleep(self.hold_s)
            self._send(*[self._key(scan=u, flags=UNICODE | UP) for u in units])
            time.sleep(self.delay_s * (6 if not ch.isalnum() else 1))

    def chord(self, keys: list[str]) -> None:
        UP, EXT = 0x0002, 0x0001
        codes = [VK[k] for k in keys]
        down = [self._key(vk=c, flags=EXT if c in EXTENDED else 0) for c in codes]
        up = [self._key(vk=c, flags=UP | (EXT if c in EXTENDED else 0)) for c in reversed(codes)]
        self._send(*down)
        time.sleep(0.03)
        self._send(*up)
        time.sleep(0.05)

    def release_modifiers(self) -> None:
        self._send(*[self._key(vk=VK[k], flags=0x0002 | (0x0001 if VK[k] in EXTENDED else 0))
                     for k in ("ctrl", "alt", "shift", "winleft")])


class PyAutoGuiInput:
    """Mouse through PyAutoGUI after SetCursorPos on a checked point; keyboard through SendInputKeyboard."""

    def __init__(self):
        ensure_vision_on_path()
        from nelly_vision.coordinates import ensure_physical_input
        ensure_physical_input()                             # per-monitor DPI aware BEFORE pyautogui is imported
        import pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        self.gui = pyautogui
        self.keys = SendInputKeyboard()

    def click(self, point, kind: str) -> tuple[int, int]:
        from nelly_vision.coordinates import move_cursor
        xy = move_cursor(point)                             # SetCursorPos on the checked physical point
        self.gui.failSafeCheck()
        {"left": self.gui.click, "double": self.gui.doubleClick, "right": self.gui.rightClick,
         "triple": self.gui.tripleClick}[kind]()
        return xy

    def write(self, text: str) -> None:
        self.gui.failSafeCheck()                            # mouse in a corner still aborts typing
        if not self._paste(text):
            self.keys.type(text)

    def _paste(self, text: str) -> bool:
        """One Ctrl+V instead of one key per character: per-character input raced inside Notepad ('Hello LLLLY'
        twice in live runs). The clipboard is borrowed only when it holds plain text or nothing, so an image or a
        file list is never lost; the user's text is put back, and ours is kept out of clipboard history."""
        import win32clipboard as cb
        text_formats = {cb.CF_UNICODETEXT, cb.CF_TEXT, cb.CF_OEMTEXT, cb.CF_LOCALE}
        if not _open_clipboard(cb):
            return False
        try:
            formats, f = [], 0
            while (f := cb.EnumClipboardFormats(f)):
                formats.append(f)
            if any(f not in text_formats for f in formats):
                return False
            previous = cb.GetClipboardData(cb.CF_UNICODETEXT) if cb.CF_UNICODETEXT in formats else None
            cb.EmptyClipboard()
            cb.SetClipboardData(cb.CF_UNICODETEXT, text)
            cb.SetClipboardData(cb.RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing"), b"\0")
        finally:
            cb.CloseClipboard()
        self.keys.chord(["ctrl", "v"])
        time.sleep(0.3)                                     # let the paste finish before the clipboard changes back
        if _open_clipboard(cb):
            try:
                cb.EmptyClipboard()
                if previous is not None:
                    cb.SetClipboardData(cb.CF_UNICODETEXT, previous)
            finally:
                cb.CloseClipboard()
        return True

    def hotkey(self, keys: list[str]) -> None:
        self.gui.failSafeCheck()
        self.keys.chord(keys)

    def clear_clipboard(self) -> None:
        import win32clipboard as cb
        if _open_clipboard(cb):
            try:
                cb.EmptyClipboard()
            finally:
                cb.CloseClipboard()

    def scroll(self, direction: str, amount: int, point) -> None:
        if point is not None:
            from nelly_vision.coordinates import move_cursor
            move_cursor(point)
        clicks = amount * 120                               # one wheel notch is 120 units on Windows
        if direction in ("up", "down"):
            self.gui.scroll(clicks if direction == "up" else -clicks)
        else:
            self.gui.hscroll(clicks if direction == "right" else -clicks)

    def release_all(self) -> None:
        try:
            self.keys.release_modifiers()
        except Exception:
            pass
        for button in ("left", "right", "middle"):
            try:
                self.gui.mouseUp(button=button)
            except Exception:
                pass
