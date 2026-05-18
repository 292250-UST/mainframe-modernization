"""
exec_cics_extractor.py
======================
Extracts all EXEC CICS statements from COBOL programs.

WHAT IT EXTRACTS:
    Every EXEC CICS verb with:
    - Verb (SEND, RETURN, XCTL, READ, etc.)
    - Parameters (MAP, MAPSET, TRANSID, DATASET, etc.)
    - Source file + line number
    - Parent paragraph name

VERBS FOUND IN CARDDEMO (20 total):
    SEND, RETURN, XCTL, READ, RECEIVE, HANDLE,
    STARTBR, READPREV, ENDBR, REWRITE, ABEND,
    READNEXT, SYNCPOINT, WRITE, ASSIGN, ASKTIME,
    FORMATTIME, INQUIRE, WRITEQ, DELETE

DOWNSTREAM CONSUMERS:
    - transaction_flow table (XCTL/LINK edges)
    - screen_map table (SEND MAP/RECEIVE MAP)
    - file_io table (READ/WRITE/REWRITE/DELETE)
    - migration_risk table (ABEND, HANDLE ABEND)
"""

import re
import json
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger, PipelineEventLog

import sys
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import CORPUS_DIR, OUT_DIR

logger = get_logger("parsers.exec_cics_extractor")

# Pattern to find EXEC CICS blocks
# EXEC CICS verb ... END-EXEC
EXEC_CICS_START = re.compile(r'EXEC\s+CICS\s+(\w+)', re.IGNORECASE)
END_EXEC        = re.compile(r'END-EXEC', re.IGNORECASE)

# Key parameter patterns
PARAM_PATTERNS = {
    "MAP":      re.compile(r'\bMAP\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "MAPSET":   re.compile(r'\bMAPSET\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "TRANSID":  re.compile(r'\bTRANSID\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "DATASET":  re.compile(r'\bDATASET\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "FILE":     re.compile(r'\bFILE\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "PROGRAM":  re.compile(r'\bPROGRAM\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "COMMAREA": re.compile(r'\bCOMMARREA\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "QUEUE":    re.compile(r'\bQUEUE\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "ABCODE":   re.compile(r'\bABCODE\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
    "CONDITION":re.compile(r'\bCONDITION\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
}

# Paragraph definition pattern
PARA_PATTERN = re.compile(
    r'^[ ]{6,}([A-Z0-9][A-Z0-9-]{0,29})\s*\.',
    re.IGNORECASE | re.MULTILINE
)


def _extract_params(block: str) -> dict:
    """Extract key parameters from an EXEC CICS block."""
    params = {}
    for key, pattern in PARAM_PATTERNS.items():
        m = pattern.search(block)
        if m:
            params[key] = m.group(1).strip().strip("'\"")
    return params


def _find_current_paragraph(lines: list[str], line_num: int) -> str:
    """Find which paragraph contains the given line number."""
    current_para = "UNKNOWN"
    for i in range(line_num - 1, -1, -1):
        line = lines[i]
        # Paragraph definition: starts in Area A (col 8), ends with period
        stripped = line.strip()
        if stripped and not stripped.startswith("*"):
            # Check if it looks like a paragraph name
            m = re.match(r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$',
                         line, re.IGNORECASE)
            if m:
                current_para = m.group(1).upper()
                break
    return current_para


def extract_cics_from_file(cbl_file: Path) -> list[dict]:
    """
    Extract all EXEC CICS statements from one COBOL file.

    Args:
        cbl_file: Path to .cbl file

    Returns:
        List of CICS statement records
    """
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()
    results = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Find EXEC CICS start
        m = EXEC_CICS_START.search(line)
        if m:
            verb       = m.group(1).upper()
            start_line = i + 1  # 1-indexed
            block_lines = [line]

            # Collect lines until END-EXEC
            j = i + 1
            while j < len(lines) and not END_EXEC.search(lines[j]):
                block_lines.append(lines[j])
                j += 1
            if j < len(lines):
                block_lines.append(lines[j])  # include END-EXEC line

            block = " ".join(block_lines)

            # Extract parameters
            params = _extract_params(block)

            # Find parent paragraph
            para = _find_current_paragraph(lines, i)

            record = {
                "verb":        verb,
                "source_file": cbl_file.name,
                "line":        start_line,
                "paragraph":   para,
                "params":      params,
                "raw":         block.strip()[:200],
            }
            results.append(record)
            i = j + 1
        else:
            i += 1

    return results


def run(corpus_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None) -> dict:
    """
    Extract EXEC CICS from all COBOL files.

    Returns:
        dict with all CICS statements grouped by verb
    """
    corpus_dir = corpus_dir or (CORPUS_DIR / "app" / "cbl")
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer3")
    output_dir.mkdir(parents=True, exist_ok=True)

    event_log  = PipelineEventLog("exec_cics_extractor")
    all_stmts  = []
    by_verb    = {}

    cbl_files = sorted(corpus_dir.glob("*.cbl"))
    logger.info(f"Extracting EXEC CICS from {len(cbl_files)} files")

    for cbl_file in cbl_files:
        stmts = extract_cics_from_file(cbl_file)
        if stmts:
            all_stmts.extend(stmts)
            event_log.log_success(
                cbl_file.name,
                details={"cics_count": len(stmts)}
            )
            logger.debug(f"{cbl_file.name}: {len(stmts)} EXEC CICS statements")

    # Group by verb
    for stmt in all_stmts:
        verb = stmt["verb"]
        if verb not in by_verb:
            by_verb[verb] = []
        by_verb[verb].append(stmt)

    # Build summary
    summary = {
        "total_statements": len(all_stmts),
        "unique_verbs":     len(by_verb),
        "files_with_cics":  len(set(s["source_file"] for s in all_stmts)),
        "verb_counts":      {v: len(s) for v, s in sorted(
                                by_verb.items(),
                                key=lambda x: -len(x[1]))},
    }

    artifact = {
        "layer":      "L3",
        "summary":    summary,
        "statements": all_stmts,
    }

    output_path = output_dir / "cics_statements.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    event_log.save()

    logger.info(
        f"EXEC CICS extraction complete: "
        f"{len(all_stmts)} statements, "
        f"{len(by_verb)} unique verbs, "
        f"{summary['files_with_cics']} files"
    )
    return artifact


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], indent=2))
