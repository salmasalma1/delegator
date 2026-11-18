"""
Read-only start-up checks for the vision side (F6). Nothing here starts a model or reads a secret.

    startup_warnings() -> [str]          # detector not set / missing, free memory too low
    print_startup_warnings(out=print)
    ensure_memory_for_ocr()              # raises MemoryError below the safe level: OCR is never started then

Why: with too little free memory PaddleOCR crashed the whole Python process (access violation, exit 139), and
without NELLY_DETECTOR_WEIGHTS Team 1's vision silently falls back to weak edge proposals.
"""
import os
from typing import Optional

DEFAULT_MIN_FREE_GB = 3.0


def min_free_gb() -> float:
    try:
        return float(os.getenv("NELLY_MIN_FREE_MEM_GB", DEFAULT_MIN_FREE_GB))
    except ValueError:
        return DEFAULT_MIN_FREE_GB


def free_commit_gb() -> Optional[float]:
    """Free commit memory (RAM + page file) in GB on Windows; None where it cannot be read."""
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return st.ullAvailPageFile / 2 ** 30
    except Exception:                                                   # noqa: BLE001  (not Windows)
        return None


def memory_warning() -> Optional[str]:
    free = free_commit_gb()
    if free is None or free >= min_free_gb():
        return None
    return (f"only {free:.1f} GB of free memory (RAM + page file); vision needs at least {min_free_gb():.1f} GB "
            "(NELLY_MIN_FREE_MEM_GB). Close other programs: OCR will not be started below this level.")


def detector_warning() -> Optional[str]:
    path = os.getenv("NELLY_DETECTOR_WEIGHTS")
    if not path:
        return ("NELLY_DETECTOR_WEIGHTS is not set: Team 1's vision uses its default path and, if that file is "
                "missing, falls back to weak edge proposals instead of the trained detector")
    if not os.path.exists(path):
        return f"NELLY_DETECTOR_WEIGHTS points to a file that was not found ({os.path.basename(path)})"
    return None


def startup_warnings() -> list:
    return [w for w in (detector_warning(), memory_warning()) if w]


def print_startup_warnings(out=print) -> list:
    warnings = startup_warnings()
    for w in warnings:
        out(f"[startup] WARNING: {w}")
    return warnings


def ensure_memory_for_ocr() -> None:
    """Called before every perception: below the safe level, refuse instead of letting OCR crash the process."""
    w = memory_warning()
    if w:
        raise MemoryError(w)
