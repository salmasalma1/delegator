"""Team 2 shim for Team 1's `apps` table: which applications the executor may launch and which processes
belong to each one.

Keep it small on purpose. An application that is not listed here is refused for input (unknown_app):
the executor never types into a window it cannot tie to a named, known application.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------------------------------------------
# PROTECTED PROCESSES: the executor refuses to click, type or press keys while one of these is in front.
# Edit this set to add or remove programs (process names, lower case).
PROTECTED_PROCESSES = frozenset({
    "windowsterminal.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "conhost.exe",
    "code.exe",
    "claude.exe",
    "keepass.exe",
    "keepassxc.exe",
    "1password.exe",
    "bitwarden.exe",
    "lastpass.exe",
})
# ---------------------------------------------------------------------------------------------------------------

# What open_app may start: the same three programs as OPENABLE in execution/desktop_adapter.py.
LAUNCH = {
    "notepad": "notepad.exe",
    "explorer": "explorer.exe",
    "calculator": "calc.exe",
}
LAUNCH_ARGS: dict[str, str] = {}

# Process names of each application's windows (lower case).
# Note: on Windows 10 the Calculator window belongs to applicationframehost.exe (shared by every Store app),
# which is deliberately NOT listed, so input to Calculator is refused there as wrong_window.
PROCESSES = {
    "notepad": frozenset({"notepad.exe"}),
    "explorer": frozenset({"explorer.exe"}),
    "calculator": frozenset({"calculatorapp.exe", "calculator.exe"}),
}

# Names the planner or the schema may use -> key above.
_ALIASES = {
    "notepad": "notepad",
    "explorer": "explorer",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "calculator": "calculator",
    "calc": "calculator",
}


def app_key(name: str | None) -> str | None:
    """The table key for an application name, or None when it is not a known application."""
    if not name:
        return None
    n = str(name).strip().lower()
    if n.endswith(".exe"):
        n = n[:-4]
    return _ALIASES.get(n)


def processes_for(app: str | None) -> frozenset[str]:
    """Process names of the application's windows; empty when the application is unknown or not given."""
    key = app_key(app)
    return PROCESSES.get(key, frozenset()) if key else frozenset()
