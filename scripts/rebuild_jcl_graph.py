import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR
from src.parsers.jcl_parser import JCLParser
from src.layers.l4_system_graphs.jcl_graph import build_jcl_graph, save_jcl_graph

parser  = JCLParser()
results = parser.parse_all(Path("corpus/app/jcl"))
graph   = build_jcl_graph(results)
save_jcl_graph(graph)
print("known_chains:", graph.get("known_chains", []))
print("dependencies:", len(graph.get("dependencies", [])))
