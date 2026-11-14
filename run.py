"""Run NELLY (text).

    python run.py "your task"      one task, then exit
    python run.py                  interactive: type a task; type stop / exit

Ctrl+C stops the task before its next action.
"""
import os
import sys

from gateway.session import Session


def _progress(event: dict):
    for node in event:
        print(f"  -> {node}")


def main(argv):
    quiet = os.getenv("NELLY_QUIET") == "1"
    session = Session(on_event=None if quiet else _progress)

    if argv:
        out = session.submit(" ".join(argv))
        print(out["text"])
        status = out["report"]["status"]
        return {"completed": 0, "dry_run": 3}.get(status, 1)      # a dry run is not a success

    if not sys.stdin.isatty():
        print("where is the task? usage: python run.py \"your task\"")
        return 2

    print("NELLY. Type a task. 'stop' or Ctrl+C stops it, 'exit' leaves.")
    while True:
        prompt = f"{session.pending['question']}\n> " if session.pending else "> "
        try:
            text = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        out = session.submit(text)
        if out["kind"] == "exit":
            return 0
        print(out["text"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
