from src.parsers.proleap_wrapper import parse_cobol_file
from pathlib import Path
result = parse_cobol_file(Path('corpus/app/cbl/COACTUPC.cbl'))
print('Error:')
# Print first 3 lines of error only
lines = result.get('error', 'none').split('\n')
for line in lines[:3]:
    print(line)
