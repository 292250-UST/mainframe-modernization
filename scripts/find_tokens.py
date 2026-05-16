import os
from pathlib import Path

# Search ProLeap source for token-related classes
src_dir = Path("third_party/proleap-cobol-parser/src/main/java")
for java_file in src_dir.rglob("*.java"):
    content = java_file.read_text(encoding="utf-8", errors="replace")
    if "tokenStream" in content or "CommonTokenStream" in content or "hidden" in content.lower():
        print(java_file.relative_to(src_dir))
