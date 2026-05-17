"""
paragraph_inventory.py
======================
Builds the paragraph inventory for one COBOL program.

WHY THIS EXISTS:
    Layer 2 requires: paragraph/section inventory per program —
    name, range, statement count, complexity.

    We already have paragraph names from ProLeap. This module
    adds line ranges (from provenance map) and statement counts
    (from token stream analysis).

WHAT IT PRODUCES:
    paragraph_inventory.json per program:
    {
        "program": "CBACT01C",
        "paragraphs": [
            {
                "uuid": "...",
                "name": "1000-ACCTFILE-GET-NEXT",
                "start_line": 145,
                "end_line": 180,
                "statement_count": 12,
                "complexity": 1
            }
        ]
    }

DOWNSTREAM CONSUMERS:
    - cfg_builder.py    (Day 4 — needs paragraph line ranges)
    - dead_code_analyzer.py (Day 7 — finds never-PERFORM'd paragraphs)
    - complexity_analyzer.py (Day 7 — cyclomatic complexity)
"""

import json
import re
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger
from src.layers.l1_ast.ast_node import make_uuid, NodeKind
from src.preprocess.provenance_tracker import ProvenanceMap

import sys
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("layers.l2_symbols.paragraph_inventory")

LAYER2_DIR = OUT_DIR / "artifacts" / "layer2"

# COBOL statement keywords — used to count statements per paragraph
STATEMENT_KEYWORDS = {
    "MOVE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "PERFORM", "IF", "EVALUATE", "GO", "CALL", "READ", "WRITE",
    "REWRITE", "DELETE", "START", "OPEN", "CLOSE", "STOP",
    "INITIALIZE", "INSPECT", "STRING", "UNSTRING", "ACCEPT",
    "DISPLAY", "EXEC", "SET", "SEARCH"
}


class ParagraphInventoryBuilder:
    """
    Builds paragraph inventory for one COBOL program.

    Extracts:
    - Paragraph name
    - Start + end line numbers (from provenance map)
    - Statement count (from token analysis)
    - Cyclomatic complexity (base = 1, incremented per IF/EVALUATE/WHEN)
    """

    def __init__(self):
        self.logger = get_logger("layers.l2_symbols.paragraph_inventory")

    def build(
        self,
        parse_result: dict,
        provenance_map: Optional[ProvenanceMap] = None
    ) -> dict:
        """
        Build paragraph inventory from parse result.

        Args:
            parse_result (dict):    Output from proleap_wrapper
            provenance_map:         For line number lookup

        Returns:
            dict with program, paragraphs[], paragraph_count
        """
        source_file  = parse_result.get("source_file", "UNKNOWN.cbl")
        program_name = parse_result.get("program", source_file.replace(".cbl",""))
        paragraphs   = parse_result.get("paragraphs", [])

        self.logger.info(
            f"Building paragraph inventory: {source_file} "
            f"({len(paragraphs)} paragraphs)"
        )

        # Build line index from provenance map
        # Maps paragraph name -> start line
        para_lines = self._find_paragraph_lines(paragraphs, provenance_map, source_file)

        # Build inventory entries
        inventory = []
        for i, para_name in enumerate(paragraphs):
            start_line = para_lines.get(para_name, (i + 1) * 10)

            # Find end line (start of next paragraph - 1)
            if i + 1 < len(paragraphs):
                next_name = paragraphs[i + 1]
                end_line = para_lines.get(next_name, start_line + 10) - 1
            else:
                # Last paragraph ends at end of file
                end_line = (
                    provenance_map.summary()["total_lines"]
                    if provenance_map else start_line + 10
                )

            # Count statements in this paragraph's line range
            stmt_count, complexity = self._count_statements(
                start_line, end_line, provenance_map
            )

            # Generate UUID
            uuid = make_uuid(
                source_file, start_line, NodeKind.PARAGRAPH.value
            )

            inventory.append({
                "uuid":            uuid,
                "name":            para_name,
                "start_line":      start_line,
                "end_line":        end_line,
                "statement_count": stmt_count,
                "complexity":      complexity,
                "line_count":      max(0, end_line - start_line + 1),
            })

        self.logger.info(
            f"Paragraph inventory built: {source_file} — "
            f"{len(inventory)} paragraphs, "
            f"avg {sum(p['statement_count'] for p in inventory) // max(1,len(inventory))} stmts each"
        )

        return {
            "program":         program_name,
            "source_file":     source_file,
            "paragraphs":      inventory,
            "paragraph_count": len(inventory),
        }

    def _find_paragraph_lines(
        self,
        para_names: list[str],
        provenance_map: Optional[ProvenanceMap],
        source_file: str
    ) -> dict[str, int]:
        """
        Build a mapping of paragraph name -> start line number.

        Searches the provenance map for lines where a paragraph
        name appears at the start of Area A (columns 8-11).

        Args:
            para_names:     List of paragraph names from ProLeap
            provenance_map: Source line tracking
            source_file:    For logging

        Returns:
            dict: {para_name: start_line}
        """
        if provenance_map is None:
            return {name: (i + 1) * 10 for i, name in enumerate(para_names)}

        result = {}
        para_upper = {name.upper(): name for name in para_names}

        for pline in provenance_map.lines:
            content = pline.content.upper().strip()
            for upper_name, orig_name in para_upper.items():
                if orig_name in result:
                    continue
                # Paragraph definition: name followed by period or space
                if content.startswith(upper_name):
                    rest = content[len(upper_name):]
                    if rest and rest[0] in (' ', '.', '\t'):
                        result[orig_name] = pline.origin_line_num
                        break

        # Fill in any not found
        for i, name in enumerate(para_names):
            if name not in result:
                result[name] = (i + 1) * 10
                self.logger.debug(f"Paragraph '{name}' not found — using placeholder")

        return result

    def _count_statements(
        self,
        start_line: int,
        end_line: int,
        provenance_map: Optional[ProvenanceMap]
    ) -> tuple[int, int]:
        """
        Count COBOL statements and cyclomatic complexity in a line range.

        Scans the provenance map lines between start and end,
        looking for COBOL statement keywords.

        Complexity increments for: IF, EVALUATE, WHEN, PERFORM UNTIL/VARYING

        Args:
            start_line: First line of paragraph
            end_line:   Last line of paragraph
            provenance_map: Source lines

        Returns:
            tuple: (statement_count, cyclomatic_complexity)
        """
        if provenance_map is None:
            return 0, 1

        stmt_count = 0
        complexity = 1  # Base complexity

        for pline in provenance_map.lines:
            if pline.origin_line_num < start_line:
                continue
            if pline.origin_line_num > end_line:
                break

            content = pline.content.upper().strip()

            # Count statement keywords
            first_word = content.split()[0] if content.split() else ""
            if first_word in STATEMENT_KEYWORDS:
                stmt_count += 1

            # Increment complexity for branching constructs
            if re.search(r'\bIF\b', content):
                complexity += 1
            if re.search(r'\bEVALUATE\b', content):
                complexity += 1
            if re.search(r'\bWHEN\b', content):
                complexity += 1
            if re.search(r'\bPERFORM\s+(UNTIL|VARYING)\b', content):
                complexity += 1

        return stmt_count, complexity

    def save(
        self,
        build_result: dict,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save paragraph inventory as Layer 2 JSON artifact.

        Args:
            build_result: Output from build()
            output_dir:   Output directory

        Returns:
            Path to saved artifact
        """
        output_dir = output_dir or LAYER2_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        program_name = build_result["program"]
        output_path  = output_dir / f"{program_name}_paragraphs.json"

        artifact = {
            "layer":           "L2",
            "source_file":     build_result["source_file"],
            "paragraph_count": build_result["paragraph_count"],
            "paragraphs":      build_result["paragraphs"],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)

        self.logger.info(
            f"Paragraph inventory saved: {output_path.name} "
            f"({build_result['paragraph_count']} paragraphs)"
        )
        return output_path
