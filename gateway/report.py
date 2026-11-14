"""
End-of-task report: what really happened, in the user's language.

It only restates the final state. It never upgrades it: `dry_run` is not "done",
`escalated` is a question for the user, and `completed` is said only when the state says so.
"""

T = {
    "ar": {
        "completed": "تم. كل خطوة اتأكدت من الشاشة.",
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


def final_report(state: dict) -> dict:
    lang = state.get("language") if state.get("language") in T else "en"
    t = T[lang]
    status = state.get("status") or "unknown"
    esc = state.get("escalation") or {}
    why = esc.get("reason") or state.get("escalation_reason") or state.get("error") or t["unknown"]
    key = status if status in t else "incomplete"
    headline = t[key].format(why=why) if "{why}" in t[key] else t[key]

    nodes = [{"node": n.get("node"), "app": n.get("app"), "status": n.get("status", "pending")}
             for n in (state.get("nodes") or [])]
    needs_user = status == "escalated" and bool(state.get("requires_user", True))
    return {
        "status": status,
        "headline": headline,
        "language": lang,
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
