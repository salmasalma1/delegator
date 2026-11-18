"""Team 2 shim for Team 1's `vision_path` helper.

Team 1's package (nelly_vision, contracts) is already importable in delegator's .venv through
site-packages/nelly_vision_path.pth, so there is nothing to add to sys.path here.
"""


def ensure_vision_on_path():
    return None
