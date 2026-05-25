import sys, json, duckdb
from pathlib import Path
sys.path.insert(0, '.')
from config import OUT_DIR

DB_PATH = OUT_DIR / 'graph' / 'artifacts.duckdb'
conn = duckdb.connect(str(DB_PATH), read_only=True)

print('=== DEAD CODE ANALYSIS ===')

# 1. Never-PERFORM'd paragraphs
# A paragraph is dead if its name never appears as to_uuid in control_flow
all_paras = conn.execute("""
    SELECT p.uuid, p.name, p.source_file, p.program_uuid,
           p.start_line, p.statement_count, p.complexity
    FROM paragraphs p
""").fetchall()

performed = set(r[0] for r in conn.execute("""
    SELECT DISTINCT UPPER(to_uuid) FROM control_flow
""").fetchall())

# Also check by name
performed_names = set(r[0] for r in conn.execute("""
    SELECT DISTINCT UPPER(to_uuid) FROM control_flow
""").fetchall())

# Entry point paragraphs (never need to be PERFORM'd)
ENTRY_POINTS = {'MAIN-PARA','0000-MAIN','MAIN','000-MAIN','A000-MAINLINE'}

dead_paras = []
for p in all_paras:
    uuid, name, sf, prog, line, stmts, complexity = p
    if name.upper() in ENTRY_POINTS:
        continue
    if uuid.upper() not in performed and name.upper() not in performed_names:
        dead_paras.append(p)

print(f'Total paragraphs:      {len(all_paras)}')
print(f'Never PERFORM-d:       {len(dead_paras)}')
for p in dead_paras[:10]:
    print(f'  {p[1]:<40} {p[2]} line {p[4]}')

# 2. Never-read variables
never_read = conn.execute("""
    SELECT s.uuid, s.name, s.source_file, s.defined_at_line, s.level
    FROM symbols s
    WHERE s.level IN (5, 77)
    AND s.name NOT IN (
        SELECT DISTINCT data_item_uuid FROM def_use WHERE operation='READ'
    )
    AND s.name NOT LIKE '%FILLER%'
    ORDER BY s.source_file, s.defined_at_line
    LIMIT 20
""").fetchall()
print(f'\nSample never-read variables (top 20):')
for r in never_read:
    print(f'  L{r[4]:02} {r[1]:<35} {r[2]}:{r[3]}')

# 3. Files defined but never accessed
vsam_path = OUT_DIR / 'artifacts' / 'layer6' / 'vsam_schemas.json'
if vsam_path.exists():
    vsam = json.loads(vsam_path.read_text())
    vsam_names = set(s['name'].upper() for s in vsam.get('schemas',[]))
    accessed = set(r[0].upper() for r in conn.execute(
        "SELECT DISTINCT UPPER(file_name) FROM file_io"
    ).fetchall())
    never_accessed = vsam_names - accessed
    print(f'\nVSAM files never accessed in file_io: {never_accessed or "none"}')

conn.close()
