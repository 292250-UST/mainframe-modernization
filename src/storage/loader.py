"""
loader.py
=========
Loads Layer 1 + Layer 2 artifacts into DuckDB.

WHY THIS EXISTS:
    All graph queries (call graph, def-use, CFG) run against DuckDB.
    This module reads the JSON artifacts and populates the database.

WHAT IT LOADS:
    - nodes table: ProgramNode + ParagraphNode from *_ast.json
    - symbols table: from *_symbols.json
    - paragraphs table: from *_paragraphs.json
    - copybook_use table: from *_provenance.json

DOWNSTREAM CONSUMERS:
    - db_queries.py    (all API endpoint queries)
    - cfg_builder.py   (Day 4 — reads paragraphs table)
    - call_graph.py    (Day 4 — writes call_graph table)
"""

import json
import duckdb
from pathlib import Path
from typing import Optional
import uuid as uuid_lib

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("storage.loader")

LAYER1_DIR = OUT_DIR / "artifacts" / "layer1"
LAYER2_DIR = OUT_DIR / "artifacts" / "layer2"
DB_PATH    = OUT_DIR / "graph" / "artifacts.duckdb"


def get_connection(db_path: Optional[Path] = None) -> duckdb.DuckDBPyConnection:
    """
    Get a DuckDB connection, creating the database if needed.

    Args:
        db_path: Path to .duckdb file. Defaults to out/graph/artifacts.duckdb

    Returns:
        DuckDB connection object
    """
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    logger.debug(f"Connected to DuckDB: {db_path}")
    return conn


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")

    # Remove only full-line comments (lines starting with --)
    # Do NOT strip inline comments or comments inside CREATE TABLE
    lines = [l for l in sql.split("\n") if not l.strip().startswith("--")]
    clean_sql = "\n".join(lines)

    # Split on semicolons and execute each statement
    statements = [s.strip() for s in clean_sql.split(";") if s.strip()]
    for stmt in statements:
        conn.execute(stmt)

    logger.info(f"DuckDB schema initialized ({len(statements)} tables)")


def load_ast_nodes(
    conn: duckdb.DuckDBPyConnection,
    layer1_dir: Optional[Path] = None
) -> int:
    """
    Load ProgramNode and ParagraphNode from *_ast.json artifacts.

    Populates: nodes table

    Args:
        conn: DuckDB connection
        layer1_dir: Directory containing *_ast.json files

    Returns:
        int: Number of nodes loaded
    """
    layer1_dir = layer1_dir or LAYER1_DIR
    ast_files  = list(layer1_dir.glob("*_ast.json"))
    total      = 0

    logger.info(f"Loading AST nodes from {len(ast_files)} files")

    for ast_file in ast_files:
        data = json.loads(ast_file.read_text(encoding="utf-8"))
        nodes_to_load = []

        # Program node
        pn = data.get("program_node", {})
        if pn:
            sr = pn.get("source_range", {})
            nodes_to_load.append((
                pn["uuid"],
                pn["kind"],
                sr.get("source_file", ""),
                sr.get("start_line", 1),
                sr.get("end_line", 1),
                sr.get("start_col", 1),
                sr.get("end_col", 72),
                pn.get("parent_uuid"),
                sr.get("copybook"),
                json.dumps(pn.get("payload", {}))
            ))

        # Paragraph nodes
        for para in data.get("paragraph_nodes", []):
            sr = para.get("source_range", {})
            nodes_to_load.append((
                para["uuid"],
                para["kind"],
                sr.get("source_file", ""),
                sr.get("start_line", 1),
                sr.get("end_line", 1),
                sr.get("start_col", 1),
                sr.get("end_col", 72),
                para.get("parent_uuid"),
                sr.get("copybook"),
                json.dumps(para.get("payload", {}))
            ))

        if nodes_to_load:
            conn.executemany("""
                INSERT OR IGNORE INTO nodes
                (uuid, kind, source_file, start_line, end_line,
                 start_col, end_col, parent_uuid, copybook, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, nodes_to_load)
            total += len(nodes_to_load)

    logger.info(f"Loaded {total} AST nodes into DuckDB")
    return total


def load_symbols(
    conn: duckdb.DuckDBPyConnection,
    layer2_dir: Optional[Path] = None
) -> int:
    """
    Load symbol table entries from *_symbols.json artifacts.

    Populates: symbols table

    Args:
        conn: DuckDB connection
        layer2_dir: Directory containing *_symbols.json files

    Returns:
        int: Number of symbols loaded
    """
    layer2_dir  = layer2_dir or LAYER2_DIR
    sym_files   = list(layer2_dir.glob("*_symbols.json"))
    total       = 0

    logger.info(f"Loading symbols from {len(sym_files)} files")

    for sym_file in sym_files:
        data    = json.loads(sym_file.read_text(encoding="utf-8"))
        symbols = data.get("symbols", [])

        # Get program UUID from nodes table
        source_file  = data.get("source_file", "")
        program_uuid = _get_program_uuid(conn, source_file)

        rows = []
        for sym in symbols:
            rows.append((
                sym["uuid"],
                program_uuid,
                sym.get("name", ""),
                sym.get("level"),
                sym.get("pic"),
                sym.get("usage", "DISPLAY"),
                sym.get("scope", "WORKING-STORAGE"),
                json.dumps(sym.get("canonical_type", {})),
                sym.get("copybook_origin"),
                source_file,
                sym.get("defined_at_line"),
                json.dumps(sym)
            ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO symbols
                (uuid, program_uuid, name, level, pic, usage, scope,
                 canonical_type, copybook_origin, source_file,
                 defined_at_line, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            total += len(rows)

    logger.info(f"Loaded {total} symbols into DuckDB")
    return total


def load_paragraphs(
    conn: duckdb.DuckDBPyConnection,
    layer2_dir: Optional[Path] = None
) -> int:
    """
    Load paragraph inventory from *_paragraphs.json artifacts.

    Populates: paragraphs table

    Args:
        conn: DuckDB connection
        layer2_dir: Directory containing *_paragraphs.json files

    Returns:
        int: Number of paragraphs loaded
    """
    layer2_dir = layer2_dir or LAYER2_DIR
    para_files = list(layer2_dir.glob("*_paragraphs.json"))
    total      = 0

    logger.info(f"Loading paragraphs from {len(para_files)} files")

    for para_file in para_files:
        data       = json.loads(para_file.read_text(encoding="utf-8"))
        paragraphs = data.get("paragraphs", [])
        source_file = data.get("source_file", "")
        program_uuid = _get_program_uuid(conn, source_file)

        rows = []
        for para in paragraphs:
            rows.append((
                para["uuid"],
                program_uuid,
                para.get("name", ""),
                source_file,
                para.get("start_line"),
                para.get("end_line"),
                para.get("line_count", 0),
                para.get("statement_count", 0),
                para.get("complexity", 1),
                json.dumps(para)
            ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO paragraphs
                (uuid, program_uuid, name, source_file, start_line,
                 end_line, line_count, statement_count, complexity, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
            total += len(rows)

    logger.info(f"Loaded {total} paragraphs into DuckDB")
    return total


def load_copybook_use(
    conn: duckdb.DuckDBPyConnection,
    layer1_dir: Optional[Path] = None
) -> int:
    """
    Load copybook usage from *_provenance.json artifacts.

    Populates: copybook_use table

    Args:
        conn: DuckDB connection
        layer1_dir: Directory containing *_provenance.json files

    Returns:
        int: Number of copybook usage edges loaded
    """
    layer1_dir = layer1_dir or LAYER1_DIR
    prov_files = list(layer1_dir.glob("*_provenance.json"))
    total      = 0

    logger.info(f"Loading copybook usage from {len(prov_files)} files")

    for prov_file in prov_files:
        data        = json.loads(prov_file.read_text(encoding="utf-8"))
        source_file = data.get("source_file", "")
        program_uuid = _get_program_uuid(conn, source_file)
        summary     = data.get("summary", {})
        copybooks   = summary.get("copybooks_used", [])

        if not program_uuid:
            logger.debug(f"Skipping copybook_use for {source_file} — no program node found")
            continue

        rows = []
        for cb_name in copybooks:
            edge_id = str(uuid_lib.uuid4()).replace("-","")[:32]
            rows.append((
                edge_id,
                program_uuid,
                cb_name,
                json.dumps([]),
                source_file,
                0
            ))

        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO copybook_use
                (id, program_uuid, copybook_name, replacing_rules,
                 source_file, line_num)
                VALUES (?, ?, ?, ?, ?, ?)
            """, rows)
            total += len(rows)

    logger.info(f"Loaded {total} copybook usage edges into DuckDB")
    return total


def _get_program_uuid(
    conn: duckdb.DuckDBPyConnection,
    source_file: str
) -> Optional[str]:
    """
    Look up the UUID of a program node by source file name.

    Args:
        conn:        DuckDB connection
        source_file: e.g. 'CBACT01C.cbl'

    Returns:
        str: UUID of the ProgramNode, or None if not found
    """
    result = conn.execute("""
        SELECT uuid FROM nodes
        WHERE source_file = ? AND kind = 'ProgramNode'
        LIMIT 1
    """, [source_file]).fetchone()

    return result[0] if result else None

def _load_day4_artifacts(db_path: Optional[Path] = None) -> None:
    """Load call graph, file I/O, transaction flow, JCL into DuckDB."""
    import uuid as uuid_lib
    conn = get_connection(db_path)
    try:
        # Call graph
        cg_path = OUT_DIR / "artifacts" / "layer4" / "call_graph.json"
        if cg_path.exists():
            data = json.loads(cg_path.read_text())
            rows = []
            for e in data.get("edges", []):
                rows.append((
                    str(uuid_lib.uuid4()).replace("-","")[:32],
                    e.get("caller",""), e.get("callee",""),
                    None, e.get("call_type",""), e.get("callee",""),
                    e.get("is_dynamic", False), e.get("source_file",""),
                    e.get("line", 0),
                ))
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO call_graph
                    (id, caller_uuid, callee_uuid, call_site_uuid, call_type,
                     call_target, is_dynamic, source_file, line_num)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, rows)
            logger.info(f"Call graph: {len(rows)} edges loaded")

        # File I/O
        fio_path = OUT_DIR / "artifacts" / "layer4" / "file_io.json"
        if fio_path.exists():
            data = json.loads(fio_path.read_text())
            ops  = data.get("operations", [])
            rows = [(str(uuid_lib.uuid4()).replace("-","")[:32],
                     op.get("program",""), op.get("file_name",""),
                     op.get("operation",""), None, None,
                     op.get("source_file",""), op.get("line", 0))
                    for op in ops]
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO file_io
                    (id, program_uuid, file_name, operation, record_copybook,
                     stmt_uuid, source_file, line_num)
                    VALUES (?,?,?,?,?,?,?,?)
                """, rows)
            logger.info(f"File I/O: {len(rows)} operations loaded")

        # Transaction flow
        tf_path = OUT_DIR / "artifacts" / "layer4" / "transaction_flow.json"
        if tf_path.exists():
            data  = json.loads(tf_path.read_text())
            edges = data.get("edges", [])
            rows  = [(e.get("id", str(uuid_lib.uuid4()).replace("-","")[:32]),
                      e.get("from_program",""), e.get("to_program",""),
                      e.get("edge_type",""), e.get("from_transid",""),
                      e.get("commarea_size"), None,
                      e.get("source_file",""), e.get("line", 0))
                     for e in edges]
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO transaction_flow
                    (id, from_program_uuid, to_program_uuid, edge_type,
                     transid, commarea_size, stmt_uuid, source_file, line_num)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, rows)
            logger.info(f"Transaction flow: {len(rows)} edges loaded")

        # JCL
        jcl_path = OUT_DIR / "artifacts" / "jcl" / "jcl_graph.json"
        if jcl_path.exists():
            data = json.loads(jcl_path.read_text())
            jobs = data.get("jobs", [])
            rows = [(j.get("id",""), j.get("job_name",""), j.get("step_name",""),
                     j.get("program_name",""), j.get("dd_name",""),
                     j.get("dataset_name",""), j.get("disposition",""),
                     j.get("steplib",""), j.get("parm",""),
                     j.get("source_file",""), 0)
                    for j in jobs]
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO jcl_job
                    (id, job_name, step_name, program_name, dd_name,
                     dataset_name, disposition, steplib, parm, source_file, line_num)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, rows)
            logger.info(f"JCL jobs: {len(rows)} loaded")

            deps = data.get("dependencies", [])
            rows = [(d.get("id",""), d.get("producer_job",""),
                     d.get("consumer_job",""), d.get("dataset_name",""),
                     d.get("producer_disp",""), d.get("consumer_disp",""))
                    for d in deps]
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO jcl_dependency
                    (id, producer_job, consumer_job, dataset_name,
                     producer_disp, consumer_disp)
                    VALUES (?,?,?,?,?,?)
                """, rows)
            logger.info(f"JCL dependencies: {len(rows)} loaded")
    finally:
        conn.close()


def _load_business_rules(db_path: Optional[Path] = None) -> None:
    """Load business rules into DuckDB."""
    conn = get_connection(db_path)
    try:
        br_path = OUT_DIR / "artifacts" / "layer5" / "business_rules.json"
        if not br_path.exists():
            logger.warning("Business rules artifact not found — run business_rules_extractor first")
            return
        data  = json.loads(br_path.read_text())
        rules = data.get("rules", [])
        rows  = [(r["uuid"], r["program"], r["kind"],
                  r["predicate_raw"], json.dumps({}),
                  r["then_summary"], r["else_summary"],
                  r["source_file"], r["line"])
                 for r in rules]
        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO business_rules
                (uuid, program_uuid, kind, predicate_raw, predicate_resolved,
                 then_summary, else_summary, source_file, line_num)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, rows)
        logger.info(f"Business rules: {len(rows)} loaded")
    finally:
        conn.close()


def _load_cfg(db_path: Optional[Path] = None) -> None:
    """Load CFG edges into DuckDB."""
    import uuid as uuid_lib
    conn = get_connection(db_path)
    try:
        cfg_path = OUT_DIR / "artifacts" / "layer4" / "cfg.json"
        if not cfg_path.exists():
            return
        data = json.loads(cfg_path.read_text())
        rows = []
        for cfg in data.get("cfgs", []):
            prog = cfg["program"]
            row = conn.execute("""
                SELECT uuid FROM nodes
                WHERE kind = 'ProgramNode'
                AND UPPER(source_file) = UPPER(?)
                LIMIT 1
            """, [cfg["source_file"]]).fetchone()
            prog_uuid = row[0] if row else prog
            for edge in cfg.get("edges", []):
                rows.append((
                    str(uuid_lib.uuid4()).replace("-","")[:32],
                    prog_uuid,
                    edge["from_para"], edge["to_para"],
                    edge["edge_type"], edge.get("condition"),
                    edge["source_file"], edge["line"],
                ))
        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO control_flow
                (id, program_uuid, from_uuid, to_uuid, edge_type,
                 condition, source_file, line_num)
                VALUES (?,?,?,?,?,?,?,?)
            """, rows)
        logger.info(f"CFG: {len(rows)} edges loaded")
    finally:
        conn.close()


def _load_def_use(db_path: Optional[Path] = None) -> None:
    """Load def-use chains into DuckDB."""
    import uuid as uuid_lib
    conn = get_connection(db_path)
    try:
        du_path = OUT_DIR / "artifacts" / "layer5" / "def_use.json"
        if not du_path.exists():
            return
        data  = json.loads(du_path.read_text())
        rows  = [(str(uuid_lib.uuid4()).replace("-","")[:32],
                  r["variable"], r["operation"], None,
                  r["stmt_text"], r["source_file"], r["line"])
                 for r in data.get("entries", [])]
        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO def_use
                (id, data_item_uuid, operation, stmt_uuid,
                 stmt_text, source_file, line_num)
                VALUES (?,?,?,?,?,?,?)
            """, rows)
        logger.info(f"Def-use: {len(rows)} entries loaded")
    finally:
        conn.close()


def _load_dli_mq(db_path: Optional[Path] = None) -> None:
    """Load DLI and MQ statements into DuckDB."""
    import uuid as uuid_lib
    conn = get_connection(db_path)
    try:
        # DLI
        dli_path = OUT_DIR / "artifacts" / "layer3" / "dli_statements.json"
        if dli_path.exists():
            data = json.loads(dli_path.read_text())
            rows = [(str(uuid_lib.uuid4()).replace("-","")[:32],
                     s["program"], s["segment"], s["verb"],
                     s["pcb"], s["source_file"], s["line"])
                    for s in data.get("statements", [])]
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO ims_io
                    (id, program_uuid, segment_name, operation,
                     pcb_name, source_file, line_num)
                    VALUES (?,?,?,?,?,?,?)
                """, rows)
            logger.info(f"IMS I/O: {len(rows)} DLI statements loaded")

        # MQ
        mq_path = OUT_DIR / "artifacts" / "layer3" / "mq_statements.json"
        if mq_path.exists():
            data = json.loads(mq_path.read_text())
            rows = []
            seen = set()
            for s in data.get("statements", []):
                key = (s["program"], s["verb"], s["line"])
                if key in seen:
                    continue
                seen.add(key)
                op = "PUT" if "PUT" in s["verb"] else "GET" if "GET" in s["verb"] else s["verb"]
                rows.append((str(uuid_lib.uuid4()).replace("-","")[:32],
                             s["program"], s.get("queue",""),
                             op, None, s["source_file"], s["line"]))
            if rows:
                conn.executemany("""
                    INSERT OR IGNORE INTO mq_io
                    (id, program_uuid, queue_name, operation,
                     correlation_id, source_file, line_num)
                    VALUES (?,?,?,?,?,?,?)
                """, rows)
            logger.info(f"MQ I/O: {len(rows)} calls loaded")
    finally:
        conn.close()

def run_full_load(db_path: Optional[Path] = None) -> dict:
    """
    Run the complete load pipeline — all layers into DuckDB.

    Order matters:
    1. Schema init
    2. AST nodes (programs + paragraphs) — must be first (FK source)
    3. Symbols (FK -> nodes)
    4. Paragraphs (FK -> nodes)
    5. Copybook use (FK -> nodes)
    6. Call graph
    7. File I/O
    8. Transaction flow
    9. JCL jobs + dependencies
    10. Business rules
    11. CFG
    12. Def-use
    13. IMS I/O (DLI)
    14. MQ I/O
    """
    conn = get_connection(db_path)
    logger.info("Starting full DuckDB load")
    logger.info("=" * 50)

    init_schema(conn)

    # Layer 1+2
    nodes_count   = load_ast_nodes(conn)
    symbols_count = load_symbols(conn)
    paras_count   = load_paragraphs(conn)
    cb_use_count  = load_copybook_use(conn)

    conn.close()

    # Layer 4 artifacts (call graph, file I/O, tx flow, JCL)
    _load_day4_artifacts(db_path)

    # Business rules
    _load_business_rules(db_path)

    # CFG
    _load_cfg(db_path)

    # Def-use
    _load_def_use(db_path)

    # DLI + MQ
    _load_dli_mq(db_path)

    summary = {
        "nodes":        nodes_count,
        "symbols":      symbols_count,
        "paragraphs":   paras_count,
        "copybook_use": cb_use_count,
        "db_path":      str(db_path or DB_PATH),
    }

    logger.info("=" * 50)
    logger.info("DuckDB load complete:")
    for k, v in summary.items():
        if k != "db_path":
            logger.info(f"  {k:<20}: {v}")
    logger.info(f"  Database: {summary['db_path']}")

    return summary


if __name__ == "__main__":
    run_full_load()
