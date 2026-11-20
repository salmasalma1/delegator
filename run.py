"""Run NELLY (text).

    python run.py "your task"      one task, then exit
    python run.py --trace "task"   same, and also write runs/run_<id>.json + .html (see gateway/trace.py)
    python run.py                  interactive: type a task; type stop / exit

Ctrl+C stops the task before its next action.
"""
import os
import sys

from gateway.session import Session


def _progress(event: dict):
    for node, update in event.items():
        print(f"  -> {node}")
        update = update if isinstance(update, dict) else {}
        if node == "director" and update.get("nodes"):             # the PLAN, as soon as the planner makes it
            print("     PLAN:")
            for n in update["nodes"]:
                print(f"       {n.get('id', '')} [{n.get('app')}] {n.get('node')}")
                print(f"           done when: {n.get('flag')}")
                for st in n.get("steps") or []:
                    print(f"           hint: {st}")
        elif node == "plan_check" and update.get("plan_verdict"):
            v = update["plan_verdict"]
            print(f"     plan check: ok={v.get('ok')} via={v.get('method')} {v.get('reason') or ''}".rstrip())


def _trace(out):
    from gateway.trace import write_trace
    paths = write_trace(out.get("state") or {}, out.get("report"), timeline=out.get("timeline"))
    if "error" in paths:
        print(f"trace not written: {paths['error']}")
    else:
        print(f"trace: {paths['json']}\nviewer: {paths['html']}  (open it in a browser)\nall runs: {paths['index']}   newest: runs\\latest.html")


def main(argv):
    trace = "--trace" in argv or os.getenv("NELLY_TRACE") == "1"
    argv = [a for a in argv if a != "--trace"]
    quiet = os.getenv("NELLY_QUIET") == "1"
    from vision.env_check import print_startup_warnings      # F6: detector / memory (read-only, no secrets)
    print_startup_warnings()
    import llm                                               # provider host + model in use (never the key)
    for line in llm.startup_lines():
        print(line)
    session = Session(on_event=None if quiet else _progress)

    if argv:
        out = session.submit(" ".join(argv))
        print(out["text"])
        if trace and out.get("kind") == "report":
            _trace(out)
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
        if trace and out.get("kind") == "report":
            _trace(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
