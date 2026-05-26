import sys, duckdb, json
from pathlib import Path
sys.path.insert(0, '.')
from config import OUT_DIR

conn = duckdb.connect(str(OUT_DIR / 'graph' / 'artifacts.duckdb'), read_only=True)
out  = Path('docs/mermaid')
out.mkdir(parents=True, exist_ok=True)

# 1. Call graph
rows = conn.execute("""
    SELECT DISTINCT caller_uuid, call_target, call_type
    FROM call_graph ORDER BY caller_uuid
""").fetchall()
lines = ['graph TD']
seen = set()
for caller, target, ctype in rows:
    edge = f'    {caller} -->|{ctype}| {target}'
    if edge not in seen:
        seen.add(edge)
        lines.append(edge)
(out / 'call_graph.mmd').write_text('\n'.join(lines))
print(f'call_graph.mmd: {len(lines)-1} edges')

# 2. Transaction flow
rows = conn.execute("""
    SELECT DISTINCT from_program_uuid, to_program_uuid, edge_type, transid
    FROM transaction_flow WHERE to_program_uuid != ''
    ORDER BY from_program_uuid
""").fetchall()
lines = ['graph LR']
seen = set()
for frm, to, etype, transid in rows:
    label = f'{etype}:{transid}' if transid else etype
    edge = f'    {frm} -->|{label}| {to}'
    if edge not in seen:
        seen.add(edge)
        lines.append(edge)
(out / 'transaction_flow.mmd').write_text('\n'.join(lines))
print(f'transaction_flow.mmd: {len(lines)-1} edges')

# 3. JCL job chain
rows = conn.execute("""
    SELECT DISTINCT job_name, program_name
    FROM jcl_job WHERE program_name IS NOT NULL
    AND program_name NOT IN ('IDCAMS','SORT','IEFBR14','IKJEFT1B','DFHCSDUP')
    ORDER BY job_name
""").fetchall()
lines = ['graph TD']
seen = set()
for job, pgm in rows:
    edge = f'    {job}["JOB:{job}"] --> {pgm}["{pgm}"]'
    if edge not in seen:
        seen.add(edge)
        lines.append(edge)
(out / 'jcl_chain.mmd').write_text('\n'.join(lines))
print(f'jcl_chain.mmd: {len(lines)-1} edges')

# 4. File I/O
rows = conn.execute("""
    SELECT DISTINCT program_uuid, file_name, operation
    FROM file_io ORDER BY program_uuid, file_name
""").fetchall()
lines = ['graph LR']
seen = set()
for prog, fname, op in rows:
    edge = f'    {prog} -->|{op}| {fname.replace("-","_")}[("{fname}")]'
    if edge not in seen:
        seen.add(edge)
        lines.append(edge)
(out / 'file_io.mmd').write_text('\n'.join(lines))
print(f'file_io.mmd: {len(lines)-1} edges')

conn.close()
print('All Mermaid diagrams saved to docs/mermaid/')
