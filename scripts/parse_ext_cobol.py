import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR, COPYBOOK_DIR
from src.parsers.proleap_wrapper import parse_cobol_file
from src.preprocess.copybook_processor import CopybookProcessor
from src.layers.l1_ast.ast_transformer import ASTTransformer
from src.layers.l2_symbols.symbol_table import SymbolTableBuilder
from src.layers.l2_symbols.paragraph_inventory import ParagraphInventoryBuilder
import re

EXT_CBL = Path("corpus/app/app-authorization-ims-db2-mq/cbl")
EXT_CPY = Path("corpus/app/app-authorization-ims-db2-mq/cpy")

# Copy extension copybooks to main copybook dir so processor can find them
import shutil

def strip_exec_dli(lines: list[str]) -> list[str]:
    """
    Replace EXEC DLI ... END-EXEC blocks with COBOL comment lines.
    ProLeap rejects EXEC DLI syntax — stripping lets us parse the rest.
    DLI calls are extracted separately by exec_dli_extractor.py
    """
    result    = []
    in_dli    = False
    for line in lines:
        stripped = line.strip().upper()
        if re.search(r'EXEC\s+DLI', stripped):
            in_dli = True
            result.append(line[:6] + "* [EXEC DLI stripped for ProLeap]" + " " * 20)
            continue
        if in_dli:
            result.append(line[:6] + "* " + line[6:].rstrip())
            if 'END-EXEC' in stripped:
                in_dli = False
            continue
        result.append(line)
    return result


for cpy_file in list(EXT_CPY.glob("*.cpy")) + list(EXT_CPY.glob("*.CPY")):
    dest = COPYBOOK_DIR / cpy_file.name
    if not dest.exists():
        shutil.copy(cpy_file, dest)
        print(f"Copied: {cpy_file.name}")

OUT_L1  = OUT_DIR / "artifacts" / "layer1_ext"
OUT_L2  = OUT_DIR / "artifacts" / "layer2_ext"
OUT_L1.mkdir(parents=True, exist_ok=True)
OUT_L2.mkdir(parents=True, exist_ok=True)

# Use both main + extension copybook dirs
cpy_dirs = [COPYBOOK_DIR, EXT_CPY]

passed = 0
failed = 0

for cbl_file in sorted(list(EXT_CBL.glob("*.cbl")) + list(EXT_CBL.glob("*.CBL"))):
    try:
        # Preprocess
        processor = CopybookProcessor(copybook_dir=COPYBOOK_DIR)
        pre = processor.process(cbl_file)
        # Strip EXEC DLI for ProLeap (extracted separately by dli_extractor)
        pre.preprocessed_lines = strip_exec_dli(pre.preprocessed_lines)

        # Parse
        result = parse_cobol_file(
            cbl_file,
            preprocessed_lines=pre.preprocessed_lines,
            copybook_dir=COPYBOOK_DIR
        )
        result["source_file"] = cbl_file.name

        if result.get("status") == "ok":
            # AST
            trans = ASTTransformer()
            ast   = trans.transform(result, pre.provenance_map)
            trans.save(ast, OUT_L1)

            # Symbols
            sym = SymbolTableBuilder()
            sym_result = sym.build(result, pre.provenance_map)
            sym.save(sym_result, OUT_L2)

            # Paragraphs
            para = ParagraphInventoryBuilder()
            para_result = para.build(result, pre.provenance_map)
            para.save(para_result, OUT_L2)

            passed += 1
            print(f"PASS: {cbl_file.name} ({len(result['paragraphs'])} paragraphs)")
        else:
            failed += 1
            print(f"FAIL: {cbl_file.name} — {result.get('error','')[:60]}")

    except Exception as e:
        failed += 1
        print(f"ERROR: {cbl_file.name} — {str(e)[:60]}")

print(f"\nExtension COBOL: {passed} passed, {failed} failed")
