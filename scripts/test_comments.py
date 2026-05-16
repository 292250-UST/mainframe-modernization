import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.proleap_wrapper import parse_cobol_file

result = parse_cobol_file(Path("corpus/app/cbl/CBACT01C.cbl"))
print("Status:", result["status"])
print("JSON size (bytes):", len(str(result)))

# Extract only comment tokens
comments = [
    t for t in result.get("token_stream", [])
    if t["hidden"] and t["text"].strip().startswith("*")
]
print(f"Comment tokens: {len(comments)}")
print("\nFirst 5 comments:")
for c in comments[:5]:
    print(f"  line={c['line']:4}: {c['text'].strip()[:70]}")
