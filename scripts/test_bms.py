import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.parsers.bms_parser import BMSParser

parser = BMSParser()
results = parser.parse_all(Path("corpus/app/bms"))
parser.save(results)

print(f"Mapsets: {len(results)}")
print(f"Total maps: {sum(r['map_count'] for r in results)}")

# Show COTRN02 fields (demo target)
for r in results:
    if "COTRN02" in r["mapset_name"]:
        print(f"\nCOTRN02 fields:")
        for m in r["maps"]:
            named = [f for f in m["fields"] if f["is_named"]]
            print(f"  Map {m['name']}: {len(named)} named fields")
            for f in named[:5]:
                print(f"    {f['name']:<12} row={f['row']} col={f['col']} len={f['length']} input={f['input']}")
