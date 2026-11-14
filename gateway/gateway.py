"""
Task Gateway — turns what the user said or typed into a TaskRequest, and (for voice) into text.

The returned TaskRequest IS the seed AgentState, so every key the graph reads on its first node
must already exist here.
"""
import re
import uuid
from typing import Dict, Optional


def detect_language(text: str) -> str:
    """'ar' when most letters are Arabic, else 'en'. Used to answer in the user's language."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    arabic = sum(1 for c in letters if "؀" <= c <= "ۿ")
    return "ar" if arabic * 2 >= len(letters) else "en"


def normalize_task(text: str, source: str = "text", session_id: str = None,
                   task_id: str = None, language: Optional[str] = None) -> Dict:
    """Entry point for the Orchestrator. `text` is typed text or a confirmed voice transcript."""
    if not text or not text.strip():
        raise ValueError("empty task")
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "task_id": task_id or str(uuid.uuid4()),
        "session_id": session_id or str(uuid.uuid4()),
        "goal": text,
        "task_source": source,  # voice | text
        "language": language or detect_language(text),
        "status": "planning",
        "current_step": 0,
        "current_node_idx": 0,
        "nodes": [],
        "sub_results": [],
    }


# ----------------------------------------------------------------- voice (later)
def transcribe(audio_path: str) -> str:
    """Voice boundary: NOT wired yet, on purpose. The agent takes text for now.

    It raises instead of returning a canned sentence: a stub that "hears" something would make
    the whole pipeline look like it understood audio it never heard. When voice comes, the
    transcript must be confirmed by the user before anything runs.
    """
    raise NotImplementedError(f"Voice is not wired yet: pass text instead of an audio file ({audio_path!r}).")
