import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR
from src.parsers.batch_parser import run_batch_parse
from src.parsers.jcl_parser import JCLParser
from src.parsers.bms_parser import BMSParser
from src.parsers.csd_parser import CSDParser
from src.layers.l4_system_graphs.jcl_graph import build_jcl_graph, save_jcl_graph

EXT_DIR = Path("corpus/app/app-authorization-ims-db2-mq")

# 1. COBOL
print("=== Parsing extension COBOL ===")
run_batch_parse(corpus_dir=EXT_DIR / "cbl")

# 2. JCL
print("\n=== Parsing extension JCL ===")
parser = JCLParser()
results = parser.parse_all(EXT_DIR / "jcl")
parser.save_results(results, OUT_DIR / "artifacts" / "jcl_ext")
graph = build_jcl_graph(results)
save_jcl_graph(graph, OUT_DIR / "artifacts" / "jcl_ext")
print(f"JCL: {len(results)} files, {sum(r['step_count'] for r in results)} steps")

# 3. BMS
print("\n=== Parsing extension BMS ===")
bms = BMSParser()
bms_results = bms.parse_all(EXT_DIR / "bms")
bms.save(bms_results, OUT_DIR / "artifacts" / "layer6_ext")
print(f"BMS: {len(bms_results)} mapsets")

# 4. CSD
print("\n=== Parsing extension CSD ===")
csd = CSDParser()
for f in list((EXT_DIR / "csd").glob("*.csd")) + list((EXT_DIR / "csd").glob("*.CSD")):
    result = csd.parse(f)
    csd.save(result, OUT_DIR / "artifacts" / "layer6_ext")
    print(f"CSD: {len(result['programs'])} programs, {len(result['transactions'])} transactions")
