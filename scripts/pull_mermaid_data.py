import sys, json, duckdb
from pathlib import Path
sys.path.insert(0, '.')
from config import OUT_DIR

DB_PATH = OUT_DIR / 'graph' / 'artifacts.duckdb'
conn = duckdb.connect(str(DB_PATH), read_only=True)

# 1. Call graph
print('=== CALL GRAPH ===')
rows = conn.execute("""
    SELECT caller_uuid, call_target, call_type
    FROM call_graph
    ORDER BY caller_uuid, call_type
""").fetchall()
for r in rows:
    print(f'  {r[0]:<20} --{r[2]}--> {r[1]}')

# 2. Transaction flow
print('\n=== TRANSACTION FLOW ===')
rows = conn.execute("""
    SELECT from_program_uuid, to_program_uuid, edge_type, transid
    FROM transaction_flow
    ORDER BY from_program_uuid
    LIMIT 30
""").fetchall()
for r in rows:
    print(f'  {r[0]:<15} --{r[2]}--> {r[1]:<15} transid={r[3]}')

# 3. JCL job chain
print('\n=== JCL JOB CHAIN ===')
rows = conn.execute("""
    SELECT DISTINCT job_name, step_name, program_name
    FROM jcl_job
    WHERE program_name IS NOT NULL
    ORDER BY job_name, step_name
    LIMIT 40
""").fetchall()
for r in rows:
    print(f'  {r[0]:<15} step={r[1]:<20} pgm={r[2]}')

# 4. File I/O
print('\n=== FILE I/O ===')
rows = conn.execute("""
    SELECT program_uuid, file_name, operation
    FROM file_io
    ORDER BY program_uuid, file_name
    LIMIT 40
""").fetchall()
for r in rows:
    print(f'  {r[0]:<15} --{r[2]}--> {r[1]}')

conn.close()
