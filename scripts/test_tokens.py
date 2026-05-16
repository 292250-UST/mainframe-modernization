import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.proleap_wrapper import parse_cobol_file

result = parse_cobol_file(Path("corpus/app/cbl/CBACT01C.cbl"))
print("Status:", result["status"])
print("Paragraphs:", len(result["paragraphs"]))
print("Data items:", len(result.get("data_items", [])))
print("Tokens:", len(result.get("token_stream", [])))

# Show first 5 tokens
print("\nFirst 5 tokens:")
for tok in result.get("token_stream", [])[:5]:
    print(f"  line={tok['line']:4} col={tok['col']:3} hidden={tok['hidden']} text={repr(tok['text'][:40])}")

# Show first 5 hidden tokens (comments)
print("\nFirst 5 hidden tokens (comments/col7):")
hidden = [t for t in result.get("token_stream", []) if t["hidden"]]
for tok in hidden[:5]:
    print(f"  line={tok['line']:4} col={tok['col']:3} text={repr(tok['text'][:60])}")
