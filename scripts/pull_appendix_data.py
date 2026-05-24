import sys, json, duckdb
from pathlib import Path
sys.path.insert(0, '.')
from config import OUT_DIR

conn = duckdb.connect(str(OUT_DIR / 'graph' / 'artifacts.duckdb'), read_only=True)

# L1 paragraph
para = conn.execute("""
    SELECT uuid, kind, source_file, start_line, end_line, parent_uuid, payload_json
    FROM nodes WHERE kind='ParagraphNode' AND UPPER(source_file)='COTRN02C.CBL'
    LIMIT 1
""").fetchone()
payload = json.loads(para[6]) if para[6] else {}
print('L1:', para[0], payload.get('name'), para[3], para[4], para[5])

# L2 decimal symbol
prog_uuid = para[5]
sym = conn.execute("""
    SELECT uuid, name, level, pic, usage, scope, canonical_type, copybook_origin, defined_at_line
    FROM symbols WHERE program_uuid=? AND canonical_type LIKE '%decimal%' AND level=5 LIMIT 1
""", [prog_uuid]).fetchone()
if not sym:
    sym = conn.execute("SELECT uuid, name, level, pic, usage, scope, canonical_type, copybook_origin, defined_at_line FROM symbols WHERE program_uuid=? AND level=5 LIMIT 1", [prog_uuid]).fetchone()
ct = json.loads(sym[6]) if sym[6] else {}
print('L2:', sym[0], sym[1], sym[2], sym[3], sym[4], ct)

# L3 def-use
rows = conn.execute("SELECT id, data_item_uuid, operation, line_num FROM def_use WHERE UPPER(source_file)='COTRN02C.CBL' ORDER BY line_num LIMIT 6").fetchall()
print('L3 writes:', [(r[0][:16], r[1][:20], r[2], r[3]) for r in rows if r[2]=='WRITE'][:2])
print('L3 reads:', [(r[0][:16], r[1][:20], r[2], r[3]) for r in rows if r[2]=='READ'][:2])

# L4 file io
fio = conn.execute("SELECT id, program_uuid, file_name, operation, record_copybook, line_num FROM file_io WHERE UPPER(program_uuid) LIKE '%COTRN%' OR UPPER(program_uuid)='CBACT01C' LIMIT 2").fetchall()
for r in fio: print('L4:', r)

# L5 business rule
br = conn.execute("SELECT uuid, program_uuid, kind, predicate_raw, then_summary, else_summary, line_num FROM business_rules WHERE UPPER(source_file)='COTRN02C.CBL' ORDER BY line_num LIMIT 1").fetchone()
print('L5:', br)

# L8 IR
ir_path = OUT_DIR / 'artifacts' / 'layer8' / 'COTRN02C_ir.json'
ir = json.loads(ir_path.read_text())
f = ir['fields'][5]
print('L8 field:', f['uuid'][:16], f['name'], f['java_type'], f['constraint'])
m = ir['methods'][0]
print('L8 method:', m['uuid'][:16], m['name'], len(m['calls']), 'calls')

conn.close()
