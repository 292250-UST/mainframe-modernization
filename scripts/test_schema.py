import sys, duckdb
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR

db_path = OUT_DIR / "graph" / "artifacts.duckdb"
conn = duckdb.connect(str(db_path))

# Read and execute schema manually
schema = Path("src/storage/schema.sql").read_text(encoding="utf-8")

# Remove comments and split
lines = [l for l in schema.split("\n") if not l.strip().startswith("--")]
sql = "\n".join(lines)
statements = [s.strip() for s in sql.split(";") if s.strip()]

print(f"Found {len(statements)} statements")
for i, stmt in enumerate(statements):
    try:
        conn.execute(stmt)
        print(f"  OK: {stmt[:60]}")
    except Exception as e:
        print(f"  ERR: {stmt[:60]}")
        print(f"       {e}")

tables = conn.execute("SHOW TABLES").fetchall()
print(f"\nTables created: {[t[0] for t in tables]}")
conn.close()
