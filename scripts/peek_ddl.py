import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Check all DDL files
ddl_dirs = [
    Path("corpus/app/app-authorization-ims-db2-mq/ddl"),
    Path("corpus/app/app-transaction-type-db2/ddl"),
]

for ddl_dir in ddl_dirs:
    print(f"\n=== {ddl_dir} ===")
    for f in sorted(ddl_dir.glob("*.ddl")) + sorted(ddl_dir.glob("*.DDL")):
        content = f.read_text(encoding="utf-8", errors="replace")
        print(f"\n{f.name}:")
        print(content[:500])
