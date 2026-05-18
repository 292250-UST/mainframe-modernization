"""
transaction_flow.py
===================
Builds CICS transaction flow graph from EXEC CICS statements.

Uses cics_statements.json (from exec_cics_extractor) and
call_graph.json (XCTL edges) to build the transaction navigation graph.

WHAT IT PRODUCES:
    For each XCTL/LINK/RETURN:
    - from_program -> to_program edge
    - transaction ID if known (from CSD catalog)
    - commarea size if specified
"""

import json
from pathlib import Path
from typing import Optional
import uuid as uuid_lib

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("layers.l4_system_graphs.transaction_flow")


def build_transaction_flow(output_dir: Optional[Path] = None) -> dict:
    """
    Build transaction flow graph from existing artifacts.

    Reads:
    - out/artifacts/layer3/cics_statements.json (EXEC CICS)
    - out/artifacts/layer4/call_graph.json (XCTL edges)
    - out/artifacts/layer6/csd_catalog.json (TransID->Program mapping)

    Returns:
        dict with transaction flow edges
    """
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer4")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load CSD catalog for TransID->Program mapping
    csd_path = OUT_DIR / "artifacts" / "layer6" / "csd_catalog.json"
    transid_map = {}  # program -> transid
    if csd_path.exists():
        csd = json.loads(csd_path.read_text())
        for t in csd.get("transactions", []):
            prog = t.get("program", "").upper()
            tid  = t.get("name", "").upper()
            if prog and tid:
                transid_map[prog] = tid
        logger.info(f"Loaded {len(transid_map)} transaction mappings from CSD")

    # Load CICS statements
    cics_path = OUT_DIR / "artifacts" / "layer3" / "cics_statements.json"
    cics_stmts = []
    if cics_path.exists():
        cics_data  = json.loads(cics_path.read_text())
        cics_stmts = cics_data.get("statements", [])

    # Load call graph XCTL edges
    cg_path = OUT_DIR / "artifacts" / "layer4" / "call_graph.json"
    xctl_edges = []
    if cg_path.exists():
        cg_data    = json.loads(cg_path.read_text())
        xctl_edges = [e for e in cg_data.get("edges", [])
                      if e["call_type"] == "CICS_XCTL"]

    # Build flow edges
    flow_edges = []

    # From XCTL edges
    for edge in xctl_edges:
        caller = edge["caller"]
        callee = edge["callee"]
        edge_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
        flow_edges.append({
            "id":               edge_id,
            "from_program":     caller,
            "to_program":       callee,
            "edge_type":        "XCTL",
            "from_transid":     transid_map.get(caller, ""),
            "to_transid":       transid_map.get(callee, ""),
            "commarea_size":    None,
            "source_file":      edge["source_file"],
            "line":             edge["line"],
            "paragraph":        edge["paragraph"],
        })

    # From RETURN statements (program ends transaction)
    return_stmts = [s for s in cics_stmts if s["verb"] == "RETURN"]
    for stmt in return_stmts:
        prog    = stmt["source_file"].replace(".cbl", "").upper()
        transid = stmt["params"].get("TRANSID", "")
        edge_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
        flow_edges.append({
            "id":            edge_id,
            "from_program":  prog,
            "to_program":    "",
            "edge_type":     "RETURN",
            "from_transid":  transid_map.get(prog, ""),
            "to_transid":    transid,
            "commarea_size": None,
            "source_file":   stmt["source_file"],
            "line":          stmt["line"],
            "paragraph":     stmt["paragraph"],
        })

    # Summary
    summary = {
        "total_edges":  len(flow_edges),
        "xctl_edges":   sum(1 for e in flow_edges if e["edge_type"] == "XCTL"),
        "return_edges": sum(1 for e in flow_edges if e["edge_type"] == "RETURN"),
        "programs_in_flow": len(set(
            e["from_program"] for e in flow_edges if e["from_program"]
        )),
    }

    artifact = {
        "layer":    "L4",
        "summary":  summary,
        "edges":    flow_edges,
    }

    output_path = output_dir / "transaction_flow.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(
        f"Transaction flow: {len(flow_edges)} edges "
        f"({summary['xctl_edges']} XCTL, {summary['return_edges']} RETURN)"
    )
    return artifact


if __name__ == "__main__":
    result = build_transaction_flow()
    print(json.dumps(result["summary"], indent=2))
    print("\nSample XCTL edges:")
    for e in result["edges"][:5]:
        if e["edge_type"] == "XCTL":
            print(f"  {e['from_program']:<15} -XCTL-> {e['to_program']}")
