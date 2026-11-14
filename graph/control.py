"""
Stop switch. One flag, checked between nodes and before every action the worker takes.

Anything can set it: Ctrl+C in the terminal, a voice command ("stop"), a GUI button.
It never kills an action that is already running; it stops the NEXT one.
"""
import threading

_flag = threading.Event()


def cancel():
    _flag.set()


def cancelled() -> bool:
    return _flag.is_set()


def reset():
    _flag.clear()
