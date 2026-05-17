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


def run_full_load(db_path: Optional[Path] = None) -> dict:
    """
    Run the complete load pipeline — all layers into DuckDB.

    Order matters:
    1. Schema init
    2. AST nodes (programs + paragraphs) — must be first (FK source)
    3. Symbols (FK -> nodes)
    4. Paragraphs (FK -> nodes)
    5. Copybook use (FK -> nodes)

    Args:
        db_path: Path to .duckdb file

    Returns:
        dict: Summary of rows loaded per table
    """
    conn = get_connection(db_path)

    logger.info("Starting full DuckDB load")
    logger.info("=" * 50)

    init_schema(conn)

    nodes_count    = load_ast_nodes(conn)
    symbols_count  = load_symbols(conn)
    paras_count    = load_paragraphs(conn)
    cb_use_count   = load_copybook_use(conn)

    conn.close()

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
