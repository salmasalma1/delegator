"""Old first-word step parser, kept ONLY as the no-model fallback of action_decider."""
_STEP_ACTION = (("type ", "type"), ("write ", "type"), ("click ", "click"),
                ("press ", "press"), ("open ", "click"), ("save", "save_file"),
                ("create folder", "create_folder"), ("focus", "focus_window"))


def action_for(step: str) -> str:
    low = (step or "").strip().lower()
    for prefix, action in _STEP_ACTION:
        if low.startswith(prefix):
            return action
    return "click"


def action_params(step: str, action: str, element: dict) -> dict:
    low = (step or "").strip()
    if action == "type":
        text = low
        for p in ("type ", "write ", "enter "):
            if low.lower().startswith(p):
                text = low[len(p):].strip().strip('"\'')
                break
        return {"text": text, "bbox_norm": element["bbox_norm"]}
    if action == "press":
        keys = low.split(" ", 1)[1] if " " in low else low
        return {"keys": [k.strip().lower() for k in keys.split("+")]}
    return {"bbox_norm": element["bbox_norm"]}
