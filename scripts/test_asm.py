import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.parsers.assembler_stub_recognizer import run

stubs = run()
print(f"Found {len(stubs)} stubs:")
for s in stubs:
    print(f"  {s['name']:<12} ({s['entry_type']}) -- {s['description']}")