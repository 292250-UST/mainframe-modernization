import sys, json, duckdb, re, uuid as uuid_lib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR

DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"
conn    = duckdb.connect(str(DB_PATH))

# Load DLI into ims_io
dli_path = OUT_DIR / "artifacts" / "layer3" / "dli_statements.json"
dli_data = json.loads(dli_path.read_text())
rows = []
for s in dli_data["statements"]:
    rows.append((
        str(uuid_lib.uuid4()).replace("-","")[:32],
        s["program"],
        s["segment"],
        s["verb"],
        s["pcb"],
        s["source_file"],
        s["line"],
    ))
if rows:
    conn.executemany("""
        INSERT OR IGNORE INTO ims_io
        (id, program_uuid, segment_name, operation, pcb_name, source_file, line_num)
        VALUES (?,?,?,?,?,?,?)
    """, rows)
    print(f"IMS I/O: {len(rows)} DLI statements loaded")

# Extract MQ calls (CALL 'MQXXX') from extension COBOL
ext_dir  = Path("corpus/app/app-authorization-ims-db2-mq/cbl")
mq_stmts = []
MQ_PATTERN = re.compile(
    r"CALL\s+'(MQ(?:OPEN|CLOSE|PUT1?|GET|CONN|DISC|BACK|CMIT))'\s+USING\s+([^\n]+)",
    re.IGNORECASE
)
PARA_PATTERN = re.compile(r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$', re.IGNORECASE)

for cbl_file in sorted(list(ext_dir.glob("*.cbl")) + list(ext_dir.glob("*.CBL"))):
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()
    current_para = "MAIN"
    for i, line in enumerate(lines):
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
        for m in MQ_PATTERN.finditer(line):
            verb    = m.group(1).upper()
            using   = m.group(2).strip()[:100]
            # Determine queue name from USING parameters
            queue   = ""
            if "OD" in using.upper():
                queue = "REQUEST-QUEUE"
            elif "REPLY" in using.upper():
                queue = "REPLY-QUEUE"
            mq_stmts.append({
                "program":    cbl_file.stem.upper(),
                "queue":      queue,
                "verb":       verb,
                "using":      using,
                "paragraph":  current_para,
                "line":       i + 1,
                "source_file": cbl_file.name,
            })

print(f"\nMQ calls found: {len(mq_stmts)}")
for s in mq_stmts:
    print(f"  {s['program']:<15} {s['verb']:<10} queue={s['queue']} line={s['line']}")

# Load MQ into mq_io
mq_rows = []
for s in mq_stmts:
    op = "PUT" if "PUT" in s["verb"] else "GET" if "GET" in s["verb"] else s["verb"]
    mq_rows.append((
        str(uuid_lib.uuid4()).replace("-","")[:32],
        s["program"],
        s["queue"],
        op,
        None,  # correlation_id
        s["source_file"],
        s["line"],
    ))
if mq_rows:
    conn.executemany("""
        INSERT OR IGNORE INTO mq_io
        (id, program_uuid, queue_name, operation, correlation_id, source_file, line_num)
        VALUES (?,?,?,?,?,?,?)
    """, mq_rows)
    print(f"MQ I/O: {len(mq_rows)} MQ calls loaded")

# Save MQ artifact
mq_artifact = {
    "layer": "L3",
    "total": len(mq_stmts),
    "statements": mq_stmts
}
mq_path = OUT_DIR / "artifacts" / "layer3" / "mq_statements.json"
with open(mq_path, "w", encoding="utf-8") as f:
    json.dump(mq_artifact, f, indent=2)
print(f"Saved: {mq_path}")

conn.close()
