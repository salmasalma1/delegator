"""The run trace restates the state, hides screen text by default, and never upgrades a status."""
import json

from gateway.trace import build_trace, look_summary, write_trace
from tools.run_viewer import make_html

CTX = {"vision_source": "nelly_vision", "detector": "yolo", "app": "notepad", "window_title": "secret.txt - Notepad",
       "total_elements": 2, "quality": {"score": 0.7, "clear": True, "reasons": []}, "needs_review": False,
       "look_seconds": 12.3, "warnings": [],
       "elements": [{"id": "e1", "type": "input", "text": "my private words", "bbox_norm": [0.1, 0.2, 0.9, 0.8],
                     "confidence": 0.9, "clickable": True}],
       "grounding": {"target": "private target", "element_id": "e1", "status": "ok", "confidence": 0.8}}


def _state():
    return {
        "task_id": "t1", "goal": "write a note", "language": "en", "status": "dry_run", "plan_round": 1,
        "nodes": [{"id": "n1", "node": "Notepad: write", "app": "notepad", "flag": "text visible",
                   "steps": ["type"], "status": "dry_run", "history": []}],
        "sub_results": [{"node_id": "n1", "node": "Notepad: write", "round": 1, "looks": [look_summary(CTX)]}],
        "actions": [{"node_id": "n1", "round": 1, "action_type": "type", "decision": "approved",
                     "result_status": "dry_run", "approval_id": "SHOULD-NOT-LEAK"}],
        "verifications": [{"node": "Notepad: write", "passed": True, "executed": False, "method": "rule",
                           "reason": "wiring only", "confidence": 0.5}],
    }


def test_default_trace_hides_screen_text():
    t = build_trace(_state(), {"headline": "Not actually done"})
    blob = json.dumps(t)
    assert "secret.txt" not in blob and "my private words" not in blob and "private target" not in blob
    assert t["redacted"] is True
    assert "SHOULD-NOT-LEAK" not in blob                       # only whitelisted action fields are exported


def test_full_trace_keeps_text_only_when_asked():
    t = build_trace(_state(), {}, full=True)
    assert "secret.txt" in json.dumps(t) and t["redacted"] is False


def test_dry_run_is_never_upgraded():
    t = build_trace(_state(), {"headline": "x"})
    assert t["nodes"][0]["status"] == "dry_run" and t["final_status"] == "dry_run"
    assert t["execution_mode"] == "dry_run"
    assert t["nodes"][0]["verification"][0]["executed"] is False
    assert len(t["nodes"][0]["looks"]) == 1 and t["nodes"][0]["actions"][0]["action_type"] == "type"


def test_html_is_self_contained_and_safe(tmp_path):
    state = _state()
    state["goal"] = "</script><b>x</b>"
    paths = write_trace(state, {"headline": "h"}, out_dir=str(tmp_path))
    page = open(paths["html"], encoding="utf-8").read()
    assert "nelly.run_trace.v1" in page and "</script><b>" not in page
    assert "https://" not in page.replace("https://claude.ai", "")      # no network, no fonts, no CDN
    assert "/*__RUN_DATA__*/" not in page
    assert "FAKE SAMPLE" not in make_html(None)                          # no invented data in the page
    assert (tmp_path / "latest.html").exists() and (tmp_path / "index.html").exists()
    idx = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "run_t1.html" in idx and "<b>x</b>" not in idx                # the task text is escaped


def test_timeline_is_carried_into_the_trace():
    rows = [{"step": "director", "info": "plan with 1 node(s)", "at_seconds": 1.2}]
    t = build_trace(_state(), {}, timeline=rows)
    assert t["timeline"] == rows
