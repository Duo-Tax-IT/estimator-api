from functools import lru_cache
from pathlib import Path


@lru_cache
def get_base_prompt(prompt_file: str) -> str:
    """Read the estimator prompt template from a local text file.

    A bare/relative name is resolved against the `prompts/` folder at the service
    root (estimator-api/prompts/). Cached so the file is read once per path.
    """
    path = Path(prompt_file)
    if not path.is_absolute():
        # service root = estimator-api/ (one level up from app/)
        path = Path(__file__).resolve().parent.parent / "prompts" / path
    return path.read_text(encoding="utf-8").strip()
