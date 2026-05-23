"""
retrieval.py
============
Assembles artifact slices for LLM context.

Given a program UUID or name, assembles:
- Program metadata
- All paragraphs with complexity
- Symbol table (top variables)
- File I/O operations
- CICS statements
- Call graph edges
- Copybook origins
- Token stream comments (business logic hints)

This is what gets sent to Claude as context for spec generation.
All claims in the spec must trace back to one of these artifacts.
"""

import json
import duckdb
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("llm.retrieval")

DB_PATH    = OUT_DIR / "graph" / "artifacts.duckdb"
LAYER1_DIR = OUT_DIR / "artifacts" / "layer1"
LAYER2_DIR = OUT_DIR / "artifacts" / "layer2"
LAYER3_DIR = OUT_DIR / "artifacts" / "layer3"
LAYER4_DIR = OUT_DIR / "artifacts" / "layer4"


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def assemble_program_slice(program_name: str) -> dict:
    """
    Assemble complete artifact slice for one COBOL program.

    Args:
        program_name: Program name (e.g. 'COTRN02C' or 'CBACT01C')

    Returns:
        dict: Complete artifact slice for LLM context
    """
    program_name = program_name.upper().replace(".CBL", "")
    logger.info(f"Assembling artifact slice for: {program_name}")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    slice_data = {"program_name": program_name}

    try:
        # ---------------------------------------------------------------
        # 1. Program metadata from DuckDB
        # ---------------------------------------------------------------
        row = conn.execute("""
            SELECT uuid, source_file, start_line, end_line, payload_json
            FROM nodes
            WHERE kind = 'ProgramNode'
            AND UPPER(source_file) = UPPER(?)
            LIMIT 1
        """, [program_name + ".cbl"]).fetchone()

        if not row:
            logger.warning(f"Program not found in DB: {program_name}")
            slice_data["error"] = f"Program {program_name} not found"
            return slice_data

        prog_uuid, source_file, start_line, end_line, payload_json = row
        payload = json.loads(payload_json) if payload_json else {}

        slice_data["uuid"]         = prog_uuid
        slice_data["source_file"]  = source_file
        slice_data["program_type"] = payload.get("program_type", "unknown")
        slice_data["total_lines"]  = end_line - start_line + 1
        slice_data["copybooks"]    = payload.get("copybooks", [])

        # ---------------------------------------------------------------
        # 2. Paragraphs with complexity
        # ---------------------------------------------------------------
        paragraphs = conn.execute("""
            SELECT uuid, name, start_line, end_line,
                   statement_count, complexity
            FROM paragraphs
            WHERE program_uuid = ?
            ORDER BY start_line
        """, [prog_uuid]).fetchall()

        slice_data["paragraphs"] = [
            {
                "uuid":            p[0],
                "name":            p[1],
                "start_line":      p[2],
                "end_line":        p[3],
                "statement_count": p[4],
                "complexity":      p[5],
            }
            for p in paragraphs
        ]

        # ---------------------------------------------------------------
        # 3. Symbol table (top 50 — focus on working storage)
        # ---------------------------------------------------------------
        symbols = conn.execute("""
            SELECT uuid, name, level, pic, usage, scope,
                   canonical_type, copybook_origin, defined_at_line
            FROM symbols
            WHERE program_uuid = ?
            AND level IN (1, 5, 77)
            ORDER BY defined_at_line
            LIMIT 50
        """, [prog_uuid]).fetchall()

        slice_data["symbols"] = [
            {
                "uuid":            s[0],
                "name":            s[1],
                "level":           s[2],
                "pic":             s[3],
                "usage":           s[4],
                "scope":           s[5],
                "canonical_type":  json.loads(s[6]) if s[6] else {},
                "copybook_origin": s[7],
                "defined_at_line": s[8],
            }
            for s in symbols
        ]

        # ---------------------------------------------------------------
        # 4. File I/O operations
        # ---------------------------------------------------------------
        file_ops = conn.execute("""
            SELECT file_name, operation, line_num
            FROM file_io
            WHERE UPPER(program_uuid) = UPPER(?)
            ORDER BY line_num
        """, [program_name]).fetchall()

        slice_data["file_io"] = [
            {"file": r[0], "operation": r[1], "line": r[2]}
            for r in file_ops
        ]

        # ---------------------------------------------------------------
        # 5. Call graph edges (what this program calls)
        # ---------------------------------------------------------------
        callees = conn.execute("""
            SELECT id, callee_uuid, call_type, call_target, line_num
            FROM call_graph
            WHERE UPPER(caller_uuid) = UPPER(?)
            ORDER BY line_num
        """, [program_name]).fetchall()

        slice_data["calls"] = [
            {
                "uuid":        r[0],
                "callee":      r[1],
                "call_type":   r[2],
                "call_target": r[3],
                "line":        r[4],
            }
            for r in callees
        ]

        # ---------------------------------------------------------------
        # 6. Transaction flow (CICS navigation)
        # ---------------------------------------------------------------
        tx_flow = conn.execute("""
            SELECT to_program_uuid, edge_type, transid, line_num
            FROM transaction_flow
            WHERE UPPER(from_program_uuid) = UPPER(?)
        """, [program_name]).fetchall()

        slice_data["transaction_flow"] = [
            {
                "to_program": r[0],
                "edge_type":  r[1],
                "transid":    r[2],
                "line":       r[3],
            }
            for r in tx_flow
        ]

        # ---------------------------------------------------------------
        # 7. Comments from token stream (business logic hints)
        # ---------------------------------------------------------------
        token_path = LAYER1_DIR / f"{program_name}_tokens.json"
        comments   = []
        if token_path.exists():
            token_data = json.loads(token_path.read_text())
            all_tokens = token_data.get("tokens", [])
            comments   = [
                {"line": t["line"], "text": t["text"].strip()}
                for t in all_tokens
                if t.get("hidden") and t.get("text", "").strip().startswith("*")
                and len(t.get("text", "").strip()) > 3
            ][:30]  # limit to 30 most relevant comments

        slice_data["comments"] = comments

        # ---------------------------------------------------------------
        # 8. EXEC CICS statements
        # ---------------------------------------------------------------
        cics_path = LAYER3_DIR / "cics_statements.json"
        cics_stmts = []
        if cics_path.exists():
            cics_data  = json.loads(cics_path.read_text())
            cics_stmts = [
                s for s in cics_data.get("statements", [])
                if s.get("source_file", "").upper() == f"{program_name}.CBL"
            ]

        slice_data["cics_statements"] = [
            {
                "uuid":      s.get("uuid", ""),
                "verb":      s["verb"],
                "params":    s["params"],
                "paragraph": s["paragraph"],
                "line":      s["line"],
            }
            for s in cics_stmts
        ]

        # ---------------------------------------------------------------
        # 9. Move chains (data lineage)
        # ---------------------------------------------------------------
        move_path = OUT_DIR / "artifacts" / "layer5" / "move_chains.json"
        move_chains = []
        if move_path.exists():
            move_data = json.loads(move_path.read_text())
            for result in move_data.get("results", []):
                if result.get("source_file", "").upper() == f"{program_name}.CBL":
                    move_chains = result.get("moves", [])[:20]  # top 20
                    break

        slice_data["move_chains"] = move_chains
        
        # ---------------------------------------------------------------
        # 10. Business rules from DuckDB
        # ---------------------------------------------------------------
        biz_rules = conn.execute("""
            SELECT uuid, kind, predicate_raw, then_summary,
                   else_summary, line_num
            FROM business_rules
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
            LIMIT 20
        """, [source_file]).fetchall()

        slice_data["business_rules"] = [
            {
                "uuid":      r[0],
                "kind":      r[1],
                "predicate": r[2][:80] if r[2] else "",
                "then":      r[3][:60] if r[3] else "",
                "else":      r[4][:60] if r[4] else "",
                "line":      r[5],
            }
            for r in biz_rules
        ]

        # ---------------------------------------------------------------
        # 11. Def-use chains from DuckDB
        # ---------------------------------------------------------------
        def_use = conn.execute("""
            SELECT id, data_item_uuid, operation, line_num
            FROM def_use
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
            LIMIT 30
        """, [source_file]).fetchall()

        slice_data["def_use"] = [
            {
                "uuid":      r[0],
                "variable":  r[1],
                "operation": r[2],
                "line":      r[3],
            }
            for r in def_use
        ]

        # ---------------------------------------------------------------
        # 12. CFG edges from DuckDB
        # ---------------------------------------------------------------
        cfg_edges = conn.execute("""
            SELECT id, from_uuid, to_uuid, edge_type, condition, line_num
            FROM control_flow
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
            LIMIT 30
        """, [source_file]).fetchall()

        slice_data["cfg_edges"] = [
            {
                "uuid":      r[0],
                "from_para": r[1],
                "to_para":   r[2],
                "edge_type": r[3],
                "condition": r[4],
                "line":      r[5],
            }
            for r in cfg_edges
        ]

        logger.info(
            f"Slice assembled for {program_name}: "
            f"{len(slice_data['paragraphs'])} paragraphs, "
            f"{len(slice_data['symbols'])} symbols, "
            f"{len(slice_data['comments'])} comments"
        )

    finally:
        conn.close()

    return slice_data


def format_slice_for_llm(slice_data: dict) -> str:
    """
    Format artifact slice as structured text for LLM context.

    Returns a well-structured prompt context that the LLM
    uses to generate grounded specifications.

    Args:
        slice_data: Output from assemble_program_slice()

    Returns:
        str: Formatted context string
    """
    prog = slice_data.get("program_name", "UNKNOWN")
    lines = []

    lines.append(f"=== PROGRAM: {prog} ===")
    lines.append(f"Type: {slice_data.get('program_type', 'unknown').upper()}")
    lines.append(f"Lines: {slice_data.get('total_lines', 0)}")
    lines.append(f"Copybooks: {', '.join(slice_data.get('copybooks', []))}")
    lines.append("")

    # Comments (business context)
    comments = slice_data.get("comments", [])
    if comments:
        lines.append("=== PROGRAM COMMENTS (business context) ===")
        for c in comments[:15]:
            text = c["text"].lstrip("*>").strip()
            if text and len(text) > 5:
                lines.append(f"  Line {c['line']:4}: {text}")
        lines.append("")

    # Paragraphs
    paras = slice_data.get("paragraphs", [])
    if paras:
        lines.append("=== PARAGRAPHS ===")
        for p in paras:
            lines.append(
                f"  [UUID:{p.get('uuid','')}] {p['name']:<40} "
                f"lines {p['start_line']:4}-{p['end_line']:4} "
                f"stmts={p['statement_count']:3} "
                f"complexity={p['complexity']}"
            )
        lines.append("")

    # Key symbols
    symbols = slice_data.get("symbols", [])
    if symbols:
        lines.append("=== KEY DATA ITEMS (Working Storage) ===")
        for s in symbols[:20]:
            ct = s.get("canonical_type", {})
            type_str = ct.get("kind", "")
            if ct.get("precision"):
                type_str += f"({ct['precision']})"
            if ct.get("scale"):
                type_str += f" scale={ct['scale']}"
            cb = f" [from {s['copybook_origin']}]" if s.get("copybook_origin") else ""
            lines.append(
                f"  [UUID:{s.get('uuid','')}] L{s['level']:02} {s['name']:<35} "
                f"PIC {str(s.get('pic','')):<15} "
                f"{type_str}{cb}"
            )
        lines.append("")

    # File I/O
    file_ops = slice_data.get("file_io", [])
    if file_ops:
        lines.append("=== FILE I/O ===")
        for op in file_ops:
            lines.append(f"  {op['operation']:<15} {op['file']} (line {op['line']})")
        lines.append("")

    # CICS statements
    cics = slice_data.get("cics_statements", [])
    if cics:
        lines.append("=== EXEC CICS STATEMENTS ===")
        for s in cics:
            params_str = ", ".join(f"{k}={v}" for k, v in s["params"].items())
            lines.append(
                f"  [UUID:{s.get('uuid','')}] {s['verb']:<15} {params_str[:60]} "
                f"(line {s['line']}, para={s['paragraph']})"
            )
        lines.append("")

    # Calls
    calls = slice_data.get("calls", [])
    if calls:
        lines.append("=== PROGRAM CALLS ===")
        for c in calls:
            lines.append(
                f"  [UUID:{c.get('uuid','')}] {c['call_type']:<12} -> "
                f"{c['call_target']:<20} (line {c['line']})"
            )
        lines.append("")

    # Business rules
    biz_rules = slice_data.get("business_rules", [])
    if biz_rules:
        lines.append("=== BUSINESS RULES (IF/EVALUATE) ===")
        for r in biz_rules[:10]:
            lines.append(
                f"  [UUID:{r['uuid']}] {r['kind']:<10} "
                f"line {r['line']:4}: {r['predicate'][:60]}"
            )
            if r["then"]:
                lines.append(f"    THEN: {r['then']}")
            if r["else"]:
                lines.append(f"    ELSE: {r['else']}")
        lines.append("")

    # Def-use chains
    def_use = slice_data.get("def_use", [])
    if def_use:
        lines.append("=== DEF-USE CHAINS ===")
        for r in def_use[:15]:
            lines.append(
                f"  [UUID:{r.get('uuid','')}] {r['operation']:<6} "
                f"{r['variable']:<30} line {r['line']:4}"
            )
        lines.append("")

    # CFG edges
    cfg_edges = slice_data.get("cfg_edges", [])
    if cfg_edges:
        lines.append("=== CONTROL FLOW GRAPH ===")
        for e in cfg_edges[:15]:
            cond = f" [{e['condition'][:30]}]" if e.get("condition") else ""
            lines.append(
                f"  [UUID:{e.get('uuid','')}] {e['from_para']:<30} "
                f"--{e['edge_type']}--> {e['to_para']}{cond} (line {e['line']})"
            )
        lines.append("")

    return "\n".join(lines)
