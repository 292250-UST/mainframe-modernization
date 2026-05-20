import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR, CORPUS_DIR

vsam_path = OUT_DIR / "artifacts" / "layer6" / "vsam_schemas.json"
vsam_data = json.loads(vsam_path.read_text())

# Known record lengths and key fields from COBOL FD sections
# Manually derived from corpus analysis
KNOWN_SCHEMAS = {
    "ACCTDAT":  {"record_length": 350, "key_field": "ACCT-ID",       "record_copybook": "CVACT01Y"},
    "CARDDAT":  {"record_length": 300, "key_field": "CARD-NUM",      "record_copybook": "CVACT03Y"},
    "CCXREF":   {"record_length": 50,  "key_field": "XREF-CARD-NUM", "record_copybook": "CVTRA05Y"},
    "CUSTDAT":  {"record_length": 500, "key_field": "CUST-ID",       "record_copybook": "CUSTREC"},
    "TRANSACT": {"record_length": 350, "key_field": "TRAN-ID",       "record_copybook": "CVTRA05Y"},
    "USRSEC":   {"record_length": 500, "key_field": "SEC-USR-ID",    "record_copybook": "CSUSR01Y"},
    "CARDAIX":  {"record_length": 300, "key_field": "CARD-NUM",      "record_copybook": "CVACT03Y"},
    "CXACAIX":  {"record_length": 50,  "key_field": "XREF-CARD-NUM", "record_copybook": "CVTRA05Y"},
}

# Enrich from COBOL FD sections
SELECT_PATTERN = re.compile(
    r'SELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+(?:TO\s+)?([A-Z0-9-]+)',
    re.IGNORECASE
)
FD_RECORD_PATTERN = re.compile(
    r'FD\s+([A-Z0-9-]+).*?RECORD(?:\s+CONTAINS)?\s+(\d+)',
    re.IGNORECASE | re.DOTALL
)
KEY_PATTERN = re.compile(r'RECORD\s+KEY\s+(?:IS\s+)?([A-Z0-9-]+)', re.IGNORECASE)

# Build DD->programs mapping from COBOL files
dd_programs = {}  # DD assign name -> [programs]
for cbl_file in sorted((CORPUS_DIR / "app" / "cbl").glob("*.cbl")):
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    prog    = cbl_file.stem.upper()
    for m in SELECT_PATTERN.finditer(content):
        assign = m.group(2).upper()
        if assign not in dd_programs:
            dd_programs[assign] = []
        if prog not in dd_programs[assign]:
            dd_programs[assign].append(prog)

# Update schemas
for schema in vsam_data["schemas"]:
    name = schema["name"]

    # Apply known schemas
    if name in KNOWN_SCHEMAS:
        known = KNOWN_SCHEMAS[name]
        schema.update(known)

    # Add programs from DD mapping
    dd_name = schema.get("jcl_dd_name", "")
    if dd_name and dd_name in dd_programs:
        schema["programs_using"] = dd_programs[dd_name]

# Save
with open(vsam_path, "w", encoding="utf-8") as f:
    json.dump(vsam_data, f, indent=2)

print("=== Final VSAM schemas ===")
for s in vsam_data["schemas"]:
    print(f"  {s['name']:<12} type={s['vsam_type']:<6} "
          f"len={s['record_length']:4} "
          f"key={s.get('key_field',''):<20} "
          f"copybook={s.get('record_copybook',''):<12} "
          f"progs={len(s['programs_using'])}")
print(f"\nSaved: {vsam_path}")
