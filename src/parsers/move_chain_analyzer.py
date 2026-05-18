"""
move_chain_analyzer.py
======================
Analyzes MOVE statement chains to build data lineage graph (Layer 5).

WHY THIS EXISTS:
    Data lineage tracks how values flow through a program.
    MOVE A TO B means B's value comes from A.
    Chaining: MOVE A TO B, then MOVE B TO C means C traces back to A.

WHAT IT PRODUCES:
    For each program:
    - All MOVE statements (source -> target)
    - Resolved chains (transitive lineage)
    - Variables that flow into output files or screens

DOWNSTREAM CONSUMERS:
    - def_use table (data flow edges)
    - business_rules extractor (predicate variable origins)
    - LLM spec generator (explains where values come from)
"""

import re
import json
from pathlib import Path
from typing import Optional
from collections import defaultdict

from src.utils.logger import get_logger, PipelineEventLog

import sys
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import CORPUS_DIR, OUT_DIR

logger = get_logger("parsers.move_chain_analyzer")

# MOVE statement pattern
# Handles: MOVE x TO y, MOVE x TO y z (multiple targets)
# Handles: MOVE CORRESPONDING x TO y
MOVE_PATTERN = re.compile(
    r'MOVE\s+(?:CORRESPONDING\s+)?(.+?)\s+TO\s+(.+?)(?=\s+MOVE|\s+PERFORM|\s+IF|'
    r'\s+EVALUATE|\s+READ|\s+WRITE|\s+EXEC|\s+STOP|\s+GO\s+TO|\.|$)',
    re.IGNORECASE
)

# Literal value pattern (numbers, strings, figurative constants)
LITERAL_PATTERN = re.compile(
    r'^([0-9]+|\'[^\']*\'|"[^"]*"|ZEROS?|SPACES?|HIGH-VALUES?|LOW-VALUES?|'
    r'ALL\s+\'[^\']*\'|TRUE|FALSE)$',
    re.IGNORECASE
)

# Paragraph pattern for context tracking
PARA_PATTERN = re.compile(
    r'^[ ]{6,7}([A-Z0-9][A-Z0-9-]{1,29})\s*\.\s*$',
    re.IGNORECASE
)


def _is_literal(value: str) -> bool:
    """Return True if value is a literal (not a variable name)."""
    return bool(LITERAL_PATTERN.match(value.strip()))


def _clean_name(name: str) -> str:
    """Clean variable/field name — remove qualifiers and subscripts."""
    name = name.strip()
    # Remove OF/IN qualifiers: WS-NAME OF WS-RECORD -> WS-NAME
    name = re.sub(r'\s+(OF|IN)\s+\S+', '', name, flags=re.IGNORECASE)
    # Remove subscripts: TABLE(1) -> TABLE
    name = re.sub(r'\([^)]*\)', '', name)
    return name.strip().upper()


def extract_moves_from_file(cbl_file: Path) -> list[dict]:
    """
    Extract all MOVE statements from one COBOL file.

    Args:
        cbl_file: Path to .cbl source file

    Returns:
        List of move records {source, targets, line, paragraph}
    """
    content = cbl_file.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()
    moves   = []

    current_para = "UNKNOWN"

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track current paragraph
        para_m = PARA_PATTERN.match(line)
        if para_m:
            current_para = para_m.group(1).upper()
            continue

        # Skip comments
        if len(line) > 6 and line[6] in ('*', '/'):
            continue

        # Find MOVE statements
        for m in MOVE_PATTERN.finditer(line):
            source_raw  = m.group(1).strip()
            targets_raw = m.group(2).strip()

            source = _clean_name(source_raw)
            # Targets can be multiple: MOVE X TO A B C
            targets = [_clean_name(t) for t in targets_raw.split()
                       if t.upper() not in ('TO',) and t.strip()]

            if not source or not targets:
                continue

            moves.append({
                "source":      source,
                "source_raw":  source_raw,
                "targets":     targets,
                "is_literal":  _is_literal(source),
                "line":        i + 1,
                "paragraph":   current_para,
                "source_file": cbl_file.name,
            })

    return moves


def build_lineage_graph(moves: list[dict]) -> dict:
    """
    Build data lineage graph from MOVE statements.

    Creates a directed graph where edges mean:
    "target variable's value came from source variable"

    Also resolves transitive chains:
    MOVE A TO B, MOVE B TO C -> C ultimately comes from A

    Args:
        moves: List of move records from extract_moves_from_file()

    Returns:
        dict with edges, chains, and variable stats
    """
    # Build direct edges: target -> [sources]
    edges      = defaultdict(list)  # target -> list of sources
    rev_edges  = defaultdict(list)  # source -> list of targets

    for move in moves:
        if move["is_literal"]:
            continue  # Skip literal assignments for lineage

        src = move["source"]
        for tgt in move["targets"]:
            if src != tgt:  # Skip MOVE X TO X (no-op)
                edges[tgt].append({
                    "source":    src,
                    "line":      move["line"],
                    "paragraph": move["paragraph"],
                })
                rev_edges[src].append(tgt)

    # Resolve transitive chains (up to depth 5)
    def trace_origins(var: str, depth: int = 0) -> list[str]:
        if depth > 5 or var not in edges:
            return [var]
        origins = []
        for edge in edges[var]:
            origins.extend(trace_origins(edge["source"], depth + 1))
        return list(set(origins)) if origins else [var]

    # Build chain summary for key output variables
    # (variables that appear to flow to files or screens)
    output_indicators = {"OUT-", "WS-OUT", "SEND", "WRITE", "MOVE-TO-SCREEN"}
    chains = {}
    for var in list(edges.keys())[:50]:  # limit to first 50 for performance
        if any(var.startswith(ind) for ind in output_indicators):
            origins = trace_origins(var)
            if origins != [var]:
                chains[var] = origins

    return {
        "direct_edges":  [
            {
                "target":    tgt,
                "sources":   srcs,
            }
            for tgt, srcs in edges.items()
        ],
        "output_chains": chains,
        "variable_stats": {
            "total_targets":  len(edges),
            "total_sources":  len(set(
                e["source"] for srcs in edges.values() for e in srcs
            )),
        }
    }


def run(corpus_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None) -> dict:
    """
    Run move chain analysis on all COBOL files.

    Returns:
        dict with per-program lineage graphs
    """
    corpus_dir = corpus_dir or (CORPUS_DIR / "app" / "cbl")
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer5")
    output_dir.mkdir(parents=True, exist_ok=True)

    event_log = PipelineEventLog("move_chain_analyzer")
    all_results = []
    total_moves = 0

    cbl_files = sorted(corpus_dir.glob("*.cbl"))
    logger.info(f"Analyzing MOVE chains in {len(cbl_files)} files")

    for cbl_file in cbl_files:
        moves = extract_moves_from_file(cbl_file)
        if not moves:
            continue

        graph = build_lineage_graph(moves)
        total_moves += len(moves)

        result = {
            "source_file":  cbl_file.name,
            "move_count":   len(moves),
            "literal_moves": sum(1 for m in moves if m["is_literal"]),
            "variable_moves": sum(1 for m in moves if not m["is_literal"]),
            "lineage":      graph,
            "moves":        moves,
        }
        all_results.append(result)

        event_log.log_success(
            cbl_file.name,
            details={
                "moves":    len(moves),
                "edges":    len(graph["direct_edges"]),
                "chains":   len(graph["output_chains"]),
            }
        )
        logger.debug(
            f"{cbl_file.name}: {len(moves)} moves, "
            f"{len(graph['direct_edges'])} edges"
        )

    event_log.save()

    artifact = {
        "layer":        "L5",
        "total_moves":  total_moves,
        "programs":     len(all_results),
        "results":      all_results,
    }

    output_path = output_dir / "move_chains.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(
        f"Move chain analysis complete: "
        f"{total_moves} MOVE statements across {len(all_results)} programs"
    )
    return artifact


if __name__ == "__main__":
    result = run()
    print(f"Total MOVE statements: {result['total_moves']}")
    print(f"Programs analyzed: {result['programs']}")
    # Show sample for CBACT01C
    for r in result["results"]:
        if r["source_file"] == "CBACT01C.cbl":
            print(f"\nCBACT01C: {r['move_count']} moves")
            print(f"  Literal moves: {r['literal_moves']}")
            print(f"  Variable moves: {r['variable_moves']}")
            print(f"  Lineage edges: {len(r['lineage']['direct_edges'])}")
            print(f"\n  Sample edges:")
            for edge in r["lineage"]["direct_edges"][:5]:
                srcs = [s["source"] for s in edge["sources"]]
                print(f"    {edge['target']:<30} <- {srcs}")
            break
