import sys, json, duckdb, uuid as uuid_lib
from pathlib import Path
sys.path.insert(0, ".")
from config import OUT_DIR

conn = duckdb.connect(str(OUT_DIR / "graph" / "artifacts.duckdb"))

# Load call graph edges
cg_path = OUT_DIR / "artifacts" / "layer4" / "call_graph.json"
if cg_path.exists():
    data  = json.loads(cg_path.read_text())
    edges = data.get("edges", [])
    rows  = []
    for e in edges:
        rows.append((
            str(uuid_lib.uuid4()).replace("-","")[:32],
            e.get("caller",""),
            e.get("callee",""),
            None,  # call_site_uuid
            e.get("call_type",""),
            e.get("callee",""),
            e.get("is_dynamic", False),
            e.get("source_file",""),
            e.get("line", 0),
        ))
    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO call_graph
            (id, caller_uuid, callee_uuid, call_site_uuid, call_type,
             call_target, is_dynamic, source_file, line_num)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, rows)
    print(f"Call graph: {len(rows)} edges loaded")

# Load file_io
fio_path = OUT_DIR / "artifacts" / "layer4" / "file_io.json"
if fio_path.exists():
    data = json.loads(fio_path.read_text())
    ops  = data.get("operations", [])
    rows = []
    for op in ops:
        rows.append((
            str(uuid_lib.uuid4()).replace("-","")[:32],
            op.get("program",""),
            op.get("file_name",""),
            op.get("operation",""),
            None,  # record_copybook
            None,  # stmt_uuid
            op.get("source_file",""),
            op.get("line", 0),
        ))
    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO file_io
            (id, program_uuid, file_name, operation, record_copybook,
             stmt_uuid, source_file, line_num)
            VALUES (?,?,?,?,?,?,?,?)
        """, rows)
    print(f"File I/O: {len(rows)} operations loaded")

# Load transaction flow
tf_path = OUT_DIR / "artifacts" / "layer4" / "transaction_flow.json"
if tf_path.exists():
    data  = json.loads(tf_path.read_text())
    edges = data.get("edges", [])
    rows  = []
    for e in edges:
        rows.append((
            e.get("id", str(uuid_lib.uuid4()).replace("-","")[:32]),
            e.get("from_program",""),
            e.get("to_program",""),
            e.get("edge_type",""),
            e.get("from_transid",""),
            e.get("commarea_size"),
            None,
            e.get("source_file",""),
            e.get("line", 0),
        ))
    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO transaction_flow
            (id, from_program_uuid, to_program_uuid, edge_type,
             transid, commarea_size, stmt_uuid, source_file, line_num)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, rows)
    print(f"Transaction flow: {len(rows)} edges loaded")

# Load JCL jobs
jcl_path = OUT_DIR / "artifacts" / "jcl" / "jcl_graph.json"
if jcl_path.exists():
    data = json.loads(jcl_path.read_text())
    jobs = data.get("jobs", [])
    rows = []
    for j in jobs:
        rows.append((
            j.get("id",""),
            j.get("job_name",""),
            j.get("step_name",""),
            j.get("program_name",""),
            j.get("dd_name",""),
            j.get("dataset_name",""),
            j.get("disposition",""),
            j.get("steplib",""),
            j.get("parm",""),
            j.get("source_file",""),
            0,
        ))
    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO jcl_job
            (id, job_name, step_name, program_name, dd_name,
             dataset_name, disposition, steplib, parm, source_file, line_num)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
    print(f"JCL jobs: {len(rows)} records loaded")

    # Load JCL dependencies
    deps = data.get("dependencies", [])
    rows = []
    for d in deps:
        rows.append((
            d.get("id",""),
            d.get("producer_job",""),
            d.get("consumer_job",""),
            d.get("dataset_name",""),
            d.get("producer_disp",""),
            d.get("consumer_disp",""),
        ))
    if rows:
        conn.executemany("""
            INSERT OR IGNORE INTO jcl_dependency
            (id, producer_job, consumer_job, dataset_name,
             producer_disp, consumer_disp)
            VALUES (?,?,?,?,?,?)
        """, rows)
    print(f"JCL dependencies: {len(rows)} edges loaded")

conn.close()
print("Done!")
