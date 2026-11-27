"""
End-of-task report: what really happened, in the user's language.

It only restates the final state. It never upgrades it: `dry_run` is not "done",
`escalated` is a question for the user, and `completed` is said only when the state says so.
"""

T = {
    "ar": {
        "completed": "تم. كل خطوة اتأكدت من الشاشة.",
        "completed_structural": "الخطوات اتنفذت، بس التحقق كان هيكلي: ما اتأكدتش من الشاشة إن كل خطوة نجحت فعلًا.",
        "dry_run": "المهمة ما اتنفذتش فعليًا: التنفيذ كان تجريبي (dry run) ومفيش حاجة اتعملت على الجهاز.",
        "failed": "المهمة فشلت: {why}",
        "escalated": "المهمة واقفة ومحتاجة قرارك: {why}",
        "cancelled": "المهمة اتوقفت زي ما طلبت.",
        "incomplete": "المهمة ما خلصتش ومفيش دليل على إنها اتعملت.",
        "nodes": "الأهداف الفرعية",
        "ask": "{q}",
        "retry_q": "المهمة وقفت: {why}. أعيد المحاولة، أتخطى الخطوة دي، ولا تكمّلي إنتي؟",
        "unknown": "غير معروف",
    },
    "en": {
        "completed": "Done. Every step was checked on the screen.",
        "completed_structural": "The steps ran, but the check was structural only: I did not confirm on the screen "
                                "that each step really worked.",
        "dry_run": "Not actually done: this was a dry run, nothing happened on the machine.",
        "failed": "I could not do the task: {why}",
        "escalated": "I stopped because I need your decision: {why}",
        "cancelled": "Stopped, as you asked.",
        "incomplete": "The task did not finish and there is no proof it was done.",
        "nodes": "Sub-goals",
        "ask": "{q}",
        "retry_q": "The task stopped: {why}. Retry, skip this step, or take over?",
        "unknown": "unknown",
    },
}


def _question(t: dict, why: str) -> str:
    """A question the planner asked is passed through as is; anything else gets a standard one."""
    marker = "need your input:"
    if why.lower().startswith(marker):
        return why[len(marker):].strip()
    return t["retry_q"].format(why=why)


def screen_checked(state: dict) -> bool:
    """True only when EVERY node of the final plan was confirmed by a check that looked at the screen.

    The structural rule verifier proves wiring, not results (`semantic: False`), so it never earns the words
    "checked on the screen". No nodes, or a node without a passing semantic check, means False."""
    names = [n.get("node") for n in (state.get("nodes") or [])]
    if not names:
        return False
    latest = {}
    for v in state.get("verifications") or []:       # later attempts replace earlier ones for the same node
        if v.get("node") in names:
            latest[v["node"]] = v
    return all(n in latest and latest[n].get("passed") and latest[n].get("semantic") is True for n in names)


def final_report(state: dict) -> dict:
    lang = state.get("language") if state.get("language") in T else "en"
    t = T[lang]
    status = state.get("status") or "unknown"
    esc = state.get("escalation") or {}
    why = esc.get("reason") or state.get("escalation_reason") or state.get("error") or t["unknown"]
    key = status if status in t else "incomplete"
    on_screen = status == "completed" and screen_checked(state)
    if status == "completed" and not on_screen:
        key = "completed_structural"                  # never claim a screen check that did not happen
    headline = t[key].format(why=why) if "{why}" in t[key] else t[key]

    nodes = [{"node": n.get("node"), "app": n.get("app"), "status": n.get("status", "pending")}
             for n in (state.get("nodes") or [])]
    needs_user = status == "escalated" and bool(state.get("requires_user", True))
    return {
        "status": status,
        "headline": headline,
        "language": lang,
        "checked_on_screen": on_screen,
        "nodes": nodes,
        "needs_user": needs_user,
        "question": _question(t, why) if needs_user else None,
        "approvals": [a for a in (state.get("actions") or []) if a.get("approval_scope")],
    }


def render(report: dict) -> str:
    """Plain text for the terminal (or for text-to-speech later)."""
    t = T[report["language"]]
    lines = [report["headline"]]
    if report["nodes"]:
        lines.append(f"{t['nodes']}:")
        lines += [f"  - {n['node']}: {n['status']}" for n in report["nodes"]]
    if report["question"]:
        lines.append(t["ask"].format(q=report["question"]))
    return "\n".join(lines)
