import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

content = Path("corpus/app/app-authorization-ims-db2-mq/cbl/COPAUA0C.cbl").read_text(encoding="utf-8", errors="replace")

print("=== EXEC DLI samples ===")
for m in re.finditer(r'EXEC\s+DLI.{0,150}', content, re.IGNORECASE|re.DOTALL):
    print(f"  {m.group()[:120].strip()}")
    print()

print("\n=== EXEC MQ samples ===")
for m in re.finditer(r'(MQPUT|MQGET|MQOPEN|MQCLOSE|MQCONN).{0,150}', content, re.IGNORECASE|re.DOTALL):
    print(f"  {m.group()[:120].strip()}")
    print()

print("\n=== EXEC SQL samples ===")
for m in re.finditer(r'EXEC\s+SQL.{0,150}', content, re.IGNORECASE|re.DOTALL):
    print(f"  {m.group()[:120].strip()}")
    print()
