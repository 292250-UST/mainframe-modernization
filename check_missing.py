import json
with open('out/reports/parse_coverage.json') as f:
    data = json.load(f)

missing = set()
for gap in data['gaps']:
    if gap['gap_type'] == 'MISSING_COPYBOOK':
        missing.add(gap['missing'])

print(f'Total unique missing copybooks: {len(missing)}')
for m in sorted(missing):
    print(f'  {m}')
