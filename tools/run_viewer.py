"""
run_viewer: turn a run trace (runs/run_<id>.json, written by `python run.py --trace "task"`) into ONE html page
you can open in a browser and screenshot. The page is self-contained: no server, no network, nothing uploaded.

    python tools/run_viewer.py runs/run_X.json            # writes runs/run_X.html
    python tools/run_viewer.py                            # no file: writes the page with the labelled FAKE sample

The trace holds no window title and no element text unless it was written with NELLY_TRACE_FULL=1.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "/*__RUN_DATA__*/"


def make_html(trace: dict = None) -> str:
    with open(os.path.join(HERE, "run_viewer.html"), encoding="utf-8") as f:
        page = f.read()
    data = json.dumps(trace, ensure_ascii=False, default=str).replace("</", "<\\/") if trace else "null"
    return page.replace(MARK, data, 1)


def main(argv):
    trace, out = None, os.path.join("runs", "run_sample.html")
    if argv:
        with open(argv[0], encoding="utf-8") as f:
            trace = json.load(f)
        out = os.path.splitext(argv[0])[0] + ".html"
    else:
        os.makedirs("runs", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(make_html(trace))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
