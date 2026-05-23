"""
main.py
=======
FastAPI REST API for the CardDemo modernization pipeline.

Required endpoints per brief §8:
    GET /program/{name}              — program metadata + node UUID
    GET /paragraph/{uuid}            — paragraph AST + statements
    GET /dataitem/{uuid}             — data definition with type, scope
    GET /callers/{uuid}              — call graph traversal (who calls this)
    GET /callees/{uuid}              — call graph traversal (what this calls)
    GET /controlflow/{program_uuid}  — CFG
    GET /defuse/{dataitem_uuid}      — def-use chain
    GET /businessrules/{program_uuid}— business rule catalog
    GET /fileaccesses/{program_uuid} — file I/O list
    GET /transactionflow/{transid}   — reachable transaction graph
    GET /jobchain/{job_name}         — upstream/downstream job dependencies
    GET /copybookconsumers/{name}    — programs that include the copybook
    GET /retrieve/{uuid}             — artifact slice retrieval
    GET /health                      — health check
    GET /coverage                    — parse coverage report
"""

import json
import duckdb
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from fastapi.responses import HTMLResponse

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

# -----------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------
app = FastAPI(
    title="CardDemo Modernization API",
    description="REST API for CardDemo COBOL corpus analysis artifacts",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"


def get_db():
    """Get DuckDB connection."""
    return duckdb.connect(str(DB_PATH), read_only=True)


def _load_json(path: Path) -> dict:
    """Load JSON artifact file."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# -----------------------------------------------------------------------
# Health + Coverage
# -----------------------------------------------------------------------

@app.get("/health")
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "db": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }


@app.get("/coverage")
def get_coverage():
    """Return parse coverage report."""
    coverage_path = OUT_DIR / "reports" / "parse_coverage.json"
    if not coverage_path.exists():
        raise HTTPException(status_code=404, detail="Coverage report not found")
    return _load_json(coverage_path)


# -----------------------------------------------------------------------
# Program endpoints
# -----------------------------------------------------------------------

@app.get("/program/{program_name}")
def get_program(program_name: str):
    """
    Get program metadata and node UUID.
    Returns: program node, paragraph count, symbol count, copybooks used.
    """
    conn = get_db()
    try:
        name_upper = program_name.upper()
        if not name_upper.endswith(".CBL"):
            name_upper_file = name_upper + ".cbl"
        else:
            name_upper_file = name_upper

        # Try both with and without .cbl suffix
        row = conn.execute("""
            SELECT uuid, kind, source_file, start_line, end_line, payload_json
            FROM nodes
            WHERE kind = 'ProgramNode'
            AND (UPPER(source_file) = UPPER(?)
                 OR UPPER(source_file) = UPPER(?) )
            LIMIT 1
        """, [name_upper_file, program_name + ".CBL"]).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Program '{program_name}' not found"
            )

        uuid, kind, source_file, start_line, end_line, payload_json = row
        payload = json.loads(payload_json) if payload_json else {}

        # Get paragraphs with UUIDs
        para_rows = conn.execute("""
            SELECT uuid, name, start_line, end_line, statement_count, complexity
            FROM paragraphs WHERE program_uuid = ?
            ORDER BY start_line
        """, [uuid]).fetchall()
        para_count = len(para_rows)

        # Get symbol count
        sym_count = conn.execute("""
            SELECT COUNT(*) FROM symbols WHERE program_uuid = ?
        """, [uuid]).fetchone()[0]

        # Get copybooks used
        copybooks = conn.execute("""
            SELECT id, copybook_name FROM copybook_use WHERE program_uuid = ?
        """, [uuid]).fetchall()

        return {
            "uuid":           uuid,
            "program_name":   payload.get("program_name", program_name),
            "source_file":    source_file,
            "program_type":   payload.get("program_type", "unknown"),
            "total_lines":    end_line - start_line + 1,
            "paragraph_count": para_count,
            "paragraphs": [
                {
                    "uuid":       p[0],
                    "name":       p[1],
                    "start_line": p[2],
                    "end_line":   p[3],
                    "statements": p[4],
                    "complexity": p[5],
                }
                for p in para_rows
            ],
            "symbol_count":   sym_count,
            "copybooks":      [c[0] for c in copybooks],
            "payload":        payload,
            "copybooks": [{"uuid": c[0], "name": c[1]} for c in copybooks]
        }
    finally:
        conn.close()

@app.get("/paragraph/{uuid}")
def get_paragraph(uuid: str):
    """
    Get enriched paragraph AST including:
    - Basic metadata (name, lines, statements, complexity)
    - CFG edges (PERFORM chains from this paragraph)
    - CICS statements in this paragraph
    - Business rules (IF/EVALUATE) in this paragraph
    - Symbols referenced (from move chains)
    """
    conn = get_db()
    try:
        # Basic paragraph data
        row = conn.execute("""
            SELECT uuid, source_file, start_line, end_line,
                   statement_count, complexity, name, program_uuid
            FROM paragraphs WHERE uuid = ?
        """, [uuid]).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Paragraph '{uuid}' not found")

        uuid, sf, sl, el, stmts, cx, name, prog_uuid = row
        prog = sf.replace(".cbl", "").upper()

        # CFG edges from this paragraph
        cfg_edges = conn.execute("""
            SELECT cf.id, cf.from_uuid, cf.to_uuid, cf.edge_type,
                   cf.condition, cf.line_num,
                   fp.uuid as from_para_uuid,
                   tp.uuid as to_para_uuid
            FROM control_flow cf
            LEFT JOIN paragraphs fp ON UPPER(fp.name) = UPPER(cf.from_uuid)
                AND UPPER(fp.source_file) = UPPER(cf.source_file)
            LEFT JOIN paragraphs tp ON UPPER(tp.name) = UPPER(cf.to_uuid)
                AND UPPER(tp.source_file) = UPPER(cf.source_file)
            WHERE UPPER(cf.source_file) = UPPER(?)
            AND UPPER(cf.from_uuid) = UPPER(?)
            ORDER BY cf.line_num
        """, [sf, name]).fetchall()

        # CICS statements in this paragraph
        cics_path = OUT_DIR / "artifacts" / "layer3" / "cics_statements.json"
        cics_stmts = []
        if cics_path.exists():
            cics_data = json.loads(cics_path.read_text())
            cics_stmts = [
                s for s in cics_data.get("statements", [])
                if s.get("source_file", "").upper() == sf.upper()
                and s.get("paragraph", "").upper() == name.upper()
            ]

        # Business rules in this paragraph
        rules = conn.execute("""
            SELECT uuid, kind, predicate_raw, then_summary, else_summary, line_num
            FROM business_rules
            WHERE UPPER(source_file) = UPPER(?)
            AND UPPER(program_uuid) = UPPER(?)
            AND line_num BETWEEN ? AND ?
            ORDER BY line_num
        """, [sf, prog, sl, el]).fetchall()

        # Real statements from AST artifact (Layer 1)
        moves = []
        ast_path = OUT_DIR / "artifacts" / "layer1" / sf.replace(".cbl", "_ast.json")
        if ast_path.exists():
            ast_data = json.loads(ast_path.read_text())
            for para_node in ast_data.get("paragraph_nodes", []):
                if para_node.get("payload", {}).get("name", "").upper() == name.upper():
                    moves = para_node.get("payload", {}).get("statements", [])
                    break

        return {
            "uuid":            uuid,
            "name":            name,
            "source_file":     sf,
            "program":         prog,
            "start_line":      sl,
            "end_line":        el,
            "line_count":      el - sl + 1,
            "statement_count": stmts,
            "complexity":      cx,
            "cfg_edges": [
                {
                    "uuid":          r[0],
                    "from_para":     r[1],
                    "to_para":       r[2],
                    "edge_type":     r[3],
                    "condition":     r[4],
                    "line":          r[5],
                    "from_para_uuid": r[6],
                    "to_para_uuid":  r[7],
                }
                for r in cfg_edges
            ],
            "cics_statements": [
                {
                    "uuid":   s.get("uuid", ""),
                    "verb":   s["verb"],
                    "params": s["params"],
                    "line":   s["line"],
                }
                for s in cics_stmts
            ],
            "business_rules": [
                {
                    "uuid":      r[0],
                    "kind":      r[1],
                    "predicate": r[2],
                    "then":      r[3],
                    "else":      r[4],
                    "line":      r[5],
                }
                for r in rules
            ],
            "statements": [
                {
                    "uuid": m.get("uuid", ""),
                    "type": m.get("type", ""),
                    "line": m.get("line", 0),
                    "raw":  m.get("raw", "")[:100],
                }
                for m in moves[:50]
            ],
        }
    finally:
        conn.close()


@app.get("/dataitem/{uuid}")
def get_data_item(uuid: str):
    """Get data item definition with type and scope."""
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT uuid, name, level, pic, usage, scope,
                   canonical_type, copybook_origin, source_file,
                   defined_at_line, payload_json
            FROM symbols WHERE uuid = ?
        """, [uuid]).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Data item '{uuid}' not found"
            )

        (uuid, name, level, pic, usage, scope,
         canonical_type, copybook_origin, sf, line, payload) = row

        return {
            "uuid":            uuid,
            "name":            name,
            "level":           level,
            "pic":             pic,
            "usage":           usage,
            "scope":           scope,
            "canonical_type":  json.loads(canonical_type) if canonical_type else {},
            "copybook_origin": copybook_origin,
            "source_file":     sf,
            "defined_at_line": line,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Call graph endpoints
# -----------------------------------------------------------------------

@app.get("/callers/{program_name}")
def get_callers(program_name: str):
    """Get all programs that call this program."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, caller_uuid, call_type, call_target, source_file, line_num
            FROM call_graph
            WHERE UPPER(callee_uuid) = UPPER(?)
               OR UPPER(call_target) = UPPER(?)
        """, [program_name, program_name]).fetchall()

        # Get program UUID
        prog_node = conn.execute("""
            SELECT uuid FROM nodes
            WHERE kind = 'ProgramNode'
            AND UPPER(source_file) = UPPER(?)
            LIMIT 1
        """, [program_name.upper() + ".cbl"]).fetchone()
        program_uuid = prog_node[0] if prog_node else None

        return {
            "program":  program_name,
            "program_uuid": program_uuid,
            "callers":  [
                {   
                    "uuid":        r[0],
                    "caller":      r[1],
                    "call_type":   r[2],
                    "call_target": r[3],
                    "source_file": r[4],
                    "line":        r[5],
                }
                for r in rows
            ],
            "count": len(rows)
        }
    finally:
        conn.close()


@app.get("/callees/{program_name}")
def get_callees(program_name: str):
    """Get all programs called by this program."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, callee_uuid, call_type, call_target, source_file, line_num
            FROM call_graph
            WHERE UPPER(caller_uuid) = UPPER(?)
            ORDER BY line_num
        """, [program_name.upper()]).fetchall()

        # Get program UUID
        prog_node = conn.execute("""
            SELECT uuid FROM nodes
            WHERE kind = 'ProgramNode'
            AND UPPER(source_file) = UPPER(?)
            LIMIT 1
        """, [program_name.upper() + ".cbl"]).fetchone()
        program_uuid = prog_node[0] if prog_node else None

        return {
            "program":  program_name,
            "program_uuid": program_uuid,
            "callees":  [
                {
                    "uuid":        r[0],
                    "callee":      r[1],
                    "call_type":   r[2],
                    "call_target": r[3],
                    "source_file": r[4],
                    "line":        r[5],
                }
                for r in rows
            ],
            "count": len(rows)
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------
# File I/O endpoint
# -----------------------------------------------------------------------

@app.get("/fileaccesses/{program_name}")
def get_file_accesses(program_name: str):
    """Get all file I/O operations for a program."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT file_name, operation, source_file, line_num
            FROM file_io
            WHERE UPPER(program_uuid) = UPPER(?)
            ORDER BY line_num
        """, [program_name.upper()]).fetchall()

        return {
            "program":    program_name,
            "operations": [
                {
                    "file_name":   r[0],
                    "operation":   r[1],
                    "source_file": r[2],
                    "line":        r[3],
                }
                for r in rows
            ],
            "count": len(rows)
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Transaction flow endpoint
# -----------------------------------------------------------------------

@app.get("/transactionflow/{transid}")
def get_transaction_flow(transid: str):
    """Get reachable transaction graph from a transaction ID."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT from_program_uuid, to_program_uuid, edge_type,
                   transid, source_file, line_num
            FROM transaction_flow
            WHERE UPPER(transid) = UPPER(?)
               OR UPPER(from_program_uuid) = UPPER(?)
        """, [transid.upper(), transid.upper()]).fetchall()

        return {
            "transid": transid,
            "edges":   [
                {
                    "from_program": r[0],
                    "to_program":   r[1],
                    "edge_type":    r[2],
                    "transid":      r[3],
                    "source_file":  r[4],
                    "line":         r[5],
                }
                for r in rows
            ],
            "count": len(rows)
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------
# JCL job chain endpoint
# -----------------------------------------------------------------------

@app.get("/jobchain/{job_name}")
def get_job_chain(job_name: str):
    """Get upstream/downstream job dependencies via dataset reuse."""
    conn = get_db()
    try:
        # Get steps for this job
        steps = conn.execute("""
            SELECT id, step_name, program_name, dd_name,
                   dataset_name, disposition
            FROM jcl_job
            WHERE UPPER(job_name) = UPPER(?)
            ORDER BY step_name
        """, [job_name.upper()]).fetchall()

        # Get dependencies where this job is producer or consumer
        deps = conn.execute("""
            SELECT producer_job, consumer_job, dataset_name,
                   producer_disp, consumer_disp
            FROM jcl_dependency
            WHERE UPPER(producer_job) = UPPER(?)
               OR UPPER(consumer_job) = UPPER(?)
        """, [job_name.upper(), job_name.upper()]).fetchall()

        # Also check known chains
        known_chains_path = OUT_DIR / "artifacts" / "jcl" / "jcl_graph.json"
        known_chains = []
        if known_chains_path.exists():
            jcl_data = json.loads(known_chains_path.read_text())
            for chain in jcl_data.get("known_chains", []):
                if job_name.upper() in [j.upper() for j in chain.get("jobs", [])]:
                    known_chains.append(chain)

        # Get job UUID
        job_node = conn.execute("""
            SELECT id FROM jcl_job
            WHERE UPPER(job_name) = UPPER(?)
            LIMIT 1
        """, [job_name.upper()]).fetchone()
        job_uuid = job_node[0] if job_node else None

        return {
            "job_name":     job_name,
            "job_uuid": job_uuid,
            "steps": [
                {
                    "uuid":        r[0],
                    "step_name":   r[1],
                    "program":     r[2],
                    "dd_name":     r[3],
                    "dataset":     r[4],
                    "disposition": r[5],
                }
                for r in steps
            ],
            "dependencies": [
                {
                    "producer_job":  r[0],
                    "consumer_job":  r[1],
                    "dataset_name":  r[2],
                    "producer_disp": r[3],
                    "consumer_disp": r[4],
                }
                for r in deps
            ],
            "known_chains": known_chains,
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Copybook consumers endpoint
# -----------------------------------------------------------------------

@app.get("/copybookconsumers/{copybook_name}")
def get_copybook_consumers(copybook_name: str):
    """Get all programs that include this copybook."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT program_uuid, source_file
            FROM copybook_use
            WHERE UPPER(copybook_name) = UPPER(?)
            ORDER BY program_uuid
        """, [copybook_name.upper()]).fetchall()

        return {
            "copybook":  copybook_name,
            "consumers": [
                {
                    "program":     r[0],
                    "source_file": r[1],
                }
                for r in rows
            ],
            "count": len(rows)
        }
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Artifact retrieval endpoint
# -----------------------------------------------------------------------

@app.get("/retrieve/{uuid}")
def retrieve_artifact(uuid: str):
    """
    Assemble relevant artifact slice for a given UUID.
    Returns the node, its symbol context, CFG neighbors,
    def-use cluster, called/calling paragraphs.
    """
    conn = get_db()
    try:
        # Try nodes table first
        node = conn.execute("""
            SELECT uuid, kind, source_file, start_line, end_line,
                   parent_uuid, payload_json
            FROM nodes WHERE uuid = ?
        """, [uuid]).fetchone()

        if node:
            uuid, kind, sf, sl, el, parent_uuid, payload_json = node
            payload = json.loads(payload_json) if payload_json else {}

            result = {
                "uuid":        uuid,
                "kind":        kind,
                "source_file": sf,
                "start_line":  sl,
                "end_line":    el,
                "parent_uuid": parent_uuid,
                "payload":     payload,
            }

            # If program node — add children
            if kind == "ProgramNode":
                children = conn.execute("""
                    SELECT uuid, payload_json->>'name' as name
                    FROM nodes WHERE parent_uuid = ?
                    AND kind = 'ParagraphNode'
                """, [uuid]).fetchall()
                result["paragraphs"] = [
                    {"uuid": c[0], "name": c[1]} for c in children
                ]

                symbols = conn.execute("""
                    SELECT uuid, name, pic, canonical_type
                    FROM symbols WHERE program_uuid = ?
                    LIMIT 20
                """, [uuid]).fetchall()
                result["symbols_sample"] = [
                    {"uuid": s[0], "name": s[1], "pic": s[2]} for s in symbols
                ]

            return result

        # Try symbols table
        sym = conn.execute("""
            SELECT uuid, name, level, pic, usage, scope,
                   canonical_type, copybook_origin, source_file
            FROM symbols WHERE uuid = ?
        """, [uuid]).fetchone()

        if sym:
            return {
                "uuid":            sym[0],
                "kind":            "DataItem",
                "name":            sym[1],
                "level":           sym[2],
                "pic":             sym[3],
                "usage":           sym[4],
                "scope":           sym[5],
                "canonical_type":  json.loads(sym[6]) if sym[6] else {},
                "copybook_origin": sym[7],
                "source_file":     sym[8],
            }

        # 3. paragraphs table
        row = conn.execute("""
            SELECT uuid, name, source_file, start_line, end_line,
                   statement_count, complexity, program_uuid
            FROM paragraphs WHERE uuid = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": "ParagraphNode",
                "name": row[1], "source_file": row[2],
                "start_line": row[3], "end_line": row[4],
                "statement_count": row[5], "complexity": row[6],
                "program_uuid": row[7],
                "retrieve_via": f"/paragraph/{row[0]}"
            }

        # 4. business_rules table
        row = conn.execute("""
            SELECT uuid, program_uuid, kind, predicate_raw,
                   then_summary, else_summary, source_file, line_num
            FROM business_rules WHERE uuid = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": f"BusinessRule:{row[2]}",
                "program_uuid": row[1],
                "predicate": row[3],
                "then": row[4], "else": row[5],
                "source_file": row[6], "line_num": row[7],
                "retrieve_via": f"/businessrules/{row[1]}"
            }

        # 5. control_flow table
        row = conn.execute("""
            SELECT id, program_uuid, from_uuid, to_uuid,
                   edge_type, condition, source_file, line_num
            FROM control_flow WHERE id = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": "CFGEdge",
                "program_uuid": row[1],
                "from_para": row[2], "to_para": row[3],
                "edge_type": row[4], "condition": row[5],
                "source_file": row[6], "line_num": row[7]
            }

        # 6. call_graph table
        row = conn.execute("""
            SELECT id, caller_uuid, callee_uuid, call_type,
                   call_target, source_file, line_num
            FROM call_graph WHERE id = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": "CallEdge",
                "caller": row[1], "callee": row[2],
                "call_type": row[3], "call_target": row[4],
                "source_file": row[5], "line_num": row[6]
            }

        # 7. def_use table
        row = conn.execute("""
            SELECT id, data_item_uuid, operation,
                   stmt_text, source_file, line_num
            FROM def_use WHERE id = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": "DefUseEntry",
                "variable": row[1], "operation": row[2],
                "stmt_text": row[3],
                "source_file": row[4], "line_num": row[5]
            }

        # 8. ims_io table
        row = conn.execute("""
            SELECT id, program_uuid, segment_name,
                   operation, pcb_name, source_file, line_num
            FROM ims_io WHERE id = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": "IMSAccess",
                "program": row[1], "segment": row[2],
                "operation": row[3], "pcb": row[4],
                "source_file": row[5], "line_num": row[6]
            }

        # 9. mq_io table
        row = conn.execute("""
            SELECT id, program_uuid, queue_name,
                   operation, source_file, line_num
            FROM mq_io WHERE id = ?
        """, [uuid]).fetchone()
        if row:
            return {
                "uuid": row[0], "kind": "MQAccess",
                "program": row[1], "queue": row[2],
                "operation": row[3],
                "source_file": row[4], "line_num": row[5]
            }

        # 10. CICS statements (stored in JSON artifact not DuckDB)
        cics_path = OUT_DIR / "artifacts" / "layer3" / "cics_statements.json"
        if cics_path.exists():
            cics_data = json.loads(cics_path.read_text())
            for stmt in cics_data.get("statements", []):
                if stmt.get("uuid") == uuid:
                    return {
                        "uuid":        stmt["uuid"],
                        "kind":        "CICSStatement",
                        "verb":        stmt.get("verb"),
                        "params":      stmt.get("params", {}),
                        "paragraph":   stmt.get("paragraph"),
                        "source_file": stmt.get("source_file"),
                        "line_num":    stmt.get("line"),
                        "raw":         stmt.get("raw","")[:100],
                    }

        raise HTTPException(
            status_code=404,
            detail=f"UUID '{uuid}' not found in any artifact table"
        )
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Business rules + Control flow + Def-use (stub endpoints)
# -----------------------------------------------------------------------

@app.get("/controlflow/{program_name}")
def get_control_flow(program_name: str):
    """Get CFG edges for a program. Also see GET /cfg/{program_name} for visual."""
    conn = get_db()
    try:
        prog = program_name.upper()

        rows = conn.execute("""
            SELECT from_uuid, to_uuid, edge_type, condition, line_num
            FROM control_flow
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
        """, [prog + ".cbl"]).fetchall()

        return {
            "program":    prog,
            "edges": [
                {
                    "from_para": r[0],
                    "to_para":   r[1],
                    "edge_type": r[2],
                    "condition": r[3],
                    "line":      r[4],
                }
                for r in rows
            ],
            "count":   len(rows),
            "visual":  f"http://localhost:8000/cfg/{prog}",
        }
    finally:
        conn.close()
        
@app.get("/defuse/{program_name}")
def get_def_use(program_name: str):
    """
    Get def-use chains for all variables in a program.
    Shows where each variable is defined (WRITE) and used (READ).
    """
    conn = get_db()
    try:
        prog = program_name.upper()

        rows = conn.execute("""
            SELECT data_item_uuid, operation, stmt_text, source_file, line_num
            FROM def_use
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
        """, [prog + ".cbl"]).fetchall()

        # Group by variable
        by_var = {}
        for r in rows:
            var = r[0]
            if var not in by_var:
                by_var[var] = {"variable": var, "reads": [], "writes": []}
            entry = {"stmt_text": r[2], "line": r[4]}
            if r[1] == "WRITE":
                by_var[var]["writes"].append(entry)
            else:
                by_var[var]["reads"].append(entry)

        return {
            "program":     prog,
            "total_vars":  len(by_var),
            "total_reads": sum(1 for r in rows if r[1] == "READ"),
            "total_writes":sum(1 for r in rows if r[1] == "WRITE"),
            "chains":      list(by_var.values())[:50],
        }
    finally:
        conn.close()

@app.get("/businessrules/{program_uuid}")
def get_business_rules(program_uuid: str):
    """Get business rule catalog for a program (stub — populated Day 6)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT uuid, kind, predicate_raw, then_summary,
                   else_summary, source_file, line_num
            FROM business_rules WHERE program_uuid = ?
            ORDER BY line_num
        """, [program_uuid]).fetchall()

        return {
            "program_uuid": program_uuid,
            "rules": [
                {
                    "uuid":          r[0],
                    "kind":          r[1],
                    "predicate":     r[2],
                    "then_summary":  r[3],
                    "else_summary":  r[4],
                    "source_file":   r[5],
                    "line":          r[6],
                }
                for r in rows
            ],
            "count": len(rows),
            "note": "Business rules extracted via IF/EVALUATE analysis"
        }
    finally:
        conn.close()

@app.get("/cfg/{program_name}", response_class=HTMLResponse)
def get_cfg_visual(program_name: str):
    """
    Returns an interactive CFG visualization as HTML.
    Open in browser: http://localhost:8000/cfg/COTRN02C
    """
    conn = get_db()
    try:
        prog = program_name.upper()

        # If UUID passed instead of name — resolve to program name
        if len(prog) == 32 and prog.isalnum():
            row = conn.execute("""
                SELECT payload_json->>'program_name' as name
                FROM nodes WHERE uuid = ?
                OR uuid = (SELECT program_uuid FROM paragraphs WHERE uuid = ?)
                LIMIT 1
            """, [prog, prog]).fetchone()
            if row and row[0]:
                prog = row[0].upper()
            else:
                # Try paragraphs table
                row = conn.execute("""
                    SELECT n.payload_json->>'program_name'
                    FROM paragraphs p
                    JOIN nodes n ON p.program_uuid = n.uuid
                    WHERE p.uuid = ?
                    LIMIT 1
                """, [prog]).fetchone()
                if row and row[0]:
                    prog = row[0].upper()

        # Get paragraphs
        paras = conn.execute("""
            SELECT name, start_line, end_line, statement_count, complexity
            FROM paragraphs
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY start_line
        """, [prog + ".cbl"]).fetchall()

        if not paras:
            raise HTTPException(status_code=404, detail=f"Program '{program_name}' not found")

        # Get CFG edges
        edges = conn.execute("""
            SELECT from_uuid, to_uuid, edge_type, condition, line_num
            FROM control_flow
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
        """, [prog + ".cbl"]).fetchall()

        # Get program metadata
        meta = conn.execute("""
            SELECT payload_json FROM nodes
            WHERE kind = 'ProgramNode'
            AND UPPER(source_file) = UPPER(?)
            LIMIT 1
        """, [prog + ".cbl"]).fetchone()

        payload = json.loads(meta[0]) if meta else {}
        prog_type = payload.get("program_type", "batch").upper()
        total_lines = payload.get("total_lines", 0)

    finally:
        conn.close()

    # Build JS data
    para_js = json.dumps([
        {
            "name":  p[0],
            "lines": f"{p[1]}-{p[2]}",
            "stmts": p[3],
            "cx":    p[4],
            "type":  ("main" if i == 0
                      else "screen" if any(k in p[0] for k in ["SEND","RECEIVE","SCREEN","RETURN"])
                      else "error" if any(k in p[0] for k in ["ABEND","ERROR","9999"])
                      else "process")
        }
        for i, p in enumerate(paras)
    ])

    edge_js = json.dumps([
        {
            "from": e[0],
            "to":   e[1],
            "type": e[2],
            "condition": e[3],
            "line": e[4],
        }
        for e in edges
    ])

    total_cx = max((p[4] for p in paras), default=1)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>CFG - {prog}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0a0e1a;font-family:'Courier New',monospace;color:#e2e8f0;overflow:hidden}}
#header{{padding:12px 20px;background:rgba(10,14,26,0.95);border-bottom:1px solid #1e3a5f;display:flex;align-items:center;gap:16px}}
#header h1{{font-size:14px;font-weight:700;color:#60a5fa;letter-spacing:2px}}
.badge{{padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;letter-spacing:1px}}
.badge-t{{background:#0f4c2a;color:#4ade80;border:1px solid #166534}}
.badge-e{{background:#1e3a5f;color:#60a5fa;border:1px solid #1d4ed8}}
.meta{{font-size:11px;color:#64748b}}
#info{{position:fixed;top:52px;right:20px;background:rgba(15,20,35,0.95);border:1px solid #1e3a5f;border-radius:6px;padding:12px 16px;font-size:10px;width:180px;z-index:100}}
#info h3{{color:#60a5fa;margin-bottom:8px;letter-spacing:1px}}
.sr{{display:flex;justify-content:space-between;margin:3px 0}}
.sl{{color:#64748b}}.sv{{color:#e2e8f0;font-weight:700}}
#legend{{position:fixed;bottom:20px;left:20px;background:rgba(15,20,35,0.95);border:1px solid #1e3a5f;border-radius:6px;padding:12px 16px;font-size:10px;z-index:100}}
#legend h3{{color:#60a5fa;margin-bottom:8px;font-size:10px;letter-spacing:1px}}
.lr{{display:flex;align-items:center;gap:8px;margin:4px 0;color:#94a3b8}}
.ll{{width:24px;height:2px}}
.ln{{width:12px;height:12px;border-radius:2px}}
#tt{{position:fixed;background:rgba(15,20,40,0.98);border:1px solid #2563eb;border-radius:6px;padding:10px 14px;font-size:11px;pointer-events:none;z-index:200;display:none}}
#tt .tn{{color:#60a5fa;font-weight:700;margin-bottom:4px}}
#tt .tr{{color:#94a3b8;margin:2px 0}}
#tt .tr span{{color:#e2e8f0}}
svg{{position:fixed;top:44px;left:0;right:0;bottom:0;width:100%;height:calc(100vh - 44px)}}
</style>
</head>
<body>
<div id="header">
  <h1>CFG &mdash; {prog}</h1>
  <span class="badge badge-t">{prog_type}</span>
  <span class="badge badge-e">{len(edges)} EDGES</span>
  <span class="meta">{len(paras)} paragraphs &middot; complexity={total_cx} &middot; {total_lines} lines</span>
</div>
<div id="info">
  <h3>PROGRAM STATS</h3>
  <div class="sr"><span class="sl">Type</span><span class="sv">{prog_type}</span></div>
  <div class="sr"><span class="sl">Lines</span><span class="sv">{total_lines:,}</span></div>
  <div class="sr"><span class="sl">Paragraphs</span><span class="sv">{len(paras)}</span></div>
  <div class="sr"><span class="sl">CFG Edges</span><span class="sv">{len(edges)}</span></div>
  <div class="sr"><span class="sl">Max Complexity</span><span class="sv">{total_cx}</span></div>
</div>
<div id="legend">
  <h3>EDGE TYPES</h3>
  <div class="lr"><div class="ll" style="background:#3b82f6"></div>PERFORM</div>
  <div class="lr"><div class="ll" style="background:#f59e0b"></div>PERFORM CONDITIONAL</div>
  <div class="lr"><div class="ll" style="background:#a855f7"></div>PERFORM UNTIL</div>
  <div class="lr"><div class="ll" style="background:#ec4899"></div>PERFORM VARYING</div>
  <div style="margin-top:8px;border-top:1px solid #1e3a5f;padding-top:8px">
  <div class="lr"><div class="ln" style="background:#0f2050;border:1px solid #3b82f6"></div>Entry</div>
  <div class="lr"><div class="ln" style="background:#1a0a35;border:1px solid #7c3aed"></div>CICS Screen</div>
  <div class="lr"><div class="ln" style="background:#1c0a0a;border:1px solid #b91c1c"></div>Error/Abend</div>
  <div class="lr"><div class="ln" style="background:#0a1525;border:1px solid #334155"></div>Processing</div>
  </div>
</div>
<div id="tt"><div class="tn" id="ttn"></div><div class="tr">Lines: <span id="ttl"></span></div><div class="tr">Stmts: <span id="tts"></span></div><div class="tr">Complexity: <span id="ttc"></span></div></div>
<svg id="svg">
<defs>
  <marker id="ab" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#3b82f6" opacity="0.8"/></marker>
  <marker id="aa" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#f59e0b" opacity="0.8"/></marker>
  <marker id="ap" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#a855f7" opacity="0.8"/></marker>
  <marker id="ak" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#ec4899" opacity="0.8"/></marker>
  <filter id="glow"><feGaussianBlur stdDeviation="2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<g id="zg"><g id="el"></g><g id="nl"></g></g>
</svg>
<script>
const paragraphs = {para_js};
const rawEdges   = {edge_js};

// Auto-layout: grid with COLS columns
const COLS=4, NW=190, NH=46, GX=28, GY=52, OX=40, OY=20;
const positions={{}};
let col=0, row=0;
paragraphs.forEach((p,i)=>{{
  if(i===0){{ positions[p.name]={{x:OX+1.5*(NW+GX), y:OY}}; return; }}
  positions[p.name]={{x:OX+col*(NW+GX), y:OY+(NH+GY)*(row+1)}};
  col++;
  if(col>=COLS){{col=0;row++;}}
}});

const ec={{PERFORM:"#3b82f6",PERFORM_CONDITIONAL:"#f59e0b",PERFORM_UNTIL:"#a855f7",PERFORM_VARYING:"#ec4899"}};
const em={{PERFORM:"url(#ab)",PERFORM_CONDITIONAL:"url(#aa)",PERFORM_UNTIL:"url(#ap)",PERFORM_VARYING:"url(#ak)"}};
const ed={{PERFORM:"none",PERFORM_CONDITIONAL:"5,3",PERFORM_UNTIL:"none",PERFORM_VARYING:"2,2"}};
const nc={{main:{{fill:"#0f2050",stroke:"#3b82f6"}},screen:{{fill:"#1a0a35",stroke:"#7c3aed"}},error:{{fill:"#1c0a0a",stroke:"#b91c1c"}},process:{{fill:"#0a1525",stroke:"#334155"}}}};

const NS="http://www.w3.org/2000/svg";
const el=document.getElementById("el"),nll=document.getElementById("nl"),tt=document.getElementById("tt");

rawEdges.forEach(e=>{{
  const fp=positions[e.from],tp=positions[e.to];
  if(!fp||!tp)return;
  const x1=fp.x+NW/2,y1=fp.y+NH,x2=tp.x+NW/2,y2=tp.y,cy=(y1+y2)/2;
  const g=document.createElementNS(NS,"g");
  const p=document.createElementNS(NS,"path");
  p.setAttribute("d",`M ${{x1}} ${{y1}} C ${{x1}} ${{cy}}, ${{x2}} ${{cy}}, ${{x2}} ${{y2}}`);
  p.setAttribute("fill","none");
  p.setAttribute("stroke",ec[e.type]||"#3b82f6");
  p.setAttribute("stroke-width","1.5");
  p.setAttribute("stroke-dasharray",ed[e.type]||"none");
  p.setAttribute("marker-end",em[e.type]||"url(#ab)");
  p.setAttribute("opacity","0.55");
  g.appendChild(p);el.appendChild(g);
}});

paragraphs.forEach((p,i)=>{{
  const pp=positions[p.name];if(!pp)return;
  const c=nc[p.type]||nc.process;
  const g=document.createElementNS(NS,"g");
  g.setAttribute("transform",`translate(${{pp.x}},${{pp.y}})`);
  if(i===0)g.setAttribute("filter","url(#glow)");
  const r=document.createElementNS(NS,"rect");
  r.setAttribute("width",NW);r.setAttribute("height",NH);r.setAttribute("rx",4);
  r.setAttribute("fill",c.fill);r.setAttribute("stroke",c.stroke);
  r.setAttribute("stroke-width",i===0?"2":"1");
  const bw=Math.min((p.cx/25)*NW,NW-4);
  const b=document.createElementNS(NS,"rect");
  b.setAttribute("x",2);b.setAttribute("y",NH-4);b.setAttribute("width",bw);b.setAttribute("height",2);
  b.setAttribute("rx",1);b.setAttribute("fill",p.cx>15?"#ef4444":p.cx>8?"#f59e0b":"#22c55e");b.setAttribute("opacity","0.7");
  const t=document.createElementNS(NS,"text");
  t.setAttribute("x",NW/2);t.setAttribute("y",18);t.setAttribute("text-anchor","middle");
  t.setAttribute("dominant-baseline","middle");t.setAttribute("fill","#e2e8f0");
  t.setAttribute("font-size","9.5");t.setAttribute("font-family","Courier New,monospace");
  t.textContent=p.name.length>25?p.name.substring(0,23)+"..":p.name;
  const m=document.createElementNS(NS,"text");
  m.setAttribute("x",NW/2);m.setAttribute("y",34);m.setAttribute("text-anchor","middle");
  m.setAttribute("fill","#94a3b8");m.setAttribute("font-size","8");
  m.setAttribute("font-family","Courier New,monospace");
  m.textContent=`stmts=${{p.stmts}} cx=${{p.cx}}`;
  g.appendChild(r);g.appendChild(b);g.appendChild(t);g.appendChild(m);
  g.style.cursor="pointer";
  g.addEventListener("mouseenter",ev=>{{
    document.getElementById("ttn").textContent=p.name;
    document.getElementById("ttl").textContent=p.lines;
    document.getElementById("tts").textContent=p.stmts;
    document.getElementById("ttc").textContent=p.cx;
    tt.style.display="block";tt.style.left=(ev.clientX+12)+"px";tt.style.top=(ev.clientY-10)+"px";
  }});
  g.addEventListener("mousemove",ev=>{{tt.style.left=(ev.clientX+12)+"px";tt.style.top=(ev.clientY-10)+"px";}});
  g.addEventListener("mouseleave",()=>{{tt.style.display="none";}});
  nll.appendChild(g);
}});

let vx=0,vy=0,sc=1,dr=false,sx,sy;
const svg=document.getElementById("svg");
svg.addEventListener("mousedown",e=>{{dr=true;sx=e.clientX-vx;sy=e.clientY-vy;}});
svg.addEventListener("mousemove",e=>{{if(!dr)return;vx=e.clientX-sx;vy=e.clientY-sy;document.getElementById("zg").setAttribute("transform",`translate(${{vx}},${{vy}}) scale(${{sc}})`)}});
svg.addEventListener("mouseup",()=>dr=false);
svg.addEventListener("wheel",e=>{{e.preventDefault();sc=Math.max(0.3,Math.min(2.5,sc-e.deltaY*0.001));document.getElementById("zg").setAttribute("transform",`translate(${{vx}},${{vy}}) scale(${{sc}})`)}});
const sw=window.innerWidth,gw=COLS*(NW+GX);
vx=(sw-gw)/2-OX+20;vy=10;
document.getElementById("zg").setAttribute("transform",`translate(${{vx}},${{vy}}) scale(${{sc}})`);
</script>
</body>
</html>"""
    return HTMLResponse(content=html)

@app.get("/connectivity/{program_name}")
def get_connectivity(program_name: str):
    """Aggregates CALL, XCTL, COPY, COMMAREA, JCL connections for one program."""
    conn = get_db()
    try:
        prog = program_name.upper()

        callees = conn.execute("""
            SELECT id, call_target, call_type, source_file, line_num
            FROM call_graph
            WHERE UPPER(caller_uuid) = UPPER(?)
            ORDER BY line_num
        """, [prog]).fetchall()

        callers = conn.execute("""
            SELECT caller_uuid, call_type, source_file, line_num
            FROM call_graph WHERE UPPER(call_target) = ?
            ORDER BY line_num
        """, [prog]).fetchall()

        copybooks = conn.execute("""
            SELECT cu.copybook_name, cu.source_file
            FROM copybook_use cu
            JOIN nodes n ON cu.program_uuid = n.uuid
            WHERE n.kind = 'ProgramNode'
            AND UPPER(n.source_file) = UPPER(?)
            ORDER BY cu.copybook_name
        """, [prog + ".cbl"]).fetchall()

        shared = conn.execute("""
            SELECT DISTINCT cu2.program_uuid, cu2.copybook_name
            FROM copybook_use cu1
            JOIN nodes n ON cu1.program_uuid = n.uuid
            JOIN copybook_use cu2 ON cu1.copybook_name = cu2.copybook_name
            WHERE n.kind = 'ProgramNode'
            AND UPPER(n.source_file) = UPPER(?)
            AND cu2.program_uuid != cu1.program_uuid
            ORDER BY cu2.copybook_name LIMIT 20
        """, [prog + ".cbl"]).fetchall()

        commarea = conn.execute("""
            SELECT from_program_uuid, to_program_uuid,
                   edge_type, transid, commarea_size, line_num
            FROM transaction_flow
            WHERE UPPER(from_program_uuid) = ?
               OR UPPER(to_program_uuid) = ?
        """, [prog, prog]).fetchall()

        jobs = conn.execute("""
            SELECT DISTINCT job_name, step_name, source_file
            FROM jcl_job WHERE UPPER(program_name) = ?
            ORDER BY job_name
        """, [prog]).fetchall()

        # Get program UUID
        prog_node = conn.execute("""
            SELECT uuid FROM nodes
            WHERE kind = 'ProgramNode'
            AND UPPER(source_file) = UPPER(?)
            LIMIT 1
        """, [program_name.upper() + ".cbl"]).fetchone()
        program_uuid = prog_node[0] if prog_node else None

        return {
            "program": prog,
            "program_uuid": program_uuid,
            "connectivity_summary": {
                "call_edges_out":        len([c for c in callees if c[1] == "CALL"]),
                "xctl_edges_out":        len([c for c in callees if c[1] == "CICS_XCTL"]),
                "callers":               len(callers),
                "copybooks_used":        len(copybooks),
                "shared_copybook_progs": len(set(r[0] for r in shared)),
                "commarea_connections":  len(commarea),
                "jcl_jobs":             len(jobs),
            },
            "calls":              [{"target": c[0], "type": c[1], "file": c[2], "line": c[3]} for c in callees],
            "callers":            [{"caller": c[0], "type": c[1], "file": c[2], "line": c[3]} for c in callers],
            "copybooks":          [{"name": c[0], "file": c[1]} for c in copybooks],
            "shared_via_copybook":[{"program": r[0], "shared_copybook": r[1]} for r in shared],
            "commarea":           [{"from": c[0], "to": c[1], "type": c[2], "transid": c[3], "commarea_size": c[4], "line": c[5]} for c in commarea],
            "jcl_jobs":           [{"job_name": j[0], "step_name": j[1], "file": j[2]} for j in jobs],
        }
    finally:
        conn.close()
@app.get("/db2")
def get_db2_schema():
    """Get DB2 table definitions from DDL parsing."""
    db2_path = OUT_DIR / "artifacts" / "layer6" / "db2_schema.json"
    if not db2_path.exists():
        raise HTTPException(status_code=404, detail="DB2 schema not found")
    data = _load_json(db2_path)
    return {
        "table_count":  data.get("table_count", 0),
        "index_count":  data.get("index_count", 0),
        "tables":       data.get("tables", []),
        "indexes":      data.get("indexes", []),
    }

@app.get("/ims")
def get_ims_schema(program: Optional[str] = None):
    """Get IMS DLI statements. Optional ?program=COPAUA0C filter."""
    conn = get_db()
    try:
        if program:
            rows = conn.execute("""
                SELECT id, program_uuid, segment_name, operation,
                   pcb_name, source_file, line_num
                FROM ims_io
                WHERE UPPER(program_uuid) = UPPER(?)
                ORDER BY line_num
            """, [program]).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, program_uuid, segment_name, operation,
                   pcb_name, source_file, line_num
                FROM ims_io
                ORDER BY source_file, line_num
            """).fetchall()

        dbd_path = OUT_DIR / "artifacts" / "layer6" / "ims_dbd_schema.json"
        dbd_data = _load_json(dbd_path) if dbd_path.exists() else {}

        return {
            "program_filter":      program or "ALL",
            "dli_statement_count": len(rows),
            "dli_statements": [
                {"uuid": r[0], "program": r[1], "segment": r[2], 
                 "operation": r[3], "pcb": r[4], "file": r[5], "line": r[6]}
                for r in rows
            ],
            "databases": dbd_data.get("databases", []) if not program else [],
            "dbd_count":  dbd_data.get("dbd_count", 0),
        }
    finally:
        conn.close()


@app.get("/mq")
def get_mq_graph(program: Optional[str] = None):
    """Get MQ queue access. Optional ?program=COPAUA0C filter."""
    conn = get_db()
    try:
        if program:
            rows = conn.execute("""
                SELECT id, program_uuid, queue_name, operation,
                       source_file, line_num
                FROM mq_io
                WHERE UPPER(program_uuid) = UPPER(?)
                ORDER BY line_num
            """, [program]).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, program_uuid, queue_name, operation,
                       source_file, line_num
                FROM mq_io
                ORDER BY source_file, line_num
            """).fetchall()

        return {
            "program_filter": program or "ALL",
            "mq_call_count":  len(rows),
            "calls": [
                {"uuid": r[0], "program": r[1], "queue": r[2], 
                 "operation": r[3], "file": r[4], "line": r[5]}
                for r in rows
            ],
            "notes": [
                "MQ uses CALL-based API (MQOPEN/MQGET/MQPUT1/MQCLOSE)",
                "Only in app-authorization-ims-db2-mq extension module",
            ],
        }
    finally:
        conn.close()

@app.get("/vsam")
def get_vsam_schemas():
    """Get VSAM file schemas — key, record length, AIX, programs using."""
    import hashlib
    vsam_path = OUT_DIR / "artifacts" / "layer6" / "vsam_schemas.json"
    if not vsam_path.exists():
        raise HTTPException(status_code=404, detail="VSAM schemas not found")
    data    = _load_json(vsam_path)
    schemas = data.get("schemas", [])
    for s in schemas:
        s["uuid"] = hashlib.sha256(s["dsn"].encode()).hexdigest()[:32]
    return {
        "vsam_count": data.get("vsam_count", 0),
        "schemas":    schemas,
        "notes": [
            "KSDS: Key-Sequenced Dataset (most common, keyed access)",
            "ESDS: Entry-Sequenced Dataset (sequential, no key)",
            "RRDS: Relative Record Dataset (fixed-length, relative record number)",
            "AIX: Alternate Index (secondary access path over base cluster)",
        ]
    }


@app.get("/gdg")
def get_gdg_registry():
    """Get GDG (Generation Data Group) registry and PDS references."""
    import hashlib
    gdg_path = OUT_DIR / "artifacts" / "layer4" / "gdg_pds_registry.json"
    if not gdg_path.exists():
        raise HTTPException(status_code=404, detail="GDG registry not found")
    data      = _load_json(gdg_path)
    gdg_bases = data.get("gdg_bases", [])
    for g in gdg_bases:
        g["uuid"] = hashlib.sha256(g["base_dsn"].encode()).hexdigest()[:32]
        for ref in g.get("references", []):
            ref["uuid"] = hashlib.sha256(
                f"{g['base_dsn']}:{ref['job']}:{ref['generation']}".encode()
            ).hexdigest()[:32]
    return {
        "gdg_count": data.get("gdg_count", 0),
        "pds_count": data.get("pds_count", 0),
        "gdg_bases": gdg_bases,
        "pds_refs":  data.get("pds_refs", []),
        "notes":     data.get("notes", []),
    }


@app.get("/dataformats/{program_name}")
def get_data_formats_for_program(program_name: str):
    """Get advanced data format breakdown for a specific program."""
    conn = get_db()
    try:
        prog = program_name.upper()
        rows = conn.execute("""
            SELECT s.uuid, s.name, s.pic, s.usage, s.canonical_type,
                   s.copybook_origin, s.defined_at_line
            FROM symbols s
            JOIN nodes n ON s.program_uuid = n.uuid
            WHERE n.kind = 'ProgramNode'
            AND UPPER(n.source_file) = UPPER(?)
            AND s.canonical_type IS NOT NULL
            ORDER BY s.defined_at_line
        """, [prog + ".cbl"]).fetchall()

        if not rows:
            raise HTTPException(status_code=404,
                detail=f"Program '{program_name}' not found")

        # Group by kind
        by_kind = {}
        for r in rows:
            try:
                ct = json.loads(r[3]) if r[3] else {}
            except (json.JSONDecodeError, TypeError):
                ct = {}
            kind = ct.get("kind", "unknown")
            if kind not in by_kind:
                by_kind[kind] = []
            by_kind[kind].append({
                    "uuid":           r[0],
                    "name":           r[1],
                    "pic":            r[2],
                    "usage":          r[3],
                    "canonical_type": ct,
                    "copybook":       r[5],
                    "line":           r[6],
                })

        return {
            "program":      prog,
            "total_symbols": len(rows),
            "by_kind": {
                kind: {"count": len(items), "items": items[:5]}
                for kind, items in sorted(by_kind.items(),
                                          key=lambda x: -len(x[1]))
            },
            "forward_engineering_notes": {
                "alphanumeric":   "→ String",
                "numeric":        "→ long/int (zoned decimal)",
                "decimal":        "→ BigDecimal (scaled)",
                "binary":         "→ int/long (COMP/COMP-4)",
                "packed_decimal": "→ BigDecimal COMP-3 (check rounding)",
                "edited_numeric": "→ String (display formatting only)",
                "group":          "→ class/struct",
            }
        }
    finally:
        conn.close()

@app.get("/spec/{program_name}")
def get_program_spec(program_name: str, refresh: bool = False):
    """
    Generate LLM-powered grounded specification for any program.
    Cached in out/demo/ — use ?refresh=true to regenerate.
    Every claim cites UUID from artifact store.
    """
    import os
    prog = program_name.upper()
    demo_dir = OUT_DIR / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    cached_path = demo_dir / f"{prog}_spec.json"

    # Return cached if exists and not refreshing
    if cached_path.exists() and not refresh:
        data = json.loads(cached_path.read_text())
        data["cached"] = True
        return data

    # Check OPEN API key
    nvidia_key = os.environ.get("OPENAI_API_KEY", "")
    if not nvidia_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY not set — set environment variable to enable spec generation"
        )

    # Generate spec
    try:
        from src.llm.spec_generator import generate_program_spec
        result = generate_program_spec(prog, output_dir=demo_dir)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        result["cached"] = False
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/slice/{program_name}")
def get_program_slice(program_name: str):
    """
    Returns the structured artifact slice sent to the LLM for spec generation.
    Use this to verify Rule 1 compliance — no raw source in the context.
    """
    from src.llm.retrieval import assemble_program_slice, format_slice_for_llm
    try:
        slice_data = assemble_program_slice(program_name.upper())
        context    = format_slice_for_llm(slice_data)
        return {
            "program":       program_name.upper(),
            "slice_data":    slice_data,
            "formatted_context": context,
            "rule1_note":    "No raw COBOL source — only structured artifacts with UUIDs",
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/explore", response_class=HTMLResponse)
def get_explorer_index():
    """Interactive graph explorer — entry point showing all programs."""
    conn = get_db()
    try:
        programs = conn.execute("""
            SELECT payload_json->>'program_name' as name, source_file
            FROM nodes WHERE kind = 'ProgramNode'
            ORDER BY name
        """).fetchall()
    finally:
        conn.close()

    prog_list = "".join([
        f'<a href="/explore/{p[0]}" style="display:block;padding:6px 12px;'
        f'margin:3px 0;border:1px solid #1e3a5f;border-radius:3px;'
        f'color:#60a5fa;font-family:Courier New,monospace;font-size:12px;'
        f'text-decoration:none;background:#0f1a2e" '
        f'onmouseover="this.style.background=\'#1e3a5f\'" '
        f'onmouseout="this.style.background=\'#0f1a2e\'">'
        f'{p[0]}</a>'
        for p in programs if p[0]
    ])

    return HTMLResponse(content=f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>CardDemo Explorer</title>
<style>
  body{{background:#0a0e1a;color:#e2e8f0;font-family:'Courier New',monospace;
        display:flex;flex-direction:column;align-items:center;padding:40px 20px}}
  h1{{color:#60a5fa;letter-spacing:3px;font-size:18px;margin-bottom:8px}}
  p{{color:#64748b;font-size:11px;margin-bottom:24px}}
  .grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:700px;width:100%}}
</style></head><body>
<h1>CARDDEMO GRAPH EXPLORER</h1>
<p>Select a program to explore its artifacts, connections and specifications</p>
<div class="grid">{prog_list}</div>
</body></html>""")


@app.get("/explore/{program_name}", response_class=HTMLResponse)
def get_explorer(program_name: str):
    """
    Interactive D3.js graph explorer for any program.
    Shows all artifacts — paragraphs, symbols, CFG, business rules,
    call graph, copybooks, file I/O, IMS, MQ — as a navigable graph.
    Click nodes to inspect. Double-click to expand.
    """
    from pathlib import Path
    template_path = Path(__file__).parent.parent.parent / "out" / "demo" / "explore_template.html"

    if template_path.exists():
        html = template_path.read_text(encoding="utf-8")
    else:
        raise HTTPException(status_code=500, detail="Explorer template not found")

    html = html.replace('{PROGRAM}', program_name.upper())
    return HTMLResponse(content=html)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
