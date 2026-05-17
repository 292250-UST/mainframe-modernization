import sys, duckdb, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR

conn = duckdb.connect(str(OUT_DIR / "graph" / "artifacts.duckdb"))

print("=== Programs in DB ===")
programs = conn.execute("""
    SELECT payload_json->>'program_name' as name,
           payload_json->>'program_type' as type,
           end_line - start_line + 1 as lines
    FROM nodes WHERE kind = 'ProgramNode'
    ORDER BY name
""").fetchall()
for p in programs[:10]:
    print(f"  {p[0]:<25} {p[1]:<10} {p[2]} lines")
print(f"  ... {len(programs)} total programs")

print("\n=== Top 5 programs by symbol count ===")
top = conn.execute("""
    SELECT n.payload_json->>'program_name' as prog,
           COUNT(s.uuid) as sym_count
    FROM symbols s
    JOIN nodes n ON s.program_uuid = n.uuid
    GROUP BY prog ORDER BY sym_count DESC LIMIT 5
""").fetchall()
for t in top:
    print(f"  {t[0]:<30} {t[1]} symbols")

print("\n=== Copybook usage summary ===")
cb = conn.execute("""
    SELECT copybook_name, COUNT(*) as programs_using
    FROM copybook_use
    GROUP BY copybook_name
    ORDER BY programs_using DESC LIMIT 10
""").fetchall()
for c in cb:
    print(f"  {c[0]:<25} used by {c[1]} programs")

conn.close()
