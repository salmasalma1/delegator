"""
time_breakdown: where does the time go, the VISION or the MODEL? No task, no click, no keyboard input.

    python tools/time_breakdown.py            # 3 looks at the live screen + 3 small model calls
    python tools/time_breakdown.py --looks 2 --calls 2

It looks at your REAL screen (private: nothing is saved and no text is printed), then asks the model a tiny question
shaped like the agent's own (one JSON object). It prints seconds per look (first one includes model loading),
Team 1's own stage timings when they give them, and seconds per model call. One agent cycle is about
one look + one model call (+ one more look after the action).
Stop with Ctrl+C. The key and the screen text are never printed.
"""
import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fmt(xs):
    return ", ".join(f"{x:.1f}s" for x in xs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--looks", type=int, default=3)
    ap.add_argument("--calls", type=int, default=3)
    a = ap.parse_args(argv)

    looks, stages = [], []
    from vision import vision_adapter
    if not vision_adapter.available():
        print("VISION: not available here (package missing, or NELLY_VISION=off): skipped")
    else:
        for i in range(a.looks):
            t = time.time()
            try:
                raw = vision_adapter.observe(screenshot=None, target=None)
            except Exception as e:                                # noqa: BLE001
                print(f"VISION: look {i + 1} failed: {type(e).__name__}: {str(e)[:160]}")
                break
            looks.append(time.time() - t)
            tm = raw.get("timings_ms") or {}
            if tm:
                stages.append({k: round(v / 1000, 1) for k, v in tm.items() if isinstance(v, (int, float))})
            print(f"  look {i + 1}: {looks[-1]:.1f}s  elements={len(raw.get('elements') or [])}"
                  + (f"  stages(s)={stages[-1]}" if tm else ""))

    import llm
    calls = []
    if not llm.available():
        print("MODEL: no key set (NELLY_LLM_API_KEY): skipped")
    else:
        st = llm.provider_settings()
        print(f"MODEL: host {st['base_url'].split('//')[-1].split('/')[0]}  model {st['model'] or '(default)'}")
        for i in range(a.calls):
            t = time.time()
            try:
                llm.chat_json('Answer ONLY JSON: {"action": "click", "element_id": "e1", "why": "short"}',
                              'Sub-goal: press the button named OK. Screen: e1 button "OK"; e2 input "Name".')
            except Exception as e:                                # noqa: BLE001
                print(f"  call {i + 1} failed: {type(e).__name__}: {str(e)[:160]}")
                break
            calls.append(time.time() - t)
            print(f"  call {i + 1}: {calls[-1]:.1f}s")

    print("\nSUMMARY")
    warm = looks[1:] or looks
    v = statistics.median(warm) if warm else None
    m = statistics.median(calls) if calls else None
    if looks:
        print(f"  look  : first {looks[0]:.1f}s (includes loading), typical {v:.1f}s   [{_fmt(looks)}]")
    if calls:
        print(f"  model : typical {m:.1f}s per call (tiny prompt; the real prompt is longer)   [{_fmt(calls)}]")
    if v is not None and m is not None:
        cycle = 2 * v + m
        print(f"  one agent action ~ 2 looks + 1 model call ~ {cycle:.0f}s; 14 cycles ~ {14 * cycle / 60:.0f} min")
        share = 2 * v / cycle * 100
        print(f"  vision is ~{share:.0f}% of a cycle -> " +
              ("the VISION is the main cost" if share >= 60 else
               "the MODEL is the main cost" if share <= 40 else "both matter"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
