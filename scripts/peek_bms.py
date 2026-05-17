from pathlib import Path
content = Path("corpus/app/bms/COSGN00.bms").read_text(encoding="utf-8", errors="replace")
print(content[:1500])
