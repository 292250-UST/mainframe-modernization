import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

ext_dir = Path("corpus/app/app-authorization-ims-db2-mq/cbl")
content = (ext_dir / "CBPAUP0C.cbl").read_text(encoding="utf-8", errors="replace")

print("=== EXEC DLI samples ===")
for m in re.finditer(r'EXEC\s+DLI.{0,100}', content, re.IGNORECASE):
    print(f"  {m.group()[:80]}")

print("\n=== EXEC MQ samples ===")
for m in re.finditer(r'(EXEC\s+MQ|MQPUT|MQGET).{0,100}', content, re.IGNORECASE):
    print(f"  {m.group()[:80]}")

print("\n=== EXEC SQL samples ===")
for m in re.finditer(r'EXEC\s+SQL.{0,100}', content, re.IGNORECASE):
    print(f"  {m.group()[:80]}")
