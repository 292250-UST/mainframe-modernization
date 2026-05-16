from src.parsers.proleap_wrapper import parse_cobol_file
from src.preprocess.copybook_processor import CopybookProcessor
from pathlib import Path
import tempfile, os

# Step 1 - preprocess
processor = CopybookProcessor(copybook_dir=Path('corpus/app/cpy'))
result = processor.process(Path('corpus/app/cbl/COACTUPC.cbl'))
print(f'Preprocessed: {len(result.preprocessed_lines)} lines, missing: {result.copybooks_missing}')

# Step 2 - write preprocessed source to temp file
with tempfile.NamedTemporaryFile(mode='w', suffix='.cbl', delete=False, encoding='utf-8') as tmp:
    tmp.write('\n'.join(result.preprocessed_lines))
    tmp_path = tmp.name

print(f'Temp file: {tmp_path}')

# Step 3 - pass temp file to ProLeap
parse_result = parse_cobol_file(Path(tmp_path))
print(f'Parse status: {parse_result["status"]}')
if parse_result['status'] == 'ok':
    print(f'Paragraphs: {len(parse_result["paragraphs"])}')
else:
    print(f'Error: {parse_result["error"][:200]}')

# Cleanup
os.unlink(tmp_path)
