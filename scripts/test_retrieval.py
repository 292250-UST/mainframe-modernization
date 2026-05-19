import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.llm.retrieval import assemble_program_slice, format_slice_for_llm

slice_data = assemble_program_slice("COTRN02C")
context = format_slice_for_llm(slice_data)
print(context[:3000])
