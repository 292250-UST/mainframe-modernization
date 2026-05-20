import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR, CORPUS_DIR

# The mapping we need:
# CSD name (ACCTDAT) <-> JCL DD name (ACCTFILE) <-> COBOL SELECT name (ACCTFILE-FILE)
# We can derive this from JCL: //ACCTFILE DD DSN=AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS

# Load JCL graph
jcl_path = OUT_DIR / "artifacts" / "jcl" / "jcl_graph.json"
jcl_data = json.loads(jcl_path.read_text())

# Build DSN -> DD name mapping from JCL
dsn_to_dd = {}
for job in jcl_data["jobs"]:
    dsn = job.get("dataset_name", "")
    dd  = job.get("dd_name", "")
    if dsn and dd and not dd.startswith("SYS"):
        dsn_to_dd[dsn] = dd

print("=== DSN -> DD mapping (sample) ===")
for dsn, dd in list(dsn_to_dd.items())[:10]:
    print(f"  {dd:<15} <- {dsn}")

# Load VSAM schemas
vsam_path = OUT_DIR / "artifacts" / "layer6" / "vsam_schemas.json"
vsam_data = json.loads(vsam_path.read_text())

# For each VSAM schema, find matching DSN in JCL
print("\n=== VSAM schema enrichment ===")
for schema in vsam_data["schemas"]:
    dsn = schema["dsn"]
    dd  = dsn_to_dd.get(dsn, "")
    if dd:
        schema["jcl_dd_name"] = dd
        print(f"  {schema['name']:<12} -> DD={dd} DSN={dsn[:40]}")
    else:
        schema["jcl_dd_name"] = ""
        print(f"  {schema['name']:<12} -> NO JCL MATCH for {dsn[:40]}")

# Now match COBOL SELECT statements
SELECT_PATTERN = re.compile(
    r'SELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?([A-Z0-9-]+)',
    re.IGNORECASE
)
FD_PATTERN     = re.compile(r'^.{6}\s+FD\s+([A-Z0-9-]+)', re.IGNORECASE | re.MULTILINE)
RECORD_PATTERN = re.compile(r'RECORD(?:\s+CONTAINS)?\s+(\d+)', re.IGNORECASE)
KEY_PATTERN    = re.compile(r'(?:RECORD\s+KEY|KEY\s+IS)\s+([A-Z0-9-]+)', re.IGNORECASE)

for cbl_file in sorted((CORPUS_DIR / "app" / "cbl").glob("*.cbl")):
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    prog    = cbl_file.stem.upper()

    # Build SELECT map: logical-name -> assign-name
    select_map = {}
    for m in SELECT_PATTERN.finditer(content):
        select_map[m.group(1).upper()] = m.group(2).upper()

    # For each VSAM schema, check if any SELECT ASSIGN matches DD name
    for schema in vsam_data["schemas"]:
        dd_name = schema.get("jcl_dd_name", "")
        if not dd_name:
            continue

        # Find SELECT that assigns to this DD name
        for logical, assign in select_map.items():
            if assign == dd_name or assign == dd_name + "FILE" or dd_name in assign:
                if prog not in schema["programs_using"]:
                    schema["programs_using"].append(prog)

                # Get record length from FD
                fd_pattern = re.compile(
                    rf'^.{{6}}\s+FD\s+{re.escape(logical)}(.*?)(?=^.{{6}}\s+FD\s|\Z)',
                    re.IGNORECASE | re.MULTILINE | re.DOTALL
                )
                fd_m = fd_pattern.search(content)
                if fd_m:
                    rec_m = RECORD_PATTERN.search(fd_m.group(1))
                    if rec_m and schema["record_length"] == 0:
                        schema["record_length"] = int(rec_m.group(1))
                    key_m = KEY_PATTERN.search(fd_m.group(1))
                    if key_m and not schema.get("key_field"):
                        schema["key_field"] = key_m.group(1).upper()

# Save enriched artifact
with open(vsam_path, "w", encoding="utf-8") as f:
    json.dump(vsam_data, f, indent=2)

print("\n=== Final VSAM schemas ===")
for s in vsam_data["schemas"]:
    print(f"  {s['name']:<12} type={s['vsam_type']:<6} "
          f"len={s['record_length']:4} "
          f"key={s.get('key_field',''):<20} "
          f"progs={len(s['programs_using'])}")
