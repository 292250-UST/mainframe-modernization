"""
exec_dli_extractor.py
=====================
Extracts EXEC DLI statements from COBOL programs.

EXEC DLI verbs found in CardDemo extension:
    SCHD  - Schedule PSB (initialize IMS connection)
    TERM  - Terminate IMS connection
    GU    - Get Unique (read by key)
    GN    - Get Next
    GNP   - Get Next in Parent
    REPL  - Replace (update) segment
    ISRT  - Insert segment
    DLET  - Delete segment

Parameters extracted:
    USING PCB(name)     - PCB number
    SEGMENT(name)       - IMS segment name
    WHERE(field=value)  - Key qualification
"""

import re
import json
from pathlib import Path
from typing import Optional
from collections import Counter

from src.utils.logger import get_logger, PipelineEventLog

import sys
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("parsers.exec_dli_extractor")

# EXEC DLI block pattern
DLI_START   = re.compile(r'EXEC\s+DLI\s+(\w+)', re.IGNORECASE)
END_EXEC    = re.compile(r'END-EXEC', re.IGNORECASE)

# Parameter patterns
PCB_PATTERN     = re.compile(r'USING\s+PCB\s*\(\s*([^)]+)\s*\)', re.IGNORECASE)
SEGMENT_PATTERN = re.compile(r'SEGMENT\s*\(\s*([^)]+)\s*\)', re.IGNORECASE)
WHERE_PATTERN   = re.compile(r'WHERE\s*\(\s*([^)]+)\s*\)', re.IGNORECASE)
PSB_PATTERN     = re.compile(r'PSB\s*\(\s*\(?([^)]+)\)?\s*\)', re.IGNORECASE)

# Paragraph pattern
PARA_PATTERN = re.compile(
    r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$',
    re.IGNORECASE
)


def extract_dli_from_file(cbl_file: Path) -> list[dict]:
    """Extract all EXEC DLI statements from one COBOL file."""
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()
    results = []
    current_para = "MAIN"

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip comments
        if len(line) > 6 and line[6] in ("*", "/"):
            i += 1
            continue

        # Track paragraph
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
            i += 1
            continue

        # Find EXEC DLI
        m = DLI_START.search(line)
        if m:
            verb       = m.group(1).upper()
            start_line = i + 1
            block_lines = [line]

            # Collect until END-EXEC
            j = i + 1
            while j < len(lines) and not END_EXEC.search(lines[j]):
                block_lines.append(lines[j])
                j += 1
            if j < len(lines):
                block_lines.append(lines[j])

            block = " ".join(block_lines)

            # Extract parameters
            pcb_m     = PCB_PATTERN.search(block)
            seg_m     = SEGMENT_PATTERN.search(block)
            where_m   = WHERE_PATTERN.search(block)
            psb_m     = PSB_PATTERN.search(block)

            results.append({
                "verb":        verb,
                "source_file": cbl_file.name,
                "program":     cbl_file.stem.upper(),
                "line":        start_line,
                "paragraph":   current_para,
                "pcb":         pcb_m.group(1).strip() if pcb_m else "",
                "segment":     seg_m.group(1).strip() if seg_m else "",
                "where":       where_m.group(1).strip() if where_m else "",
                "psb":         psb_m.group(1).strip() if psb_m else "",
                "raw":         block.strip()[:200],
            })
            i = j + 1
        else:
            i += 1

    return results


def run(ext_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None) -> dict:
    """Extract EXEC DLI from all extension COBOL files."""
    ext_dir    = ext_dir or Path("corpus/app/app-authorization-ims-db2-mq/cbl")
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer3")
    output_dir.mkdir(parents=True, exist_ok=True)

    event_log = PipelineEventLog("exec_dli_extractor")
    all_stmts = []

    cbl_files = sorted(
        list(ext_dir.glob("*.cbl")) + list(ext_dir.glob("*.CBL"))
    )
    logger.info(f"Extracting EXEC DLI from {len(cbl_files)} files")

    for cbl_file in cbl_files:
        stmts = extract_dli_from_file(cbl_file)
        if stmts:
            all_stmts.extend(stmts)
            event_log.log_success(
                cbl_file.name,
                details={"dli_count": len(stmts)}
            )

    # Verb summary
    verb_counts = Counter(s["verb"] for s in all_stmts)

    summary = {
        "total_statements": len(all_stmts),
        "unique_verbs":     len(verb_counts),
        "files_with_dli":   len(set(s["source_file"] for s in all_stmts)),
        "verb_counts":      dict(verb_counts.most_common()),
        "segments_accessed": list(set(
            s["segment"] for s in all_stmts if s["segment"]
        )),
    }

    artifact = {
        "layer":      "L3",
        "summary":    summary,
        "statements": all_stmts,
    }

    output_path = output_dir / "dli_statements.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    event_log.save()
    logger.info(
        f"EXEC DLI extraction: {len(all_stmts)} statements, "
        f"{len(verb_counts)} verbs, "
        f"{summary['files_with_dli']} files"
    )
    return artifact


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], indent=2))
