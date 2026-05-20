import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

content = Path("corpus/app/app-authorization-ims-db2-mq/ims/DBPAUTP0.dbd").read_text(encoding="utf-8", errors="replace")
print(content[:1000])
