import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR
from src.layers.l4_system_graphs.cfg_builder import extract_cfg_from_file
import json, duckdb, uuid as uuid_lib

ext_dir = Path("corpus/app/app-authorization-ims-db2-mq/cbl")
all_cfgs = []
all_edges = []

for cbl_file in sorted(list(ext_dir.glob("*.cbl")) + list(ext_dir.glob("*.CBL"))):
    cfg = extract_cfg_from_file(cbl_file)
    all_cfgs.append(cfg)
    all_edges.extend(cfg["edges"])
    print(f"  {cbl_file.name}: {len(cfg['paragraphs'])} paragraphs, {len(cfg['edges'])} edges")

# Load into DuckDB
DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"
conn = duckdb.connect(str(DB_PATH))
rows = []
for cfg in all_cfgs:
    for edge in cfg["edges"]:
        rows.append((
            str(uuid_lib.uuid4()).replace("-","")[:32],
            cfg["program"],
            edge["from_para"], edge["to_para"],
            edge["edge_type"], edge.get("condition"),
            edge["source_file"], edge["line"],
        ))
if rows:
    conn.executemany("""
        INSERT OR IGNORE INTO control_flow
        (id, program_uuid, from_uuid, to_uuid, edge_type,
         condition, source_file, line_num)
        VALUES (?,?,?,?,?,?,?,?)
    """, rows)
    print(f"Extension CFG: {len(rows)} edges loaded")

# Save extension artifact
artifact = {"layer": "L4", "total_edges": len(all_edges), "cfgs": all_cfgs}
out_path  = OUT_DIR / "artifacts" / "layer4" / "cfg_ext.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(artifact, f, indent=2)

conn.close()
print(f"Done: {len(all_edges)} CFG edges for extension module")
