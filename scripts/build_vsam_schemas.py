import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR, CORPUS_DIR

# Build VSAM schema from 3 sources:
# 1. CSD catalog (file names, DSNs, access permissions)
# 2. COBOL FD entries (record layouts, copybooks)
# 3. JCL DD statements (disposition, sharing)

vsam_schemas = {}

# Source 1: CSD catalog
csd_path = OUT_DIR / "artifacts" / "layer6" / "csd_catalog.json"
csd_data = json.loads(csd_path.read_text())
for f in csd_data.get("files", []):
    name = f["name"].upper()
    vsam_schemas[name] = {
        "name":        name,
        "dsn":         f.get("dsname", ""),
        "status":      f.get("status", ""),
        "access":      {
            "read":    f.get("read", ""),
            "add":     f.get("add", ""),
            "update":  f.get("update", ""),
            "delete":  f.get("delete", ""),
        },
        "vsam_type":   "KSDS",  # default, refined below
        "key_offset":  0,
        "key_length":  0,
        "record_length": 0,
        "record_copybook": "",
        "alternate_indexes": [],
        "programs_using": [],
    }

# Detect AIX (alternate index) from DSN suffix
for name, schema in vsam_schemas.items():
    dsn = schema["dsn"].upper()
    if "AIX" in dsn or "PATH" in dsn:
        schema["vsam_type"] = "AIX"
    elif "ESDS" in dsn:
        schema["vsam_type"] = "ESDS"
    elif "RRDS" in dsn:
        schema["vsam_type"] = "RRDS"
    elif "KSDS" in dsn:
        schema["vsam_type"] = "KSDS"

# Source 2: COBOL FD entries
# Find which FD corresponds to each VSAM file
FD_PATTERN     = re.compile(r'FD\s+([A-Z0-9-]+)', re.IGNORECASE)
COPY_PATTERN   = re.compile(r'COPY\s+([A-Z0-9]+)', re.IGNORECASE)
RECORD_PATTERN = re.compile(r'RECORD(?:\s+CONTAINS)?\s+(\d+)\s+(?:TO\s+(\d+)\s+)?(?:CHARACTERS|BYTES)?', re.IGNORECASE)
KEY_PATTERN    = re.compile(r'(?:RECORD\s+KEY|KEY\s+IS)\s+([A-Z0-9-]+)', re.IGNORECASE)

# Map FD names to VSAM file names (from CSD)
# In COBOL: SELECT ACCTFILE ASSIGN TO ACCTDAT
SELECT_PATTERN = re.compile(
    r'SELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+TO\s+([A-Z0-9-]+)',
    re.IGNORECASE
)

for cbl_file in sorted((CORPUS_DIR / "app" / "cbl").glob("*.cbl")):
    content = cbl_file.read_text(encoding="utf-8", errors="replace")

    # Build SELECT->ASSIGN mapping
    select_map = {}  # FD name -> VSAM logical name
    for m in SELECT_PATTERN.finditer(content):
        fd_name   = m.group(1).upper()
        vsam_name = m.group(2).upper()
        select_map[fd_name] = vsam_name

    # Extract FD details
    lines = content.splitlines()
    in_fd = None
    for line in lines:
        fd_m = FD_PATTERN.match(line.strip())
        if fd_m:
            in_fd = fd_m.group(1).upper()
            continue

        if in_fd:
            # Record length
            rec_m = RECORD_PATTERN.search(line)
            if rec_m:
                vsam_name = select_map.get(in_fd, in_fd)
                if vsam_name in vsam_schemas:
                    vsam_schemas[vsam_name]["record_length"] = int(rec_m.group(1))

            # Key field
            key_m = KEY_PATTERN.search(line)
            if key_m:
                vsam_name = select_map.get(in_fd, in_fd)
                if vsam_name in vsam_schemas:
                    vsam_schemas[vsam_name]["key_field"] = key_m.group(1).upper()

            # Copybook for record layout
            copy_m = COPY_PATTERN.search(line)
            if copy_m:
                vsam_name = select_map.get(in_fd, in_fd)
                if vsam_name in vsam_schemas:
                    vsam_schemas[vsam_name]["record_copybook"] = copy_m.group(1).upper()

            # Track which programs use this file
            vsam_name = select_map.get(in_fd, in_fd)
            if vsam_name in vsam_schemas:
                prog = cbl_file.stem.upper()
                if prog not in vsam_schemas[vsam_name]["programs_using"]:
                    vsam_schemas[vsam_name]["programs_using"].append(prog)

            if line.strip().startswith("01 ") or line.strip().startswith("FD "):
                in_fd = None

# Source 3: AIX relationships
for name, schema in vsam_schemas.items():
    if schema["vsam_type"] == "AIX":
        # Find the base file this AIX is for
        base_dsn = schema["dsn"].replace(".AIX.PATH","").replace(".AIX","")
        for base_name, base_schema in vsam_schemas.items():
            if base_schema["dsn"] == base_dsn:
                base_schema["alternate_indexes"].append(name)
                break

# Save artifact
artifact = {
    "layer":       "L6",
    "vsam_count":  len(vsam_schemas),
    "schemas":     list(vsam_schemas.values()),
}

output_path = OUT_DIR / "artifacts" / "layer6" / "vsam_schemas.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(artifact, f, indent=2)

print(f"VSAM schemas: {len(vsam_schemas)}")
for name, s in vsam_schemas.items():
    print(f"\n  {name:<12} ({s['vsam_type']})")
    print(f"    DSN:      {s['dsn']}")
    print(f"    Records:  {s['record_length']} bytes")
    print(f"    Copybook: {s['record_copybook']}")
    print(f"    Key:      {s.get('key_field','')}")
    print(f"    AIX:      {s['alternate_indexes']}")
    print(f"    Programs: {s['programs_using'][:3]}")
print(f"\nSaved: {output_path}")
