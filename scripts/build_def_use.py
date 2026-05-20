import sys, json, re, duckdb, uuid as uuid_lib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR

LAYER1_DIR = OUT_DIR / "artifacts" / "layer1"
DB_PATH    = OUT_DIR / "graph" / "artifacts.duckdb"

# Variable name pattern - matches COBOL identifiers
VAR_PATTERN = re.compile(r'[A-Z][A-Z0-9-]{2,29}(?:-[A-Z0-9]+)*', re.IGNORECASE)

# Known non-variable keywords to filter out
KEYWORDS = {
    "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "IF", "ELSE", "THEN", "EVALUATE", "WHEN", "PERFORM", "UNTIL",
    "VARYING", "THROUGH", "THRU", "CALL", "USING", "GIVING", "INTO",
    "TO", "FROM", "BY", "INITIALIZE", "SET", "TRUE", "FALSE",
    "DISPLAY", "ACCEPT", "READ", "WRITE", "REWRITE", "DELETE",
    "OPEN", "CLOSE", "START", "STOP", "RUN", "EXIT", "CONTINUE",
    "NOT", "AND", "OR", "END-IF", "END-EVALUATE", "END-PERFORM",
    "END-READ", "END-WRITE", "END-CALL", "SPACES", "ZEROS", "ZEROES",
    "HIGH-VALUES", "LOW-VALUES", "ALL", "CORRESPONDING", "CORR",
    "STRING", "UNSTRING", "INSPECT", "SEARCH", "ALL", "LEADING",
    "SECTION", "DIVISION", "PROGRAM-ID", "WORKING-STORAGE",
}

def is_variable(name: str) -> bool:
    """Check if a token looks like a COBOL variable name."""
    name = name.upper()
    if name in KEYWORDS:
        return False
    if re.match(r'^[0-9]', name):  # starts with digit
        return False
    if len(name) < 3:
        return False
    return True

def extract_variables_from_raw(raw: str) -> list[str]:
    """Extract variable names from concatenated raw text."""
    # Find all potential variable names
    matches = VAR_PATTERN.findall(raw)
    return [m.upper() for m in matches if is_variable(m)]

def extract_def_use_from_ast(ast_file: Path) -> list[dict]:
    data    = json.loads(ast_file.read_text())
    program = ast_file.stem.replace("_ast", "").upper()
    results = []
    source_file = ast_file.stem.replace("_ast", "") + ".cbl"

    for para_node in data.get("paragraph_nodes", []):
        payload   = para_node.get("payload", {})
        para_name = payload.get("name", "")
        stmts     = payload.get("statements", [])

        for stmt in stmts:
            stmt_type = stmt.get("type", "").upper()
            raw       = stmt.get("raw", "")
            line      = stmt.get("line", 0)

            if not raw:
                continue

            variables = extract_variables_from_raw(raw)
            if not variables:
                continue

            # Determine operation based on statement type
            if stmt_type in {"MOVE", "COMPUTE", "ADD", "SUBTRACT",
                             "MULTIPLY", "DIVIDE", "INITIALIZE", "SET",
                             "STRING", "UNSTRING", "ACCEPT"}:
                # Last variable in statement tends to be the target (DEF)
                if variables:
                    results.append({
                        "program":    program,
                        "variable":   variables[-1],  # target is usually last
                        "operation":  "WRITE",
                        "stmt_type":  stmt_type,
                        "stmt_text":  raw[:100],
                        "paragraph":  para_name,
                        "line":       line,
                        "source_file": source_file,
                    })
                # First variable tends to be the source (USE)
                if len(variables) > 1:
                    results.append({
                        "program":    program,
                        "variable":   variables[0],  # source is usually first
                        "operation":  "READ",
                        "stmt_type":  stmt_type,
                        "stmt_text":  raw[:100],
                        "paragraph":  para_name,
                        "line":       line,
                        "source_file": source_file,
                    })

            elif stmt_type in {"IF", "EVALUATE", "PERFORM"}:
                # All variables in IF/EVALUATE are USEs
                for var in variables[:3]:  # limit to first 3
                    results.append({
                        "program":    program,
                        "variable":   var,
                        "operation":  "READ",
                        "stmt_type":  stmt_type,
                        "stmt_text":  raw[:100],
                        "paragraph":  para_name,
                        "line":       line,
                        "source_file": source_file,
                    })

            elif stmt_type in {"READ", "WRITE", "REWRITE", "DELETE"}:
                # File operations - first var is file name (USE)
                if variables:
                    results.append({
                        "program":    program,
                        "variable":   variables[0],
                        "operation":  "READ" if stmt_type == "READ" else "WRITE",
                        "stmt_type":  stmt_type,
                        "stmt_text":  raw[:100],
                        "paragraph":  para_name,
                        "line":       line,
                        "source_file": source_file,
                    })

    return results

# Run on all AST files
all_results = []
ast_files   = sorted(LAYER1_DIR.glob("*_ast.json"))
print(f"Processing {len(ast_files)} AST files...")

for ast_file in ast_files:
    results = extract_def_use_from_ast(ast_file)
    all_results.extend(results)

print(f"Total def-use entries: {len(all_results)}")
print(f"  WRITE (DEF): {sum(1 for r in all_results if r['operation']=='WRITE')}")
print(f"  READ  (USE): {sum(1 for r in all_results if r['operation']=='READ')}")

# Sample
print("\nSample COTRN02C def-use:")
for r in all_results:
    if r["program"] == "COTRN02C" and r["operation"] == "WRITE":
        print(f"  DEF {r['variable']:<30} in {r['paragraph']} line {r['line']}")
        break
for r in all_results:
    if r["program"] == "COTRN02C" and r["operation"] == "READ":
        print(f"  USE {r['variable']:<30} in {r['paragraph']} line {r['line']}")
        break

# Clear existing and reload into DuckDB
conn = duckdb.connect(str(DB_PATH))
conn.execute("DELETE FROM def_use")

rows = []
for r in all_results:
    rows.append((
        str(uuid_lib.uuid4()).replace("-","")[:32],
        r["variable"],
        r["operation"],
        None,
        r["stmt_text"],
        r["source_file"],
        r["line"],
    ))

if rows:
    conn.executemany("""
        INSERT OR IGNORE INTO def_use
        (id, data_item_uuid, operation, stmt_uuid, stmt_text, source_file, line_num)
        VALUES (?,?,?,?,?,?,?)
    """, rows)
    print(f"\nLoaded {len(rows)} def-use entries into DuckDB")

# Save artifact
output_path = OUT_DIR / "artifacts" / "layer5" / "def_use.json"
artifact = {
    "layer":   "L5",
    "total":   len(all_results),
    "write":   sum(1 for r in all_results if r["operation"] == "WRITE"),
    "read":    sum(1 for r in all_results if r["operation"] == "READ"),
    "entries": all_results
}
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(artifact, f, indent=2)
print(f"Saved: {output_path}")
conn.close()
