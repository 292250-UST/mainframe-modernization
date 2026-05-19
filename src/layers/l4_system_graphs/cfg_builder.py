"""
cfg_builder.py
==============
Builds intra-program Control Flow Graph from PERFORM statements.

NODES: paragraphs (from paragraphs table)
EDGES: PERFORM statements between paragraphs

EDGE TYPES:
    PERFORM            - unconditional PERFORM
    PERFORM_CONDITIONAL - PERFORM inside IF/EVALUATE
    PERFORM_UNTIL      - PERFORM UNTIL (loop)
    PERFORM_VARYING    - PERFORM VARYING (loop)
    FALLTHROUGH        - sequential to next paragraph
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

logger = get_logger("layers.l4_system_graphs.cfg_builder")

DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"

# PERFORM patterns
PERFORM_SIMPLE   = re.compile(r'^\s+PERFORM\s+([A-Z0-9][A-Z0-9-]{1,29})\s*$', re.IGNORECASE)
PERFORM_THRU     = re.compile(r'^\s+PERFORM\s+([A-Z0-9][A-Z0-9-]{1,29})\s+(?:THROUGH|THRU)\s+([A-Z0-9][A-Z0-9-]{1,29})', re.IGNORECASE)
PERFORM_UNTIL    = re.compile(r'^\s+PERFORM\s+([A-Z0-9][A-Z0-9-]{1,29})\s+UNTIL\s+(.+)', re.IGNORECASE)
PERFORM_VARYING  = re.compile(r'^\s+PERFORM\s+([A-Z0-9][A-Z0-9-]{1,29})\s+VARYING\s+', re.IGNORECASE)
PERFORM_INLINE_UNTIL = re.compile(r'^\s+PERFORM\s+UNTIL\s+', re.IGNORECASE)

# IF pattern for detecting conditional context
IF_PATTERN       = re.compile(r'^\s+IF\s+', re.IGNORECASE)
END_IF_PATTERN   = re.compile(r'^\s+END-IF', re.IGNORECASE)

# Paragraph pattern
PARA_PATTERN     = re.compile(r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$', re.IGNORECASE)

# Reserved words to skip
RESERVED = {"UNTIL", "VARYING", "THROUGH", "THRU", "WITH", "TEST", "TIMES"}


def extract_cfg_from_file(cbl_file: Path) -> dict:
    """Extract CFG edges from one COBOL file."""
    content      = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines        = content.splitlines()
    program_name = cbl_file.stem.upper()

    paragraphs   = []
    edges        = []
    current_para = None
    if_depth     = 0
    in_procedure = False
    i = 0

    while i < len(lines):
        line = lines[i]

        if len(line) > 6 and line[6] in ("*", "/"):
            i += 1
            continue

        stripped = line.strip().upper()

        if "PROCEDURE DIVISION" in stripped:
            in_procedure = True
            i += 1
            continue

        if not in_procedure:
            i += 1
            continue

        # Track paragraphs
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
            paragraphs.append({"name": current_para, "line": i + 1})
            i += 1
            continue

        # Track IF depth for conditional context
        if IF_PATTERN.match(line):
            if_depth += 1
        if END_IF_PATTERN.match(line):
            if_depth = max(0, if_depth - 1)

        if current_para is None:
            i += 1
            continue

        # PERFORM VARYING
        m = PERFORM_VARYING.match(line)
        if m:
            target = PERFORM_VARYING.match(line)
            # Extract target from full line
            parts = line.strip().split()
            if len(parts) >= 2:
                tgt = parts[1].upper()
                if tgt not in RESERVED and len(tgt) > 1:
                    edges.append({
                        "from_para":  current_para,
                        "to_para":    tgt,
                        "edge_type":  "PERFORM_VARYING",
                        "condition":  None,
                        "line":       i + 1,
                        "source_file": cbl_file.name,
                    })
            i += 1
            continue

        # PERFORM UNTIL
        m = PERFORM_UNTIL.match(line)
        if m:
            tgt = m.group(1).upper()
            cond = m.group(2).strip()[:80]
            if tgt not in RESERVED:
                edges.append({
                    "from_para":  current_para,
                    "to_para":    tgt,
                    "edge_type":  "PERFORM_UNTIL",
                    "condition":  cond,
                    "line":       i + 1,
                    "source_file": cbl_file.name,
                })
            i += 1
            continue

        # PERFORM THRU
        m = PERFORM_THRU.match(line)
        if m:
            tgt  = m.group(1).upper()
            thru = m.group(2).upper()
            etype = "PERFORM_CONDITIONAL" if if_depth > 0 else "PERFORM"
            edges.append({
                "from_para":  current_para,
                "to_para":    tgt,
                "edge_type":  etype,
                "condition":  f"THRU {thru}",
                "line":       i + 1,
                "source_file": cbl_file.name,
            })
            i += 1
            continue

        # PERFORM simple
        m = PERFORM_SIMPLE.match(line)
        if m:
            tgt = m.group(1).upper()
            if tgt not in RESERVED:
                etype = "PERFORM_CONDITIONAL" if if_depth > 0 else "PERFORM"
                edges.append({
                    "from_para":  current_para,
                    "to_para":    tgt,
                    "edge_type":  etype,
                    "condition":  None,
                    "line":       i + 1,
                    "source_file": cbl_file.name,
                })
            i += 1
            continue

        i += 1

    return {
        "program":     program_name,
        "source_file": cbl_file.name,
        "paragraphs":  paragraphs,
        "edges":       edges,
    }


def run(corpus_dir: Optional[Path] = None) -> dict:
    """Build CFG for all programs and load into DuckDB."""
    corpus_dir = corpus_dir or (CORPUS_DIR / "app" / "cbl")

    event_log  = PipelineEventLog("cfg_builder")
    all_cfgs   = []
    all_edges  = []

    cbl_files = sorted(corpus_dir.glob("*.cbl"))
    logger.info(f"Building CFG from {len(cbl_files)} files")

    for cbl_file in cbl_files:
        cfg = extract_cfg_from_file(cbl_file)
        all_cfgs.append(cfg)
        all_edges.extend(cfg["edges"])
        event_log.log_success(
            cbl_file.name,
            details={
                "paragraphs": len(cfg["paragraphs"]),
                "edges":      len(cfg["edges"]),
            }
        )

    logger.info(f"Total CFG edges: {len(all_edges)}")

    # Load into DuckDB
    conn = duckdb.connect(str(DB_PATH))
    try:
        rows = []
        for cfg in all_cfgs:
            prog = cfg["program"]
            # Get program UUID
            row = conn.execute("""
                SELECT uuid FROM nodes
                WHERE kind = 'ProgramNode'
                AND UPPER(source_file) = UPPER(?)
                LIMIT 1
            """, [cfg["source_file"]]).fetchone()
            prog_uuid = row[0] if row else prog

            for edge in cfg["edges"]:
                edge_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
                rows.append((
                    edge_id,
                    prog_uuid,
                    edge["from_para"],
                    edge["to_para"],
                    edge["edge_type"],
                    edge.get("condition"),
                    edge["source_file"],
                    edge["line"],
                ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO control_flow
                (id, program_uuid, from_uuid, to_uuid, edge_type,
                 condition, source_file, line_num)
                VALUES (?,?,?,?,?,?,?,?)
            """, rows)
        logger.info(f"Loaded {len(rows)} CFG edges into DuckDB")
    finally:
        conn.close()

    event_log.save()

    # Save artifact
    output_dir = OUT_DIR / "artifacts" / "layer4"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cfg.json"

    artifact = {
        "layer":       "L4",
        "total_edges": len(all_edges),
        "programs":    len(all_cfgs),
        "cfgs":        all_cfgs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"CFG saved: {output_path}")
    return artifact


if __name__ == "__main__":
    result = run()
    print(f"Total CFG edges: {result['total_edges']}")
    print(f"Programs:        {result['programs']}")
    print("\nCOTRN02C CFG sample:")
    for cfg in result["cfgs"]:
        if cfg["program"] == "COTRN02C":
            print(f"  Paragraphs: {len(cfg['paragraphs'])}")
            print(f"  Edges:      {len(cfg['edges'])}")
            for e in cfg["edges"][:5]:
                print(f"  {e['from_para']:<30} --{e['edge_type']}--> {e['to_para']}")
            break
