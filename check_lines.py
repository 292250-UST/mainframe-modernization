from src.preprocess.copybook_processor import CopybookProcessor
from pathlib import Path

processor = CopybookProcessor(copybook_dir=Path("corpus/app/cpy"))
result = processor.process(Path("corpus/app/cbl/COACTUPC.cbl"))

# Show lines 163-170
for i, line in enumerate(result.preprocessed_lines[162:170], 163):
    print(f"{i:4}: {repr(line)}")
