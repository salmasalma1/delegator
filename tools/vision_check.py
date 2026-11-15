"""
vision_check — does the REAL vision see the screen, find a target, and give a click point? No model, no graph.

    python tools/vision_check.py --target "Save"                  # look at the live screen, find "Save", show the point
    python tools/vision_check.py --target "Copy" --image shot.png # same on a saved screenshot (the point may be rejected)
    python tools/vision_check.py --target "Save" --click          # + really click it (needs NELLY_LIVE_INPUT=1, asks you first)
    python tools/vision_check.py --find-type input --type "hello Lumi"   # click the biggest text field and TYPE (same rules)

Without --click nothing is ever clicked. With --click you must ALSO set NELLY_LIVE_INPUT=1 and answer y.
Stop at any time: Ctrl+C, or move the mouse to a screen corner.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision import vision_adapter                       # noqa: E402
from vision.adapter import normalize, to_prompt         # noqa: E402
from vision.ground import pick                          # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", help="the visible text of the control, e.g. Save")
    ap.add_argument("--find-type", help="instead of text: take the largest usable element of this type (e.g. input)")
    ap.add_argument("--type", dest="text", help="type this text into the element (click it first); needs NELLY_LIVE_INPUT=1 and an approval")
    ap.add_argument("--image", help="a screenshot file instead of the live screen")
    ap.add_argument("--click", action="store_true", help="really click it (also needs NELLY_LIVE_INPUT=1)")
    ap.add_argument("--countdown", type=int, default=5, help="seconds to get the right window in front (live only)")
    a = ap.parse_args(argv)
    if not a.target and not a.find_type:
        ap.error("give --target TEXT or --find-type TYPE")

    print("=" * 64)
    print(" VISION CHECK")
    print("=" * 64)
    if not vision_adapter.available():
        print(" FAIL: the vision package is not installed in this environment.")
        return 2
    print(f" detector weights : {os.getenv('NELLY_DETECTOR_WEIGHTS') or '(NOT SET: weak edge proposals will be used)'}")
    print(f" ocr languages    : {os.getenv('NELLY_OCR_LANGS') or 'en (default)'}")

    if not a.image and a.countdown:
        print(f"\n Put the target window in front. Looking in {a.countdown} s ...")
        time.sleep(a.countdown)

    t0 = time.time()
    try:
        raw = vision_adapter.observe(screenshot=a.image, target=a.target)
    except Exception as e:                                    # noqa: BLE001
        print(f" FAIL: vision crashed: {type(e).__name__}: {e}")
        return 1
    secs = time.time() - t0
    ctx = normalize(raw, source="nelly_vision")
    q = ctx["quality"]
    print(f"\n 1. SEEING   detector={ctx['detector']}  elements={len(raw.get('elements') or [])}  "
          f"took={secs:.1f}s  window={ctx['window_title']!r}")
    print(f"    quality={q['score']} clear={q['clear']} reasons={q['reasons']}")
    if ctx["detector"] in ("edge-proposals", "none", None):
        print("    WARNING: the trained detector did NOT run (check NELLY_DETECTOR_WEIGHTS). This result does not count.")
    print("\n" + to_prompt(ctx, limit=15))

    if a.find_type:                      # choose by kind, not by words: the biggest usable element of that type
        from vision.adapter import is_usable
        cands = [e for e in ctx["elements"] if e.get("type") == a.find_type and is_usable(e) and e.get("bbox_norm")]
        area = lambda e: (e["bbox_norm"][2] - e["bbox_norm"][0]) * (e["bbox_norm"][3] - e["bbox_norm"][1])  # noqa: E731
        cands.sort(key=area, reverse=True)
        g = ({"status": "grounded", "why": f"largest usable {a.find_type}", "element": cands[0], "candidates": len(cands)}
             if cands else {"status": "not_found", "why": f"no usable element of type {a.find_type!r}", "candidates": 0})
    else:
        g = pick(f"click {a.target}", ctx["elements"])
    print(f"\n 2. FINDING  status={g['status']}  why={g['why']}  candidates={g['candidates']}")
    if g["status"] != "grounded":
        print("    Not found / not sure on this screen. That is a normal answer, not a crash.")
        return 0
    el = g["element"]
    print(f"    element {el.get('id')} {el.get('type')} {el.get('text')!r} box={el.get('bbox_norm')} "
          f"conf={el.get('confidence')} clickable={el.get('clickable')}  ambiguous={g.get('ambiguous')}")

    try:
        pt = vision_adapter.resolve_point(el.get("id"), el.get("bbox_norm"), raw.get("screenshot_id"))
    except vision_adapter.TargetRejected as e:
        print(f"\n 3. POINT    REFUSED by Team 1's coordinate manager: code={e.code}  ({e})")
        return 0
    except Exception as e:                                    # noqa: BLE001
        print(f"\n 3. POINT    FAIL: {type(e).__name__}: {e}")
        return 1
    print(f"\n 3. POINT    screen pixel = {tuple(pt)}   (virtual desktop, physical pixels)")

    if not a.click and a.text is None:
        print("\n Dry check done: nothing was clicked. Add --click (and NELLY_LIVE_INPUT=1) to click.")
        return 0

    from execution import desktop_adapter
    from graph.safety_port import get_safety, bind_approver, console_approver
    if not desktop_adapter.live_requested():
        print("\n --click given but NELLY_LIVE_INPUT=1 is not set: staying a dry run.")
    action = "type" if a.text is not None else "click"
    req = {"action_id": "vision-check", "task_id": "vision-check", "action_type": action, "application": ctx["app"] or "unknown",
           "target_element_id": el.get("id"), "parameters": ({"bbox_norm": el.get("bbox_norm"), "text": a.text} if a.text is not None
                          else {"bbox_norm": el.get("bbox_norm")}),
           "observation_id": raw.get("screenshot_id"), "strategy": "vision_fallback", "risk_level": "medium" if action == "type" else "low", "reversible": True}
    with bind_approver(console_approver):
        verdict = get_safety().check(req)
    print(f"\n 4. SAFETY   {verdict.get('decision')}  ({verdict.get('reason')})")
    if verdict.get("decision") != "approved":
        print("    Not clicked.")
        return 0
    res = desktop_adapter.execute(req)
    print(f" 5. {action.upper():9} status={res['status']}  output={res['output']}  error={res['error']}")
    print("    (Whether it WORKED is for you to see on the screen; no agent judged it.)")
    return 0 if res["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
