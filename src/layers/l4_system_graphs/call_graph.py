"""
call_graph.py
=============
Builds inter-program call graph for the CardDemo pipeline.

WHAT IT EXTRACTS:
    1. CALL statements (static + dynamic)
    2. EXEC CICS XCTL (transfer control — like a GOTO to another program)
    3. EXEC CICS LINK (like a CALL — returns to caller)
    4. PERFORM statements (intra-program paragraph calls)

CALL TYPES:
    CALL        — COBOL static/dynamic program call
    CICS_XCTL   — CICS transfer control (no return)
    CICS_LINK   — CICS link (returns to caller)
    PERFORM     — intra-program paragraph call

OUTPUT:
    out/artifacts/layer4/call_graph.json
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

logger = get_logger("layers.l4_system_graphs.call_graph")

# Known valid program names in CardDemo corpus
KNOWN_PROGRAMS = {
    "CBACT01C", "CBACT02C", "CBACT03C", "CBACT04C",
    "CBCUS01C", "CBEXPORT", "CBIMPORT", "CBSTM03A", "CBSTM03B",
    "CBTRN01C", "CBTRN02C", "CBTRN03C",
    "COACTVWC", "COACTUPC", "COADM01C", "COBIL00C",
    "COBSWAIT", "COCRDLIC", "COCRDSLC", "COCRDUPC",
    "COMEN01C", "CORPT00C", "COSGN00C",
    "COTRN00C", "COTRN01C", "COTRN02C",
    "COUSR00C", "COUSR01C", "COUSR02C", "COUSR03C",
    "CSUTLDTC", "COBDATFT", "MVSWAIT",
    # IBM runtime
    "CEE3ABD", "CEEDAYS",
}

# COBOL reserved words to filter out false positives
COBOL_RESERVED = {
    "TO", "FROM", "BY", "USING", "GIVING", "UNTIL", "VARYING",
    "AFTER", "BEFORE", "TIMES", "THROUGH", "THRU", "WITH",
    "CARD", "ASSEMBLER", "MENU", "SECTION", "DATA", "FILE",
    "PROCEDURE", "WORKING", "STORAGE", "LINKAGE", "LOCAL",
}

# CALL pattern — CALL 'PROGRAM' or CALL WS-VARIABLE
CALL_PATTERN = re.compile(
    r"CALL\s+(?:'([A-Z0-9@#$]{1,8})'|\"([A-Z0-9@#$]{1,8})\"|([A-Z0-9][A-Z0-9-]{0,29}))",
    re.IGNORECASE
)

# PERFORM pattern
PERFORM_PATTERN = re.compile(
    r"PERFORM\s+([A-Z0-9][A-Z0-9-]{1,29})(?:\s+(?:THROUGH|THRU)\s+([A-Z0-9][A-Z0-9-]{1,29}))?",
    re.IGNORECASE
)

# EXEC CICS XCTL PROGRAM(name)
XCTL_PATTERN = re.compile(
    r"EXEC\s+CICS\s+XCTL\s+PROGRAM\s*\(\s*([^)]+)\s*\)",
    re.IGNORECASE
)

# EXEC CICS LINK PROGRAM(name)
LINK_PATTERN = re.compile(
    r"EXEC\s+CICS\s+LINK\s+PROGRAM\s*\(\s*([^)]+)\s*\)",
    re.IGNORECASE
)

# Paragraph pattern
PARA_PATTERN = re.compile(
    r"^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$",
    re.IGNORECASE
)


def extract_calls_from_file(cbl_file: Path) -> dict:
    """
    Extract all call edges from one COBOL file.

    Returns:
        dict with external_calls, cics_xctl, cics_link, performs
    """
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()
    joined = " ".join(l.strip() for l in lines if not (len(l) > 6 and l[6] in ("*", "/")))

    program_name    = cbl_file.stem.upper()
    external_calls  = []
    cics_xctl       = []
    cics_link       = []
    performs        = []
    current_para    = "MAIN"

    for i, line in enumerate(lines):
        # Skip comments
        if len(line) > 6 and line[6] in ("*", "/"):
            continue

        stripped = line.strip().upper()

        # Track paragraph
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
            continue

        # CALL statements
        for m in CALL_PATTERN.finditer(line):
            target = (m.group(1) or m.group(2) or m.group(3) or "").strip().upper()
            if not target or target in COBOL_RESERVED:
                continue
            is_dynamic = not (m.group(1) or m.group(2))  # no quotes = dynamic
            external_calls.append({
                "caller":     program_name,
                "callee":     target,
                "call_type":  "CALL",
                "is_dynamic": is_dynamic,
                "is_known":   target in KNOWN_PROGRAMS,
                "paragraph":  current_para,
                "line":       i + 1,
                "source_file": cbl_file.name,
            })

        # PERFORM statements
        for m in PERFORM_PATTERN.finditer(line):
            target = m.group(1).strip().upper()
            thru   = (m.group(2) or "").strip().upper()
            if target in COBOL_RESERVED:
                continue
            performs.append({
                "caller":     program_name,
                "callee":     target,
                "thru":       thru,
                "call_type":  "PERFORM",
                "paragraph":  current_para,
                "line":       i + 1,
                "source_file": cbl_file.name,
            })

    # Match XCTL and LINK on joined content (handles multi-line)
    for m in XCTL_PATTERN.finditer(joined):
        target = m.group(1).strip().strip("'\"").upper()
        cics_xctl.append({
            "caller":      program_name,
            "callee":      target,
            "call_type":   "CICS_XCTL",
            "is_dynamic":  not target[0].isalpha() or target.startswith("WS-"),
            "paragraph":   "UNKNOWN",
            "line":        0,
            "source_file": cbl_file.name,
        })

    for m in LINK_PATTERN.finditer(joined):
        target = m.group(1).strip().strip("'\"").upper()
        cics_link.append({
            "caller":      program_name,
            "callee":      target,
            "call_type":   "CICS_LINK",
            "is_dynamic":  False,
            "paragraph":   "UNKNOWN",
            "line":        0,
            "source_file": cbl_file.name,
        })
        
    return {
        "program":       program_name,
        "source_file":   cbl_file.name,
        "external_calls": external_calls,
        "cics_xctl":     cics_xctl,
        "cics_link":     cics_link,
        "performs":      performs,
    }


def build_call_graph(corpus_dir: Optional[Path] = None,
                     output_dir: Optional[Path] = None) -> dict:
    """
    Build complete call graph from all COBOL files.

    Returns:
        dict with all edges and summary
    """
    corpus_dir = corpus_dir or (CORPUS_DIR / "app" / "cbl")
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer4")
    output_dir.mkdir(parents=True, exist_ok=True)

    event_log  = PipelineEventLog("call_graph")
    all_edges  = []
    per_program = []

    cbl_files = sorted(corpus_dir.glob("*.cbl"))
    logger.info(f"Building call graph from {len(cbl_files)} files")

    for cbl_file in cbl_files:
        result = extract_calls_from_file(cbl_file)
        per_program.append(result)

        edges = (result["external_calls"] +
                 result["cics_xctl"] +
                 result["cics_link"])
        all_edges.extend(edges)

        event_log.log_success(
            cbl_file.name,
            details={
                "external_calls": len(result["external_calls"]),
                "cics_xctl":      len(result["cics_xctl"]),
                "cics_link":      len(result["cics_link"]),
                "performs":       len(result["performs"]),
            }
        )

    # Summary
    callers = set(e["caller"] for e in all_edges)
    callees = set(e["callee"] for e in all_edges)

    summary = {
        "total_edges":     len(all_edges),
        "external_calls":  sum(1 for e in all_edges if e["call_type"] == "CALL"),
        "cics_xctl":       sum(1 for e in all_edges if e["call_type"] == "CICS_XCTL"),
        "cics_link":       sum(1 for e in all_edges if e["call_type"] == "CICS_LINK"),
        "unique_callers":  len(callers),
        "unique_callees":  len(callees),
        "dynamic_calls":   sum(1 for e in all_edges if e.get("is_dynamic")),
    }

    artifact = {
        "layer":   "L4",
        "summary": summary,
        "edges":   all_edges,
    }

    output_path = output_dir / "call_graph.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    event_log.save()
    logger.info(
        f"Call graph: {len(all_edges)} edges "
        f"({summary['external_calls']} CALL, "
        f"{summary['cics_xctl']} XCTL, "
        f"{summary['cics_link']} LINK)"
    )
    return artifact


if __name__ == "__main__":
    result = build_call_graph()
    print(json.dumps(result["summary"], indent=2))
    print("\nSample XCTL edges (screen navigation):")
    for e in result["edges"]:
        if e["call_type"] == "CICS_XCTL":
            print(f"  {e['caller']:<15} -XCTL-> {e['callee']}")
