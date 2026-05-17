import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.parsers.csd_parser import run

result = run()
print(f"FILES:        {len(result['files'])}")
print(f"PROGRAMS:     {len(result['programs'])}")
print(f"TRANSACTIONS: {len(result['transactions'])}")
print(f"MAPSETS:      {len(result['mapsets'])}")
print()
print("First 3 transactions (TransID -> Program):")
for t in result['transactions'][:3]:
    print(f"  {t['name']:<8} -> {t['program']}")
print()
print("First 3 files:")
for f in result['files'][:3]:
    print(f"  {f['name']:<12} DSN={f['dsname']}")
