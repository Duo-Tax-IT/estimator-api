from functools import lru_cache
from pathlib import Path


@lru_cache
def get_base_prompt(prompt_file: str) -> str:
    """Read the estimator prompt template from a local text file.

    Resolved relative to the service root if a bare/relative path is given.
    Cached so the file is read once per path.
    """
    path = Path(prompt_file)
    if not path.is_absolute():
        # service root = estimator-api/ (one level up from app/)
        path = Path(__file__).resolve().parent.parent / path
    return path.read_text(encoding="utf-8").strip()
