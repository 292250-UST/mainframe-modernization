import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.jcl_parser import JCLParser
from src.layers.l4_system_graphs.jcl_graph import build_jcl_graph, save_jcl_graph

# Parse all JCL
parser = JCLParser()
results = parser.parse_all(Path("corpus/app/jcl"))

# Build graph
graph = build_jcl_graph(results)
save_jcl_graph(graph)

print(f"Job records: {len(graph['jobs'])}")
print(f"Dependencies: {len(graph['dependencies'])}")

# Show demo chain dependencies
print("\nBatch chain dependencies (POSTTRAN/INTCALC/CREASTMT):")
demo_jobs = {"POSTTRAN", "INTCALC", "CREASTMT"}
for dep in graph["dependencies"]:
    if dep["producer_job"] in demo_jobs or dep["consumer_job"] in demo_jobs:
        print(f"  {dep['producer_job']} → {dep['consumer_job']}")
        print(f"    via: {dep['dataset_name']}")
