"""The v2 AI chain — one module per step (link).

Each step takes its inputs, loads its prompt, calls the model, and parses the
JSON reply (via the shared `_parse`). Steps know nothing about pricing or the
response shape; they only turn inputs into a parsed model output.
"""
from .era import ERA_PROMPT_FILE, run_era
from .match import CANDIDATES_PROMPT_FILE, run_match
from .observe import OBSERVE_PROMPT_FILE, run_observe
from .structure import STRUCTURE_PROMPT_FILE, run_structure
from .support import SUPPORT_PROMPT_FILE, run_support

__all__ = [
    "OBSERVE_PROMPT_FILE",
    "ERA_PROMPT_FILE",
    "SUPPORT_PROMPT_FILE",
    "CANDIDATES_PROMPT_FILE",
    "STRUCTURE_PROMPT_FILE",
    "run_observe",
    "run_era",
    "run_support",
    "run_match",
    "run_structure",
]
