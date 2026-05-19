"""
ast_transformer.py
==================
Transforms ProLeap parse output into clean typed AST nodes.

WHY THIS EXISTS:
    ProLeap returns a simple dict with program name and paragraph list.
    This module transforms that raw output into our typed AST hierarchy:
    - ProgramNode (one per program)
    - ParagraphNode (one per paragraph)
    
    It also cross-references the provenance map so every node
    knows exactly which source line it came from — including
    whether that line came from a copybook.

WHAT IT PRODUCES:
    For each parsed COBOL file:
    {
        "program_node": ProgramNode,
        "paragraph_nodes": [ParagraphNode, ...],
        "node_count": 17,
        "uuid": "875123c7..."
    }

    Saved as Layer 1 artifact:
    out/artifacts/layer1/CBACT01C_ast.json

DOWNSTREAM CONSUMERS:
    - symbol_table.py    (reads DataItemNode — added in L2)
    - cfg_builder.py     (reads ParagraphNode + StatementNode)
    - call_graph.py      (reads ProgramNode + StatementNode)
    - loader.py          (saves all nodes to DuckDB nodes table)
"""

import json
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger
from src.layers.l1_ast.ast_node import (
    ASTNode, ProgramNode, ParagraphNode,
    NodeKind, nodes_to_json
)
from src.preprocess.provenance_tracker import ProvenanceMap

import sys
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("layers.l1_ast.ast_transformer")

# Output directory for Layer 1 AST artifacts
LAYER1_DIR = OUT_DIR / "artifacts" / "layer1"


class ASTTransformer:
    """
    Transforms ProLeap parse output into clean typed AST nodes.

    Takes the raw dict from proleap_wrapper.parse_cobol_file() and
    the ProvenanceMap from copybook_processor, and produces a clean
    typed AST with stable UUIDs and source ranges.

    Usage:
        transformer = ASTTransformer()
        result = transformer.transform(parse_result, provenance_map)
        transformer.save(result, output_dir)
    """

    def __init__(self):
        self.logger = get_logger("layers.l1_ast.ast_transformer")

    def transform(
        self,
        parse_result: dict,
        provenance_map: Optional[ProvenanceMap] = None
    ) -> dict:
        """
        Transform ProLeap parse output into typed AST nodes.

        Args:
            parse_result (dict):        Output from proleap_wrapper.
                                        Must have: program, status, paragraphs, source_file
            provenance_map (ProvenanceMap): Line-level provenance tracking.
                                            Used to set copybook origins on nodes.

        Returns:
            dict with keys:
                program_node (ProgramNode):       Root program node
                paragraph_nodes (list):           List of ParagraphNode
                all_nodes (list):                 All nodes combined
                node_count (int):                 Total node count
                source_file (str):                Original .cbl filename
        """
        source_file   = parse_result.get("source_file", "UNKNOWN.cbl")
        program_name  = parse_result.get("program", source_file.replace(".cbl","").replace(".CBL",""))
        paragraphs    = parse_result.get("paragraphs", [])
        para_stmts    = parse_result.get("paragraph_statements", [])
        # Build lookup: para_name -> statements[]
        stmt_lookup   = {p["name"]: p.get("statements", []) for p in para_stmts} if para_stmts else {}
        total_lines   = provenance_map.summary()["total_lines"] if provenance_map else 0
        copybooks     = provenance_map.get_copybooks_used() if provenance_map else []

        self.logger.info(
            f"Transforming AST: {source_file} "
            f"({len(paragraphs)} paragraphs, {total_lines} lines)"
        )

        # -------------------------------------------------------------------
        # Step 1: Create ProgramNode (root of AST)
        # -------------------------------------------------------------------
        program_node = ProgramNode.create(
            program_name=program_name,
            source_file=source_file,
            total_lines=total_lines,
            copybooks=copybooks
        )

        # -------------------------------------------------------------------
        # Step 2: Create ParagraphNode for each paragraph
        # ProLeap gives us paragraph names but not line numbers.
        # We use the provenance map to find approximate line numbers.
        # If no provenance map, we assign sequential placeholder lines.
        # -------------------------------------------------------------------
        paragraph_nodes = []
        for i, para_name in enumerate(paragraphs):
            # Try to find the paragraph line in provenance map
            start_line = self._find_paragraph_line(
                para_name, provenance_map, source_file, i
            )
            end_line = start_line  # Will be refined in CFG builder (Day 4)

            para_node = ParagraphNode.create(
                name=para_name,
                statements=stmt_lookup.get(para_name, []),
                source_file=source_file,
                start_line=start_line,
                end_line=end_line,
                parent_uuid=program_node.uuid
            )
            program_node.add_child(para_node)
            paragraph_nodes.append(para_node)

        # Update paragraph count in program node payload
        program_node.payload["paragraph_count"] = len(paragraph_nodes)

        # -------------------------------------------------------------------
        # Step 3: Combine all nodes
        # -------------------------------------------------------------------
        all_nodes = [program_node] + paragraph_nodes

        self.logger.info(
            f"AST built: {source_file} — "
            f"{len(all_nodes)} nodes "
            f"({len(paragraph_nodes)} paragraphs)"
        )

        return {
            "program_node":     program_node,
            "paragraph_nodes":  paragraph_nodes,
            "all_nodes":        all_nodes,
            "node_count":       len(all_nodes),
            "source_file":      source_file,
        }

    def _find_paragraph_line(
        self,
        para_name: str,
        provenance_map: Optional[ProvenanceMap],
        source_file: str,
        index: int
    ) -> int:
        """
        Find the line number of a paragraph in the provenance map.

        Searches for the paragraph name in the preprocessed source lines.
        COBOL paragraph names appear at the start of a line in Area A
        (columns 8-11) followed by a period.

        Args:
            para_name (str):            Paragraph name to search for
            provenance_map:             Provenance map to search in
            source_file (str):          Source filename (for fallback UUID)
            index (int):                Paragraph index (for fallback line)

        Returns:
            int: Line number (1-indexed), or placeholder if not found
        """
        if provenance_map is None:
            # No provenance map — use index-based placeholder
            return (index + 1) * 10

        # Search provenance lines for paragraph name
        # COBOL paragraph: name starts at column 8, followed by period or space
        para_upper = para_name.upper()
        for pline in provenance_map.lines:
            content = pline.content.upper()
            # Check if line starts with paragraph name in Area A (col 8+)
            stripped = content.strip()
            if (stripped.startswith(para_upper) and
                len(stripped) > len(para_upper) and
                stripped[len(para_upper)] in (' ', '.')):
                return pline.origin_line_num

        # Not found — use placeholder
        self.logger.debug(
            f"Paragraph '{para_name}' not found in provenance map "
            f"for {source_file} — using placeholder line"
        )
        return (index + 1) * 10

    def save(
        self,
        transform_result: dict,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save the AST as a JSON artifact to the Layer 1 output directory.

        Output filename: {program_name}_ast.json
        Output format:
        {
            "source_file": "CBACT01C.cbl",
            "program_node": { ... },
            "paragraph_nodes": [ { ... }, ... ],
            "node_count": 17
        }

        Args:
            transform_result (dict):    Output from transform()
            output_dir (Path):          Where to save. Default: out/artifacts/layer1/

        Returns:
            Path: Path to the saved artifact file.
        """
        output_dir = output_dir or LAYER1_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        program_node = transform_result["program_node"]
        source_file  = transform_result["source_file"]
        program_name = program_node.payload["program_name"]

        artifact = {
            "layer":        "L1",
            "source_file":  source_file,
            "node_count":   transform_result["node_count"],
            "program_node": program_node.to_dict(),
            "paragraph_nodes": [
                n.to_dict() for n in transform_result["paragraph_nodes"]
            ],
        }

        output_path = output_dir / f"{program_name}_ast.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)

        self.logger.info(
            f"AST artifact saved: {output_path.name} "
            f"({transform_result['node_count']} nodes)"
        )
        return output_path
