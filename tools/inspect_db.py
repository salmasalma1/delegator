"""
inspect_db — look inside the checkpoint store and confirm writes are landing.

    python tools/inspect_db.py                      # uses NELLY_DB or ./agent.db
    python tools/inspect_db.py agent.db --session <id> --dump <checkpoint_id>

Prints the three tables checkpoint store owns (checkpoints / steps / audit_log), newest first.
"""
import argparse
import json
import os
import sqlite3
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", nargs="?", default=os.getenv("NELLY_DB", "agent.db"))
    ap.add_argument("--session", default=None)
    ap.add_argument("--dump", default=None, help="print one full agent_state_json")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"no database at {args.db}")
        print("create it by running a task with NELLY_DB set, e.g.")
        print("  NELLY_DB=agent.db python run.py 'open notepad and type hi'")
        return 1

    con = sqlite3.connect(args.db)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"db      : {os.path.abspath(args.db)}")
    print(f"tables  : {tables}\n")

    where, params = "", ()
    if args.session:
        where, params = "WHERE session_id = ?", (args.session,)

    rows = con.execute(
        f"SELECT checkpoint_id, session_id, task_id, step_number, created_at, "
        f"length(agent_state_json) FROM checkpoints {where} "
        f"ORDER BY created_at DESC, rowid DESC LIMIT ?", params + (args.limit,)).fetchall()
    print(f"checkpoints ({len(rows)} shown)")
    for r in rows:
        print(f"  {r[0][:8]}  step={r[3]:<2} session={(r[1] or '')[:8]}  "
              f"size={r[5]}B  {r[4]}")
    if not rows:
        print("  (none — has a task run with NELLY_DB set?)")

    for table, cols in (("steps", "checkpoint_id, step_id, description, app, status, "
                                 "confidence, source"),
                        ("audit_log", "checkpoint_id, safety_decision, latency_ms, created_at")):
        try:
            data = con.execute(f"SELECT {cols} FROM {table} ORDER BY id DESC LIMIT ?",
                               (args.limit,)).fetchall()
        except sqlite3.OperationalError as e:
            print(f"\n{table}: {e}")
            continue
        print(f"\n{table} ({len(data)} shown)")
        for d in data:
            print("  " + " | ".join("" if v is None else str(v)[:46] for v in d))

    if args.dump:
        row = con.execute("SELECT agent_state_json FROM checkpoints WHERE checkpoint_id = ?",
                          (args.dump,)).fetchone()
        if row:
            print("\nagent_state_json:")
            print(json.dumps(json.loads(row[0]), indent=2, ensure_ascii=False)[:4000])
        else:
            print(f"\nno checkpoint {args.dump}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
