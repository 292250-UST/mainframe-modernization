"""
copybook_cache.py
=================
Memoized copybook loader for the CardDemo modernization pipeline.

WHY THIS EXISTS:
    CardDemo has ~62 copybooks shared across ~80 COBOL programs.
    Without caching, parsing 80 programs would read CVACT01Y.cpy
    (for example) dozens of times from disk. This module ensures
    each copybook file is read exactly once per pipeline run.

HOW IT WORKS:
    Uses Python's functools.lru_cache on the load_copybook() function.
    The cache key is (copybook_name, copybook_dir) — both strings
    because lru_cache requires hashable arguments.

USAGE:
    from src.preprocess.copybook_cache import load_copybook
    lines = load_copybook('CVACT01Y', 'corpus/app/cpy')

DOWNSTREAM CONSUMERS:
    - copybook_processor.py  (COPY resolution)
    - provenance_tracker.py  (line-level origin tracking)

KNOWN LIMITATIONS:
    - Cache is process-scoped (cleared on pipeline restart)
    - Does not handle nested copybooks (copybook that COPYs another)
      — this is handled by copybook_processor.py recursively
"""

from pathlib import Path
from functools import lru_cache
from src.utils.logger import get_logger

# Module-level logger — named to match file path for easy log filtering
logger = get_logger("preprocess.copybook_cache")

# ---------------------------------------------------------------------------
# COPYBOOK FILE EXTENSIONS
# ---------------------------------------------------------------------------
# CardDemo uses mixed case extensions (.cpy, .CPY) across different files.
# We try all variants to be robust — order matters (most common first).
COPYBOOK_EXTENSIONS = [".cpy", ".CPY", ".cbl", ".CBL"]


@lru_cache(maxsize=256)
def load_copybook(copybook_name: str, copybook_dir: str) -> list[str] | None:
    """
    Load a copybook file by name and return its lines.

    This function is memoized — the same (copybook_name, copybook_dir)
    combination is only read from disk once per pipeline run.

    Args:
        copybook_name (str): Copybook name WITHOUT extension.
                             Examples: 'CVACT01Y', 'COCOM01Y', 'CODATECN'
        copybook_dir (str):  Path to copybook directory as a STRING
                             (not Path — lru_cache requires hashable args).
                             Example: 'corpus/app/cpy'

    Returns:
        list[str]: Lines of the copybook file (no newlines), or
        None:      If the copybook file cannot be found in any variant.

    Raises:
        Does NOT raise — returns None on failure so callers can handle
        missing copybooks gracefully and log the gap.

    Example:
        >>> lines = load_copybook('CVACT01Y', 'corpus/app/cpy')
        >>> print(len(lines))  # number of lines in the copybook
        42
    """
    cpy_dir = Path(copybook_dir)

    # -----------------------------------------------------------------------
    # Try all extension variants — CardDemo has inconsistent casing
    # Also try uppercase name variant (e.g. 'cvact01y' -> 'CVACT01Y')
    # -----------------------------------------------------------------------
    candidates = []
    for name_variant in [copybook_name, copybook_name.upper()]:
        for ext in COPYBOOK_EXTENSIONS:
            candidates.append(cpy_dir / f"{name_variant}{ext}")

    # Remove duplicates while preserving order
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique_candidates.append(c)

    # -----------------------------------------------------------------------
    # Try each candidate path — return lines from first match found
    # -----------------------------------------------------------------------
    for candidate in unique_candidates:
        if candidate.exists():
            logger.debug(
                f"Cache MISS — loading from disk: {candidate.name} "
                f"(cache size: {load_copybook.cache_info().currsize})"
            )
            # Read with utf-8, replace unmappable chars (EBCDIC artifacts)
            lines = candidate.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            logger.debug(
                f"Loaded {len(lines)} lines from {candidate.name}"
            )
            return lines

    # -----------------------------------------------------------------------
    # Copybook not found — log as GAP (caller must handle)
    # This is a known issue: COTRN02.cpy is missing from CardDemo corpus
    # -----------------------------------------------------------------------
    logger.warning(
        f"Copybook NOT FOUND: '{copybook_name}' "
        f"in directory '{copybook_dir}'. "
        f"Tried: {[c.name for c in unique_candidates]}"
    )
    return None


def clear_cache() -> None:
    """
    Clear the in-memory copybook cache.

    When to use:
        - In tests, to ensure a clean state between test cases
        - If copybook files are modified during a pipeline run (rare)

    Example:
        >>> clear_cache()
        >>> cache_info()  # currsize will be 0
    """
    load_copybook.cache_clear()
    logger.debug("Copybook cache cleared")


def cache_info() -> dict:
    """
    Return current cache statistics as a readable dictionary.

    Returns:
        dict with keys:
            hits     - number of times a cached result was returned
            misses   - number of times disk was read
            maxsize  - maximum cache capacity
            currsize - current number of cached entries

    Example:
        >>> info = cache_info()
        >>> print(f"Cache hits: {info['hits']}, misses: {info['misses']}")
    """
    raw = load_copybook.cache_info()
    return {
        "hits":     raw.hits,
        "misses":   raw.misses,
        "maxsize":  raw.maxsize,
        "currsize": raw.currsize,
    }
