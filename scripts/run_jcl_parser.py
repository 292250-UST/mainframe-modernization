import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.jcl_parser import JCLParser

parser = JCLParser()
results = parser.parse_all(Path("corpus/app/jcl"))
output = parser.save_results(results)

print(f"\nSummary:")
print(f"  Total jobs: {len(results)}")
print(f"  Passed: {sum(1 for r in results if r['status']=='ok')}")
print(f"  Failed: {sum(1 for r in results if r['status']!='ok')}")
print(f"  Total steps: {sum(r['step_count'] for r in results)}")
print(f"  Total datasets: {sum(len(s['datasets']) for r in results for s in r['steps'])}")
print(f"  Saved to: {output}")
