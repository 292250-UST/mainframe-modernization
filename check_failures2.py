import json
with open('out/reports/parse_coverage.json') as f:
    data = json.load(f)
print('First failure full error:')
for gap in data['gaps']:
    if gap['gap_type'] == 'PARSE_FAILURE':
        print(f"File: {gap['file']}")
        print(f"Error: {gap['error']}")
        break
