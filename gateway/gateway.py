"""
Task Gateway — normalizes voice or text into TaskRequest.

"""
from typing import Dict
import uuid


def normalize_task(text: str, source: str = "text", session_id: str = None, task_id: str = None) -> Dict:
    """
    Entry point for Orchestrator. Accepts text from Voice Gateway (Whisper) or direct text.

    The returned dict is not a view model: it IS the seed AgentState, so every key
    the graph reads on its first node must already exist here.
    """
    if not text or not text.strip():
        raise ValueError("empty task")
    return {
        "task_id": task_id or str(uuid.uuid4()),
        "session_id": session_id or str(uuid.uuid4()),
        "goal": text.strip(),
        "task_source": source,  # voice | text
        "status": "planning",
        "current_step": 0,
        "current_node_idx": 0,
        "nodes": [],
        "sub_results": [],
    }


def transcribe(audio_path: str) -> str:
    """Voice boundary. Whisper is not installed on this machine yet.

    Deliberately raises: a stub that returns a canned sentence makes the whole
    pipeline look like it understood audio when it never heard anything.
    Wire whisper.cpp / the Whisper API here, then delete this docstring.
    """
    raise NotImplementedError(
        "Whisper is not wired yet — pass text to normalize_task(text=...) "
        f"instead of an audio file ({audio_path!r})."
    )