import json
with open('out/reports/parse_coverage.json') as f:
    data = json.load(f)
print('Failed files and errors:')
for gap in data['gaps']:
    if gap['gap_type'] == 'PARSE_FAILURE':
        print(f"  {gap['file']}: {gap['error'][:120]}")
