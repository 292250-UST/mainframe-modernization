from pathlib import Path
content = Path("corpus/app/csd/CARDDEMO.CSD").read_text(encoding="utf-8", errors="replace")
print(content[:2000])
