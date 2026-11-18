"""Test helper: makes Team 1's vision package (contracts, nelly_vision) look NOT installed.

Python imports `sitecustomize` at start-up from the path, so putting this folder first on PYTHONPATH blocks those
imports in that process and in every test it starts. Used by tests/run_without_team1.py and
tests/test_team1_missing.py; the application code never imports it.
"""
import sys

BLOCKED = ("contracts", "nelly_vision")


class _BlockTeam1:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r} (blocked by tests/no_team1)", name=name)
        return None


sys.meta_path.insert(0, _BlockTeam1())
