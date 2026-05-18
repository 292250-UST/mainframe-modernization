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

        # Get paragraph count
        para_count = conn.execute("""
            SELECT COUNT(*) FROM paragraphs WHERE program_uuid = ?
        """, [uuid]).fetchone()[0]

        # Get symbol count
        sym_count = conn.execute("""
            SELECT COUNT(*) FROM symbols WHERE program_uuid = ?
        """, [uuid]).fetchone()[0]

        # Get copybooks used
        copybooks = conn.execute("""
            SELECT copybook_name FROM copybook_use WHERE program_uuid = ?
        """, [uuid]).fetchall()

        return {
            "uuid":           uuid,
            "program_name":   payload.get("program_name", program_name),
            "source_file":    source_file,
            "program_type":   payload.get("program_type", "unknown"),
            "total_lines":    end_line - start_line + 1,
            "paragraph_count": para_count,
            "symbol_count":   sym_count,
            "copybooks":      [c[0] for c in copybooks],
            "payload":        payload,
        }
    finally:
        conn.close()


@app.get("/paragraph/{uuid}")
def get_paragraph(uuid: str):
    """Get paragraph details by UUID."""
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT uuid, source_file, start_line, end_line, payload_json
            FROM nodes WHERE uuid = ? AND kind = 'ParagraphNode'
        """, [uuid]).fetchone()

        if not row:
            # Try paragraphs table
            row2 = conn.execute("""
                SELECT uuid, source_file, start_line, end_line,
                       statement_count, complexity, name, payload_json
                FROM paragraphs WHERE uuid = ?
            """, [uuid]).fetchone()

            if not row2:
                raise HTTPException(
                    status_code=404,
                    detail=f"Paragraph '{uuid}' not found"
                )
            uuid, sf, sl, el, stmts, cx, name, payload = row2
            return {
                "uuid":            uuid,
                "name":            name,
                "source_file":     sf,
                "start_line":      sl,
                "end_line":        el,
                "statement_count": stmts,
                "complexity":      cx,
            }

        uuid, sf, sl, el, payload_json = row
        payload = json.loads(payload_json) if payload_json else {}
        return {
            "uuid":        uuid,
            "name":        payload.get("name", ""),
            "source_file": sf,
            "start_line":  sl,
            "end_line":    el,
            "payload":     payload,
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
            SELECT caller_uuid, call_type, call_target, source_file, line_num
            FROM call_graph
            WHERE UPPER(callee_uuid) = UPPER(?)
               OR UPPER(call_target) = UPPER(?)
        """, [program_name, program_name]).fetchall()

        return {
            "program":  program_name,
            "callers":  [
                {
                    "caller":      r[0],
                    "call_type":   r[1],
                    "call_target": r[2],
                    "source_file": r[3],
                    "line":        r[4],
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
            SELECT callee_uuid, call_type, call_target, source_file, line_num
            FROM call_graph
            WHERE UPPER(caller_uuid) = UPPER(?)
        """, [program_name.upper()]).fetchall()

        return {
            "program":  program_name,
            "callees":  [
                {
                    "callee":      r[0],
                    "call_type":   r[1],
                    "call_target": r[2],
                    "source_file": r[3],
                    "line":        r[4],
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
            SELECT step_name, program_name, dd_name,
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

        return {
            "job_name":     job_name,
            "steps":        [
                {
                    "step_name":    r[0],
                    "program":      r[1],
                    "dd_name":      r[2],
                    "dataset":      r[3],
                    "disposition":  r[4],
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

        raise HTTPException(
            status_code=404,
            detail=f"UUID '{uuid}' not found in any artifact table"
        )
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Business rules + Control flow + Def-use (stub endpoints)
# -----------------------------------------------------------------------

@app.get("/controlflow/{program_uuid}")
def get_control_flow(program_uuid: str):
    """Get CFG for a program (stub — populated Day 6)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT from_uuid, to_uuid, edge_type, condition
            FROM control_flow
            WHERE program_uuid = ?
        """, [program_uuid]).fetchall()

        return {
            "program_uuid": program_uuid,
            "edges": [
                {
                    "from_uuid":  r[0],
                    "to_uuid":    r[1],
                    "edge_type":  r[2],
                    "condition":  r[3],
                }
                for r in rows
            ],
            "count": len(rows),
            "note": "CFG population in progress (Day 6)"
        }
    finally:
        conn.close()


@app.get("/defuse/{dataitem_uuid}")
def get_def_use(dataitem_uuid: str):
    """Get def-use chain for a data item (stub — populated Day 6)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT operation, stmt_text, source_file, line_num
            FROM def_use WHERE data_item_uuid = ?
        """, [dataitem_uuid]).fetchall()
        return {
                    "data_item_uuid": dataitem_uuid,
                    "chain": [
                        {
                            "operation":   r[0],
                            "stmt_text":   r[1],
                            "source_file": r[2],
                            "line":        r[3],
                        }
                        for r in rows
                    ],
                    "count": len(rows),
                    "note": "Def-use chain population in progress (Day 6)"
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
            "note": "Business rules extraction in progress (Day 6)"
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
