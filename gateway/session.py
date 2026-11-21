"""
Session: the user's side of the agent (text for now).

    s = Session()
    out = s.submit("write a note in Notepad")     # -> {"kind": "report", ...}
    s.submit("stop")                              # stop works from another thread / GUI too

What it adds on top of the graph:
  * one session_id for the whole conversation (a new task_id per request)
  * a stop command ("stop", "cancel", "وقف", "الغي" as the WHOLE message) and Ctrl+C
  * when the run ended with a question for the user, the next message is the ANSWER to it
  * a plain end-of-task report that never says "done" unless the state says so
"""
import re
import sys
import uuid

from gateway.gateway import normalize_task
from gateway.report import final_report, render
from graph import control, safety_port

STOP_WORDS = {"stop", "cancel", "abort", "وقف", "قف", "الغي", "الغاء", "إلغاء", "ايقاف", "إيقاف"}
EXIT_WORDS = {"exit", "quit", "خروج", "اخرج"}


def _clean(text: str) -> str:
    return re.sub(r"[\s\.\!\?\؟،,]+", " ", (text or "").strip().lower()).strip()


def parse_command(text: str):
    """'cancel' | 'exit' | None. Only a message that is JUST the command counts, so a request such
    as "open the player and stop the music" is never mistaken for a stop."""
    t = _clean(text)
    if t in STOP_WORDS:
        return "cancel"
    if t in EXIT_WORDS:
        return "exit"
    return None


class Session:
    def __init__(self, graph=None, approver="auto", on_event=None, allow_task=False):
        if graph is None:
            from graph.builder import build_graph
            graph = build_graph()
        self.graph = graph
        self.session_id = str(uuid.uuid4())
        self.on_event = on_event
        self.history = []                # one report per finished task
        self.pending = None              # {"goal", "question"} while waiting for the user's answer
        self.allow_task = bool(allow_task)   # the user allowed this whole task up front (not delete/send/pay)
        self.running = False
        if approver == "auto":           # a person at the terminal can answer approvals
            approver = safety_port.console_approver if sys.stdin.isatty() else None
        self.approver = approver

    # ------------------------------------------------------------ public
    def submit(self, text: str) -> dict:
        cmd = parse_command(text)
        if cmd == "exit":
            return {"kind": "exit"}
        if cmd == "cancel":
            if self.running:
                control.cancel()
                return {"kind": "info", "text": "stopping after the current action"}
            self.pending = None
            return {"kind": "info", "text": "nothing is running"}
        if not (text or "").strip():
            return {"kind": "info", "text": "empty message"}

        goal = text.strip()
        low = goal.lower()
        for prefix in ("allow:", "/allow "):                  # the user's own words, never the model's
            if low.startswith(prefix):
                goal = goal[len(prefix):].strip()
                text = goal
                self.allow_task = True
                break
        if not goal:
            return {"kind": "info", "text": "allow: needs a task after it"}
        if self.pending:                 # the user is answering our question
            q = self.pending
            self.pending = None
            goal = f"{q['goal']} (Question asked: {q['question']} Answer from the user: {goal})"
        return self._run(goal, shown=text.strip())

    def cancel(self):
        """For a GUI or a voice command: stop the next action."""
        control.cancel()

    # ------------------------------------------------------------ run
    def _run(self, goal: str, shown: str) -> dict:
        control.reset()
        init = normalize_task(goal, source="text", session_id=self.session_id)
        config = {"configurable": {"thread_id": init["task_id"]}}
        self.running = True
        safety_port.grant_task(self.allow_task)
        try:
            with safety_port.bind_approver(self.approver):
                for event in self.graph.stream(init, config=config):
                    if self.on_event:
                        self.on_event(event)
            final = dict(self.graph.get_state(config).values)
        except KeyboardInterrupt:
            control.cancel()
            final = {**init, "status": "cancelled", "cancelled": True}
        finally:
            self.running = False
            safety_port.grant_task(False)

        final.setdefault("language", init["language"])
        report = final_report(final)
        report["task_id"] = init["task_id"]
        if report["needs_user"]:
            self.pending = {"goal": goal, "question": report["question"]}   # a retry keeps the permission
        else:
            self.allow_task = False
        self.history.append(report)
        return {"kind": "report", "report": report, "text": render(report), "state": final}
