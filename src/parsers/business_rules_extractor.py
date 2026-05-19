"""
business_rules_extractor.py
============================
Extracts IF/EVALUATE predicates from COBOL programs.

WHAT IT EXTRACTS:
    - IF conditions with THEN/ELSE summaries
    - EVALUATE subjects with WHEN clauses
    - Line numbers and paragraph context
    - Loads into business_rules DuckDB table

DOWNSTREAM CONSUMERS:
    - GET /businessrules/{program_uuid} API endpoint
    - LLM spec generator (business logic context)
"""

import re
import json
import uuid as uuid_lib
import duckdb
from pathlib import Path
from typing import Optional
from collections import defaultdict

from src.utils.logger import get_logger, PipelineEventLog

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import CORPUS_DIR, OUT_DIR

logger = get_logger("parsers.business_rules_extractor")

DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"

# IF pattern — captures condition after IF
IF_PATTERN = re.compile(
    r'^\s+IF\s+(.+?)(?:\s+THEN)?\s*$',
    re.IGNORECASE
)

# EVALUATE pattern
EVALUATE_PATTERN = re.compile(
    r'^\s+EVALUATE\s+(.+?)\s*$',
    re.IGNORECASE
)

# WHEN pattern
WHEN_PATTERN = re.compile(
    r'^\s+WHEN\s+(.+?)\s*$',
    re.IGNORECASE
)

# PERFORM/MOVE after IF (THEN action)
THEN_PATTERN = re.compile(
    r'^\s+(PERFORM|MOVE|COMPUTE|ADD|SUBTRACT|SET|DISPLAY|CALL)\s+(.+?)\s*$',
    re.IGNORECASE
)

# Paragraph pattern
PARA_PATTERN = re.compile(
    r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$',
    re.IGNORECASE
)


def extract_rules_from_file(cbl_file: Path) -> list[dict]:
    """Extract IF/EVALUATE business rules from one COBOL file."""
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()

    program_name  = cbl_file.stem.upper()
    rules         = []
    current_para  = "MAIN"
    in_procedure  = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip comments
        if len(line) > 6 and line[6] in ("*", "/"):
            i += 1
            continue

        stripped = line.strip()

        # Track PROCEDURE DIVISION
        if "PROCEDURE DIVISION" in stripped.upper():
            in_procedure = True
            i += 1
            continue

        # Track paragraph
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
            i += 1
            continue

        if not in_procedure:
            i += 1
            continue

        # IF statement
        if_m = IF_PATTERN.match(line)
        if if_m:
            predicate = if_m.group(1).strip()

            # Look ahead for THEN action (next non-empty line)
            then_summary = ""
            else_summary = ""
            j = i + 1
            while j < len(lines) and j < i + 5:
                next_line = lines[j].strip()
                if next_line and not next_line.startswith("*"):
                    then_m = THEN_PATTERN.match(lines[j])
                    if then_m:
                        then_summary = f"{then_m.group(1)} {then_m.group(2)[:40]}"
                    break
                j += 1

            # Look for ELSE
            k = j + 1
            while k < len(lines) and k < i + 10:
                next_line = lines[k].strip().upper()
                if next_line.startswith("ELSE"):
                    # Get action after ELSE
                    if k + 1 < len(lines):
                        else_m = THEN_PATTERN.match(lines[k + 1])
                        if else_m:
                            else_summary = f"{else_m.group(1)} {else_m.group(2)[:40]}"
                    break
                if next_line.startswith("END-IF") or next_line.startswith("IF "):
                    break
                k += 1

            rule_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
            rules.append({
                "uuid":          rule_id,
                "program":       program_name,
                "source_file":   cbl_file.name,
                "kind":          "IF",
                "predicate_raw": predicate[:200],
                "then_summary":  then_summary[:100],
                "else_summary":  else_summary[:100],
                "paragraph":     current_para,
                "line":          i + 1,
            })

        # EVALUATE statement
        eval_m = EVALUATE_PATTERN.match(line)
        if eval_m:
            subject = eval_m.group(1).strip()
            whens   = []

            # Collect WHEN clauses
            j = i + 1
            while j < len(lines) and j < i + 30:
                when_m = WHEN_PATTERN.match(lines[j])
                if when_m:
                    whens.append(when_m.group(1).strip()[:60])
                elif "END-EVALUATE" in lines[j].upper():
                    break
                j += 1

            rule_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
            rules.append({
                "uuid":          rule_id,
                "program":       program_name,
                "source_file":   cbl_file.name,
                "kind":          "EVALUATE",
                "predicate_raw": f"EVALUATE {subject}" + (f" WHEN {whens[0]}" if whens else ""),
                "then_summary":  f"{len(whens)} WHEN clauses",
                "else_summary":  "",
                "paragraph":     current_para,
                "line":          i + 1,
            })

        i += 1

    return rules


def run(corpus_dir: Optional[Path] = None) -> dict:
    """Extract business rules from all COBOL files and load into DuckDB."""
    corpus_dir = corpus_dir or (CORPUS_DIR / "app" / "cbl")

    event_log  = PipelineEventLog("business_rules_extractor")
    all_rules  = []

    cbl_files = sorted(corpus_dir.glob("*.cbl"))
    logger.info(f"Extracting business rules from {len(cbl_files)} files")

    for cbl_file in cbl_files:
        rules = extract_rules_from_file(cbl_file)
        if rules:
            all_rules.extend(rules)
            event_log.log_success(
                cbl_file.name,
                details={"rules": len(rules)}
            )

    logger.info(f"Total rules extracted: {len(all_rules)}")

    # Load into DuckDB
    conn = duckdb.connect(str(DB_PATH))
    try:
        rows = [
            (
                r["uuid"],
                r["program"],
                r["kind"],
                r["predicate_raw"],
                json.dumps({}),
                r["then_summary"],
                r["else_summary"],
                r["source_file"],
                r["line"],
            )
            for r in all_rules
        ]
        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO business_rules
                (uuid, program_uuid, kind, predicate_raw, predicate_resolved,
                 then_summary, else_summary, source_file, line_num)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, rows)
        logger.info(f"Loaded {len(rows)} business rules into DuckDB")
    finally:
        conn.close()

    event_log.save()

    # Save artifact
    output_dir = OUT_DIR / "artifacts" / "layer5"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "business_rules.json"

    by_program = defaultdict(list)
    for r in all_rules:
        by_program[r["program"]].append(r)

    artifact = {
        "layer":        "L5",
        "total_rules":  len(all_rules),
        "programs":     len(by_program),
        "by_kind": {
            "IF":       sum(1 for r in all_rules if r["kind"] == "IF"),
            "EVALUATE": sum(1 for r in all_rules if r["kind"] == "EVALUATE"),
        },
        "rules": all_rules,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"Business rules saved: {output_path}")
    return artifact


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "total_rules":  result["total_rules"],
        "programs":     result["programs"],
        "by_kind":      result["by_kind"],
    }, indent=2))
    print("\nSample rules from COTRN02C:")
    for r in result["rules"]:
        if r["program"] == "COTRN02C" and r["kind"] == "IF":
            print(f"  Line {r['line']:4} [{r['paragraph']}]")
            print(f"    IF {r['predicate_raw'][:60]}")
            if r["then_summary"]:
                print(f"    THEN: {r['then_summary']}")
            break
