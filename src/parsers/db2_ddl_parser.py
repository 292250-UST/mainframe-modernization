"""
db2_ddl_parser.py
=================
Parses DB2 DDL files extracting table and index definitions.
Populates db_io table with schema information.
"""

import re
import json
import duckdb
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("parsers.db2_ddl_parser")

DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"

# Patterns
TABLE_PATTERN  = re.compile(r'CREATE\s+TABLE\s+([A-Z0-9_.]+)', re.IGNORECASE)
INDEX_PATTERN  = re.compile(r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+([A-Z0-9_.]+)\s+ON\s+([A-Z0-9_.]+)', re.IGNORECASE)
COLUMN_PATTERN = re.compile(r'[\s(,]+([A-Z_][A-Z0-9_]{1,29})\s+(CHAR|VARCHAR|INTEGER|SMALLINT|DECIMAL|TIMESTAMP|DATE|TIME)(?:\(([^)]+)\))?(\s+NOT\s+NULL)?', re.IGNORECASE)
PK_PATTERN     = re.compile(r'PRIMARY\s+KEY\s*\(([^)]+)\)', re.IGNORECASE)
FK_PATTERN     = re.compile(r'REFERENCES\s+([A-Z0-9_.]+)\s*\(([^)]+)\)', re.IGNORECASE)


def parse_ddl_file(ddl_file: Path) -> dict:
    """Parse one DB2 DDL file."""
    content = ddl_file.read_text(encoding="utf-8", errors="replace")
    result  = {
        "source_file": ddl_file.name,
        "tables":      [],
        "indexes":     [],
    }

    # Extract tables
    for table_m in TABLE_PATTERN.finditer(content):
        table_name = table_m.group(1).strip()
        # Find table body
        start = table_m.end()
        depth = 0
        body  = ""
        for i, c in enumerate(content[start:]):
            if c == "(": depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    body = content[start:start+i+1]
                    break

        # Extract columns
        columns = []
        for col_m in COLUMN_PATTERN.finditer(body):
            col = {
                "name":     col_m.group(1).upper(),
                "type":     col_m.group(2).upper(),
                "size":     col_m.group(3) or "",
                "not_null": bool(col_m.group(4)),
            }
            columns.append(col)

        # Extract PK
        pk_m = PK_PATTERN.search(body)
        pk   = [c.strip() for c in pk_m.group(1).split(",")] if pk_m else []

        # Extract FK
        fk_m = FK_PATTERN.search(body)
        fk   = {
            "references_table":  fk_m.group(1).strip() if fk_m else "",
            "references_columns": fk_m.group(2).strip() if fk_m else "",
        }

        result["tables"].append({
            "table_name": table_name,
            "columns":    columns,
            "primary_key": pk,
            "foreign_key": fk,
            "column_count": len(columns),
        })
        logger.debug(f"Table: {table_name} ({len(columns)} columns)")

    # Extract indexes
    for idx_m in INDEX_PATTERN.finditer(content):
        result["indexes"].append({
            "index_name": idx_m.group(1).strip(),
            "table_name": idx_m.group(2).strip(),
        })

    return result


def run(output_dir: Optional[Path] = None) -> dict:
    """Parse all DB2 DDL files and load into DuckDB."""
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer6")
    output_dir.mkdir(parents=True, exist_ok=True)

    ddl_dirs = [
        Path("corpus/app/app-authorization-ims-db2-mq/ddl"),
        Path("corpus/app/app-transaction-type-db2/ddl"),
    ]

    all_tables  = []
    all_indexes = []

    for ddl_dir in ddl_dirs:
        if not ddl_dir.exists():
            continue
        files = sorted(list(ddl_dir.glob("*.ddl")) + list(ddl_dir.glob("*.DDL")))
        # Deduplicate by stem
        seen = {}
        for f in files:
            if f.stem.upper() not in seen:
                seen[f.stem.upper()] = f
        files = list(seen.values())

        for f in files:
            result = parse_ddl_file(f)
            all_tables.extend(result["tables"])
            all_indexes.extend(result["indexes"])
            logger.info(f"Parsed {f.name}: {len(result['tables'])} tables, {len(result['indexes'])} indexes")

    # Load into DuckDB db_io table
    conn = duckdb.connect(str(DB_PATH))
    rows = []
    for table in all_tables:
        cols = ",".join(c["name"] for c in table["columns"][:10])
        rows.append((
            str(uuid_lib.uuid4()).replace("-","")[:32],
            "DB2_DDL",           # program_uuid (schema definition not program)
            table["table_name"],
            cols,
            "CREATE",
            None,               # cursor_name
            None,               # stmt_uuid
            "DB2_DDL",
            0,
        ))

    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO db_io
            (id, program_uuid, table_name, columns, operation,
             cursor_name, stmt_uuid, source_file, line_num)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, rows)
    conn.close()

    # Save artifact
    artifact = {
        "layer":       "L6",
        "table_count": len(all_tables),
        "index_count": len(all_indexes),
        "tables":      all_tables,
        "indexes":     all_indexes,
    }

    output_path = output_dir / "db2_schema.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"DB2 DDL: {len(all_tables)} tables, {len(all_indexes)} indexes")
    return artifact


if __name__ == "__main__":
    result = run()
    print(f"Tables: {result['table_count']}")
    print(f"Indexes: {result['index_count']}")
    for t in result["tables"]:
        print(f"\n  {t['table_name']} ({t['column_count']} columns)")
        for c in t["columns"]:
            nn = " NOT NULL" if c["not_null"] else ""
            print(f"    {c['name']:<30} {c['type']}{('('+c['size']+')') if c['size'] else ''}{nn}")
        if t["primary_key"]:
            print(f"    PK: {t['primary_key']}")
