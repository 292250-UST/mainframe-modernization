"""
file_io_extractor.py
====================
Extracts file I/O operations from COBOL programs.

WHAT IT EXTRACTS:
    READ, WRITE, REWRITE, DELETE, START, OPEN, CLOSE
    with the file name and paragraph context.

DOWNSTREAM CONSUMERS:
    - file_io table in DuckDB
    - file dependency graph
    - migration risk (identifies files programs depend on)
"""

import re
import json
from pathlib import Path
from typing import Optional
from collections import defaultdict

from src.utils.logger import get_logger, PipelineEventLog

import sys
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import CORPUS_DIR, OUT_DIR

logger = get_logger("parsers.file_io_extractor")

# File I/O verb pattern
FILE_IO_PATTERN = re.compile(
    r'^\s+(READ|WRITE|REWRITE|DELETE|START|OPEN|CLOSE)\s+([A-Z0-9][A-Z0-9-]+)',
    re.IGNORECASE
)

# OPEN mode pattern: OPEN INPUT/OUTPUT/I-O/EXTEND file
OPEN_PATTERN = re.compile(
    r'OPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+([A-Z0-9][A-Z0-9-]+)',
    re.IGNORECASE
)

# Paragraph pattern
PARA_PATTERN = re.compile(
    r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$',
    re.IGNORECASE
)

# Map verbs to operation types
OPERATION_MAP = {
    "READ":    "READ",
    "WRITE":   "WRITE",
    "REWRITE": "REWRITE",
    "DELETE":  "DELETE",
    "START":   "START",
    "OPEN":    "OPEN",
    "CLOSE":   "CLOSE",
}


def extract_file_io_from_file(cbl_file: Path) -> list[dict]:
    """
    Extract all file I/O operations from one COBOL file.

    Args:
        cbl_file: Path to .cbl file

    Returns:
        List of file I/O records
    """
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()
    results = []

    program_name = cbl_file.stem.upper()
    current_para = "MAIN"
    in_procedure = False

    for i, line in enumerate(lines):
        # Skip comment lines
        if len(line) > 6 and line[6] in ("*", "/"):
            continue

        stripped = line.strip().upper()

        # Track when we enter PROCEDURE DIVISION
        if "PROCEDURE DIVISION" in stripped:
            in_procedure = True
            continue

        # Track paragraph
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
            continue

        # Only extract I/O from PROCEDURE DIVISION
        if not in_procedure:
            continue

        # Check OPEN with mode
        open_m = OPEN_PATTERN.search(line)
        if open_m:
            mode    = open_m.group(1).upper()
            file_nm = open_m.group(2).upper()
            results.append({
                "program":     program_name,
                "file_name":   file_nm,
                "operation":   f"OPEN_{mode}",
                "paragraph":   current_para,
                "line":        i + 1,
                "source_file": cbl_file.name,
            })
            continue

        # Check other I/O verbs
        io_m = FILE_IO_PATTERN.match(line)
        if io_m:
            verb    = io_m.group(1).upper()
            file_nm = io_m.group(2).upper()

            # Skip OPEN (already handled above)
            if verb == "OPEN":
                continue

            # Filter out false positives (reserved words)
            if file_nm in {"INTO", "FROM", "NEXT", "KEY", "AT", "END"}:
                continue

            results.append({
                "program":     program_name,
                "file_name":   file_nm,
                "operation":   OPERATION_MAP.get(verb, verb),
                "paragraph":   current_para,
                "line":        i + 1,
                "source_file": cbl_file.name,
            })

    return results


def run(corpus_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None) -> dict:
    """Run file I/O extraction on all COBOL files."""
    corpus_dir = corpus_dir or (CORPUS_DIR / "app" / "cbl")
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer4")
    output_dir.mkdir(parents=True, exist_ok=True)

    event_log  = PipelineEventLog("file_io_extractor")
    all_ops    = []

    cbl_files = sorted(corpus_dir.glob("*.cbl"))
    logger.info(f"Extracting file I/O from {len(cbl_files)} files")

    for cbl_file in cbl_files:
        ops = extract_file_io_from_file(cbl_file)
        if ops:
            all_ops.extend(ops)
            event_log.log_success(
                cbl_file.name,
                details={"io_count": len(ops)}
            )

    # Summary by program
    by_program = defaultdict(list)
    for op in all_ops:
        by_program[op["program"]].append(op)

    # Summary by file
    by_file = defaultdict(set)
    for op in all_ops:
        by_file[op["file_name"]].add(op["program"])

    summary = {
        "total_operations": len(all_ops),
        "programs_with_io": len(by_program),
        "unique_files":     len(by_file),
        "by_verb":          {},
        "most_shared_files": [
            {"file": f, "programs": len(progs)}
            for f, progs in sorted(by_file.items(), key=lambda x: -len(x[1]))[:10]
        ]
    }

    # Count by verb
    for op in all_ops:
        verb = op["operation"]
        summary["by_verb"][verb] = summary["by_verb"].get(verb, 0) + 1

    artifact = {
        "layer":      "L4",
        "summary":    summary,
        "operations": all_ops,
    }

    output_path = output_dir / "file_io.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    event_log.save()
    logger.info(
        f"File I/O extraction: {len(all_ops)} operations, "
        f"{len(by_program)} programs, {len(by_file)} unique files"
    )
    return artifact


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], indent=2))
