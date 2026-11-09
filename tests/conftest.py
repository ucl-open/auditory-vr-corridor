import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# gen_session.py imports helpers by plain name, as it is run from inside gen-sessions, so that folder has to be importable.
# src is added last, so an installed ucl_open_auditory_vr_corridor (uv sync) wins and src is only a fallback when it is not installed.
sys.path.insert(0, str(REPO_ROOT / "gen-sessions"))
sys.path.append(str(REPO_ROOT / "src"))


@pytest.fixture
def scripted_input(monkeypatch):
    '''
    Replaces input() with a list of answers, given in order, and returns the list of prompts it was asked. Fails the test if input() is asked more often
    than scripted, rather than hanging on a real prompt.
    '''
    def script(*answers):
        remaining = list(answers)
        prompts = []

        def fake_input(prompt=""):
            prompts.append(prompt)
            if not remaining:
                raise AssertionError(f"input() asked more often than scripted, last prompt: {prompt!r}")
            return remaining.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)
        return prompts
    return script
