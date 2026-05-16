"""
symbol_table.py
===============
Builds the symbol table and data dictionary for one COBOL program.

WHY THIS EXISTS:
    Layer 2 of the artifact contract requires:
    - Symbol table: every identifier with definition site + reference sites
    - Data dictionary: normalized data items with canonical types
    
    This module takes ProLeap data_items output and builds both.

WHAT IT PRODUCES:
    symbol_table.json per program:
    {
        "program": "CBACT01C",
        "symbols": [
            {
                "uuid": "...",
                "name": "ACCT-ID",
                "level": 5,
                "pic": "9(11)",
                "usage": "DISPLAY",
                "scope": "WORKING-STORAGE",
                "canonical_type": {
                    "kind": "numeric",
                    "precision": 11,
                    "scale": 0,
                    "signed": false
                },
                "copybook_origin": null,
                "defined_at": "CBACT01C.cbl:92"
            }
        ]
    }

DOWNSTREAM CONSUMERS:
    - def_use.py        (reads symbol UUIDs for def-use chains)
    - cfg_builder.py    (reads symbols for data flow in CFG)
    - business_rules.py (reads symbols for predicate resolution)
    - loader.py         (saves to DuckDB symbols table)
"""

import json
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from src.utils.logger import get_logger
from src.layers.l1_ast.ast_node import make_uuid, NodeKind
from src.preprocess.provenance_tracker import ProvenanceMap

import sys
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("layers.l2_symbols.symbol_table")

LAYER2_DIR = OUT_DIR / "artifacts" / "layer2"


# ---------------------------------------------------------------------------
# CANONICAL TYPE NORMALIZER
# ---------------------------------------------------------------------------

def normalize_pic(pic: Optional[str], usage: str = "DISPLAY") -> dict:
    """
    Normalize a COBOL PIC clause into a canonical type representation.

    COBOL PIC clause examples and their canonical forms:
        PIC X(08)           -> {kind: alphanumeric, length: 8}
        PIC 9(11)           -> {kind: numeric, precision: 11, scale: 0, signed: false}
        PIC S9(9)V99        -> {kind: decimal, precision: 11, scale: 2, signed: true}
        PIC S9(9)V99 COMP-3 -> {kind: decimal, precision: 11, scale: 2, signed: true, packed: true}
        PIC S9(09) COMP     -> {kind: binary, precision: 9, signed: true}

    This canonical form is what forward engineering uses to pick the right
    Java/Python type (BigDecimal vs long vs String etc.)

    Args:
        pic (str):   PIC clause string (e.g. 'S9(9)V99', 'X(08)')
        usage (str): USAGE clause (DISPLAY/COMP/COMP-3/COMP-4/BINARY)

    Returns:
        dict: Canonical type with kind, precision, scale, signed, packed
    """
    if not pic:
        return {"kind": "group", "length": 0}

    pic = pic.upper().strip()
    usage = usage.upper().strip()

    # Determine if signed
    signed = pic.startswith("S")
    pic_clean = pic.lstrip("S")

    # Alphanumeric: X or A
    if pic_clean.startswith("X") or pic_clean.startswith("A"):
        length_match = re.search(r'\((\d+)\)', pic_clean)
        length = int(length_match.group(1)) if length_match else 1
        return {
            "kind":   "alphanumeric",
            "length": length,
            "signed": False
        }

    # Numeric: 9 with optional V for decimal
    if "9" in pic_clean:
        # Find integer digits: 9(n) or 999
        int_match = re.search(r'9\((\d+)\)', pic_clean)
        if int_match:
            int_digits = int(int_match.group(1))
        else:
            int_digits = pic_clean.count("9")

        # Find decimal digits: V99 or V9(n)
        scale = 0
        if "V" in pic_clean:
            dec_part = pic_clean.split("V")[1]
            dec_match = re.search(r'9\((\d+)\)', dec_part)
            if dec_match:
                scale = int(dec_match.group(1))
            else:
                scale = dec_part.count("9")

        precision = int_digits + scale

        # Determine storage kind from USAGE
        packed = usage in ("COMP-3", "PACKED-DECIMAL")
        binary = usage in ("COMP", "COMP-4", "BINARY")

        if scale > 0:
            kind = "decimal"
        elif binary:
            kind = "binary"
        elif packed:
            kind = "packed_decimal"
        else:
            kind = "numeric"

        return {
            "kind":      kind,
            "precision": precision,
            "scale":     scale,
            "signed":    signed,
            "packed":    packed,
            "binary":    binary,
        }

    # Fallback
    return {"kind": "unknown", "raw_pic": pic}


# ---------------------------------------------------------------------------
# SYMBOL TABLE BUILDER
# ---------------------------------------------------------------------------

class SymbolTableBuilder:
    """
    Builds the Layer 2 symbol table and data dictionary for one program.

    Takes the raw data_items from ProLeap output and produces:
    - A list of normalized symbol entries with UUIDs
    - Canonical type for each data item
    - Copybook origin (from provenance map)
    - Definition site (source file + line)

    Usage:
        builder = SymbolTableBuilder()
        result = builder.build(parse_result, provenance_map)
        builder.save(result, output_dir)
    """

    def __init__(self):
        self.logger = get_logger("layers.l2_symbols.symbol_table")

    def build(
        self,
        parse_result: dict,
        provenance_map: Optional[ProvenanceMap] = None
    ) -> dict:
        """
        Build symbol table from ProLeap parse result.

        Args:
            parse_result (dict):        Output from proleap_wrapper
            provenance_map:             For copybook origin + line numbers

        Returns:
            dict with:
                program (str):      Program name
                source_file (str):  Source filename
                symbols (list):     List of symbol dicts
                symbol_count (int): Total symbols
        """
        source_file  = parse_result.get("source_file", "UNKNOWN.cbl")
        program_name = parse_result.get("program", source_file.replace(".cbl",""))
        data_items   = parse_result.get("data_items", [])

        self.logger.info(
            f"Building symbol table: {source_file} "
            f"({len(data_items)} data items)"
        )

        symbols = []
        for i, item in enumerate(data_items):
            name  = item.get("name", "FILLER")
            level = item.get("level", 1)
            pic   = item.get("pic")
            usage = item.get("usage", "DISPLAY")
            scope = item.get("scope", "WORKING-STORAGE")

            # Find definition line from provenance map
            defined_at_line = self._find_definition_line(
                name, provenance_map, source_file, i
            )

            # Get copybook origin from provenance map
            copybook_origin = self._find_copybook_origin(
                defined_at_line, provenance_map
            )

            # Generate stable UUID
            uuid = make_uuid(
                source_file,
                defined_at_line,
                f"{NodeKind.DATA_ITEM.value}:{name}"
            )

            # Normalize PIC to canonical type
            canonical_type = normalize_pic(pic, usage)

            symbol = {
                "uuid":            uuid,
                "name":            name,
                "level":           level,
                "pic":             pic,
                "usage":           usage,
                "scope":           scope,
                "canonical_type":  canonical_type,
                "copybook_origin": copybook_origin,
                "defined_at":      f"{source_file}:{defined_at_line}",
                "defined_at_line": defined_at_line,
            }
            symbols.append(symbol)

        self.logger.info(
            f"Symbol table built: {source_file} — "
            f"{len(symbols)} symbols, "
            f"{sum(1 for s in symbols if s['copybook_origin']) } from copybooks"
        )

        return {
            "program":      program_name,
            "source_file":  source_file,
            "symbols":      symbols,
            "symbol_count": len(symbols),
        }

    def _find_definition_line(
        self,
        name: str,
        provenance_map: Optional[ProvenanceMap],
        source_file: str,
        index: int
    ) -> int:
        """
        Find the line number where a data item is defined.

        Searches the provenance map for the variable name.
        Falls back to index-based placeholder if not found.
        """
        if provenance_map is None or not name or name == "FILLER":
            return index + 1

        name_upper = name.upper()
        for pline in provenance_map.lines:
            content = pline.content.upper()
            if name_upper in content and "PIC" in content:
                return pline.origin_line_num

        return index + 1

    def _find_copybook_origin(
        self,
        line_num: int,
        provenance_map: Optional[ProvenanceMap]
    ) -> Optional[str]:
        """
        Find which copybook a line came from using the provenance map.

        Args:
            line_num (int):     Line number in preprocessed source
            provenance_map:     Provenance tracking map

        Returns:
            str: Copybook name if from a copybook, None otherwise
        """
        if provenance_map is None:
            return None

        pline = provenance_map.get_line(line_num)
        if pline and pline.is_from_copybook():
            return pline.copybook

        return None

    def save(
        self,
        build_result: dict,
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save symbol table as Layer 2 JSON artifact.

        Args:
            build_result (dict):    Output from build()
            output_dir (Path):      Output directory

        Returns:
            Path: Path to saved artifact
        """
        output_dir = output_dir or LAYER2_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        program_name = build_result["program"]
        output_path  = output_dir / f"{program_name}_symbols.json"

        artifact = {
            "layer":        "L2",
            "source_file":  build_result["source_file"],
            "symbol_count": build_result["symbol_count"],
            "symbols":      build_result["symbols"],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)

        self.logger.info(
            f"Symbol table saved: {output_path.name} "
            f"({build_result['symbol_count']} symbols)"
        )
        return output_path
