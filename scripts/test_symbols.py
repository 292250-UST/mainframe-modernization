import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.layers.l2_symbols.symbol_table import SymbolTableBuilder, normalize_pic
from src.parsers.proleap_wrapper import parse_cobol_file
from src.preprocess.copybook_processor import CopybookProcessor

# Test normalize_pic
print("PIC S9(9)V99 COMP-3:", normalize_pic("S9(9)V99", "COMP-3"))
print("PIC X(08):", normalize_pic("X(08)"))
print("PIC 9(11):", normalize_pic("9(11)"))
print()

# Build symbol table
processor = CopybookProcessor(copybook_dir=Path("corpus/app/cpy"))
preprocess = processor.process(Path("corpus/app/cbl/CBACT01C.cbl"))
parse_result = parse_cobol_file(
    Path("corpus/app/cbl/CBACT01C.cbl"),
    preprocessed_lines=preprocess.preprocessed_lines
)

builder = SymbolTableBuilder()
result = builder.build(parse_result, preprocess.provenance_map)
path = builder.save(result)

print(f"Symbols: {result['symbol_count']}")
print("First 3 symbols:")
for s in result["symbols"][:3]:
    print(f"  {s['name']:30} L{s['level']:02} {str(s['pic']):15} -> {s['canonical_type']}")
print("Saved to:", path)
