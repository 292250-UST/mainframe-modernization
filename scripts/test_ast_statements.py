import sys, json, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PROLEAP_JAR, WRAPPER_DIR, COPYBOOK_DIR, CORPUS_DIR

dep_dir = Path(str(PROLEAP_JAR)).parent / "dependency"
classpath = f"{PROLEAP_JAR};{dep_dir}\\*;{WRAPPER_DIR}"
cbl_file  = CORPUS_DIR / "app" / "cbl" / "CBACT01C.cbl"

result = subprocess.run(
    ["java", "-cp", classpath, "CobolParserWrapper",
     str(cbl_file), str(COPYBOOK_DIR)],
    capture_output=True, text=True, timeout=60
)

if result.returncode != 0:
    print("ERROR:", result.stderr[-500:])
    sys.exit(1)

# Filter out INFO/WARN log lines, keep only JSON lines
lines = result.stdout.strip().split('\n')
json_lines = [l for l in lines if l.strip().startswith('{') or l.strip().startswith('}') or (l.strip() and not l.startswith('INFO') and not l.startswith('WARN') and not l.startswith('ERROR'))]

# Find the JSON block - look for last complete JSON object
raw = result.stdout
# Extract JSON - find first { and match to its closing }
start = raw.find('{')
depth = 0
end   = start
for i, c in enumerate(raw[start:], start):
    if c == '{': depth += 1
    elif c == '}':
        depth -= 1
        if depth == 0:
            end = i + 1
            break

data = json.loads(raw[start:end])

print(f"Program:    {data['program']}")
print(f"Paragraphs: {len(data['paragraphs'])}")
for para in data['paragraphs'][:3]:
    stmts = para.get('statements', [])
    print(f"\n  Paragraph: {para['name']}")
    print(f"  Statements: {len(stmts)}")
    for stmt in stmts[:3]:
        print(f"    {stmt['type']:<25} line={stmt['line']} raw={stmt['raw'][:50]}")
