from src.preprocess.copybook_processor import CopybookProcessor
from src.parsers.proleap_wrapper import parse_cobol_file
from pathlib import Path
import tempfile, os

processor = CopybookProcessor(copybook_dir=Path("corpus/app/cpy"))
result = processor.process(Path("corpus/app/cbl/COSGN00C.cbl"))
print(f"Preprocessed: {len(result.preprocessed_lines)} lines, missing: {result.copybooks_missing}")

with tempfile.NamedTemporaryFile(mode="w", suffix=".cbl", delete=False, encoding="utf-8") as tmp:
    tmp.write("\n".join(result.preprocessed_lines))
    tmp_path = tmp.name

parse_result = parse_cobol_file(Path(tmp_path))
print(f"Status: {parse_result['status']}")
if parse_result["status"] == "ok":
    print(f"Paragraphs: {len(parse_result['paragraphs'])}")
    print(parse_result["paragraphs"])
else:
    lines = parse_result["error"].split("\n")
    for line in lines[:3]:
        print(line)
os.unlink(tmp_path)
