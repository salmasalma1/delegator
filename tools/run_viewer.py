"""
run_viewer: turn a run trace (runs/run_<id>.json, written by `python run.py --trace "task"`) into ONE html page
you can open in a browser and screenshot. The page is self-contained: no server, no network, nothing uploaded.

    python tools/run_viewer.py runs/run_X.json            # writes runs/run_X.html
    python tools/run_viewer.py --index [runs]             # rebuild runs/index.html from the trace files

Every run also refreshes runs/index.html (all runs, newest first) and runs/latest.html (a copy of the newest run).

The trace holds no window title and no element text unless it was written with NELLY_TRACE_FULL=1.
"""
import html as _html
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "/*__RUN_DATA__*/"


def make_html(trace: dict = None) -> str:
    with open(os.path.join(HERE, "run_viewer.html"), encoding="utf-8") as f:
        page = f.read()
    data = json.dumps(trace, ensure_ascii=False, default=str).replace("</", "<\\/") if trace else "null"
    return page.replace(MARK, data, 1)


def make_index(out_dir: str = "runs") -> str:
    """runs/index.html: one row per run_*.json, newest first (file time = when the run was written)."""
    rows = []
    for name in os.listdir(out_dir):
        if not (name.startswith("run_") and name.endswith(".json")):
            continue
        path = os.path.join(out_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                t = json.load(f)
        except (OSError, ValueError):
            continue
        nodes = t.get("nodes") or []
        counts = {}
        for n in nodes:
            counts[n.get("status") or "?"] = counts.get(n.get("status") or "?", 0) + 1
        rows.append((os.path.getmtime(path), name[:-5], t, counts))
    rows.sort(reverse=True)
    e = _html.escape
    body = []
    for mtime, base, t, counts in rows:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        tally = ", ".join(f"{v} {e(str(k))}" for k, v in counts.items()) or "no nodes"
        body.append(f'<tr><td>{when}</td><td><a href="{e(base)}.html">{e(str(t.get("task") or base))}</a></td>'
                    f'<td>{e(str(t.get("final_status") or "?"))}</td><td>{e(str(t.get("execution_mode") or ""))}</td>'
                    f'<td>{tally}</td></tr>')
    table = "\n".join(body) or '<tr><td colspan="5">No runs yet. Try: python run.py --trace "your task"</td></tr>'
    return INDEX.replace("__ROWS__", table)


INDEX = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NELLY runs</title>
<style>
:root{--bg:#fff1f8;--panel:#fff;--fg:#3a1230;--muted:#8a5b78;--line:#f6c9e0;--accent:#e0218a;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#24101f;--panel:#34182c;--fg:#ffe9f5;--muted:#d9a3c4;--line:#5a2a4a;--accent:#ff6fb5;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif;padding:20px max(16px,env(safe-area-inset-left,0px))}
.w{max-width:960px;margin:0 auto}h1{margin:0 0 12px;font-size:22px;color:var(--accent)}
.t{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:8px 12px;border-top:1px solid var(--line);vertical-align:top}
th{border-top:0;color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}a{color:var(--accent);font-weight:600}
</style><div class="w"><h1>NELLY runs</h1><div class="t"><table>
<tr><th>When</th><th>Task</th><th>Final</th><th>Mode</th><th>Nodes</th></tr>
__ROWS__
</table></div></div>"""


def main(argv):
    if argv and argv[0] == "--index":
        d = argv[1] if len(argv) > 1 else "runs"
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write(make_index(d))
        print(os.path.join(d, "index.html"))
        return 0
    if not argv:
        print("usage: python tools/run_viewer.py runs/run_<id>.json   |   python tools/run_viewer.py --index [runs]")
        return 2
    with open(argv[0], encoding="utf-8") as f:
        trace = json.load(f)
    out = os.path.splitext(argv[0])[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(make_html(trace))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
