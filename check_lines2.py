from src.preprocess.copybook_processor import CopybookProcessor
from pathlib import Path

processor = CopybookProcessor(copybook_dir=Path("corpus/app/cpy"))
result = processor.process(Path("corpus/app/cbl/COACTUPC.cbl"))

# Show lines around 5204
for i, line in enumerate(result.preprocessed_lines[5199:5210], 5200):
    print(f"{i:5}: {line}")
