"""
bms_parser.py
=============
Parses BMS (Basic Mapping Support) screen map files.

WHAT IT EXTRACTS:
    DFHMSD  - Mapset definition (name, mode, language)
    DFHMDI  - Map definition (name, size, position)
    DFHMDF  - Field definition (name, position, length, attributes)

OUTPUT:
    bms_catalog.json with all screen maps and fields
"""

import re
import json
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("parsers.bms_parser")

# Match named BMS macro lines
# NAME DFHMSD/DFHMDI/DFHMDF ...
MACRO_PATTERN = re.compile(
    r'^([A-Z0-9@#$]{1,8})?\s+(DFHMSD|DFHMDI|DFHMDF)\s+(.*)$',
    re.IGNORECASE
)

# Extract KEY(VALUE) pairs from macro parameters
PARAM_PATTERN = re.compile(r'([A-Z]+)=(?:\(([^)]*)\)|([^\s,]+))', re.IGNORECASE)


def _join_continuations(lines: list[str]) -> list[str]:
    """
    Join BMS continuation lines (ending with -) into logical lines.
    BMS uses trailing hyphen for continuation.
    """
    joined = []
    buffer = ""

    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith("-"):
            buffer += stripped[:-1] + " "
        else:
            buffer += stripped
            if buffer.strip():
                joined.append(buffer)
            buffer = ""

    if buffer.strip():
        joined.append(buffer)

    return joined


def _extract_params(param_str: str) -> dict:
    """Extract KEY=VALUE or KEY=(VALUE) pairs from parameter string."""
    params = {}
    for m in PARAM_PATTERN.finditer(param_str):
        key = m.group(1).upper()
        val = (m.group(2) or m.group(3) or "").strip()
        params[key] = val
    return params


def _extract_pos(pos_str: str) -> tuple[int, int]:
    """Extract (row, col) from POS=(row,col) or POS=(n)."""
    parts = pos_str.strip("()").split(",")
    try:
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
        return int(parts[0]), 1
    except ValueError:
        return 0, 0


class BMSParser:
    """
    Parses BMS map definition files into structured screen catalogs.

    Extracts mapsets, maps, and fields with positions,
    lengths, and attributes for Layer 6 artifact contract.
    """

    def __init__(self):
        self.logger = get_logger("parsers.bms_parser")

    def parse(self, bms_file: Path) -> dict:
        """
        Parse one BMS file into structured map catalog.

        Args:
            bms_file: Path to .bms file

        Returns:
            dict with mapset name, maps[], fields[]
        """
        logger.debug(f"Parsing BMS: {bms_file.name}")

        content = bms_file.read_text(encoding="utf-8", errors="replace")
        lines   = _join_continuations(content.splitlines())

        mapset_name  = bms_file.stem.upper()
        maps         = []
        current_map  = None
        filler_count = 0

        for line in lines:
            # Skip comments and empty lines
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue

            match = MACRO_PATTERN.match(line)
            if not match:
                continue

            name       = (match.group(1) or "").strip().upper()
            macro_type = match.group(2).upper()
            param_str  = match.group(3)
            params     = _extract_params(param_str)

            if macro_type == "DFHMSD":
                # Mapset definition
                mapset_name = name or mapset_name
                # TYPE=FINAL marks end of mapset
                if params.get("TYPE", "").upper() == "FINAL":
                    continue

            elif macro_type == "DFHMDI":
                # Map definition
                size_str = params.get("SIZE", "24,80")
                size_parts = size_str.split(",")
                rows = int(size_parts[0]) if size_parts else 24
                cols = int(size_parts[1]) if len(size_parts) > 1 else 80

                current_map = {
                    "name":    name,
                    "mapset":  mapset_name,
                    "rows":    rows,
                    "cols":    cols,
                    "fields":  [],
                }
                maps.append(current_map)

            elif macro_type == "DFHMDF" and current_map is not None:
                # Field definition
                pos_str = params.get("POS", "(1,1)")
                row, col = _extract_pos(pos_str)

                try:
                    length = int(params.get("LENGTH", "0"))
                except ValueError:
                    length = 0

                # Extract attributes
                attrb  = params.get("ATTRB", "")
                color  = params.get("COLOR", "")
                initial = params.get("INITIAL", "")
                hilight = params.get("HILIGHT", "")

                # Determine field type from attributes
                is_protected = "ASKIP" in attrb.upper() or "PROT" in attrb.upper()
                is_numeric   = "NUM" in attrb.upper()
                is_bright    = "BRT" in attrb.upper()
                is_dark      = "DRK" in attrb.upper()
                is_input     = "UNPROT" in attrb.upper()
                is_fset      = "FSET" in attrb.upper()
                has_ic       = "IC" in attrb.upper()

                # Use name or generate filler name
                field_name = name if name else f"FILLER{filler_count:03d}"
                if not name:
                    filler_count += 1

                field = {
                    "name":         field_name,
                    "is_named":     bool(name),
                    "row":          row,
                    "col":          col,
                    "length":       length,
                    "attrb":        attrb,
                    "color":        color,
                    "hilight":      hilight,
                    "initial":      initial[:50] if initial else "",
                    "protected":    is_protected,
                    "numeric":      is_numeric,
                    "bright":       is_bright,
                    "dark":         is_dark,
                    "input":        is_input,
                    "fset":         is_fset,
                    "ic":           has_ic,
                }
                current_map["fields"].append(field)

        result = {
            "source_file":  bms_file.name,
            "mapset_name":  mapset_name,
            "map_count":    len(maps),
            "maps":         maps,
        }

        named_fields = sum(
            sum(1 for f in m["fields"] if f["is_named"])
            for m in maps
        )
        logger.debug(
            f"BMS parsed: {bms_file.name} — "
            f"{len(maps)} maps, {named_fields} named fields"
        )
        return result

    def parse_all(self, bms_dir: Path) -> list[dict]:
        """Parse all BMS files in a directory."""
        # Deduplicate by stem
        seen = {}
        for f in list(bms_dir.glob("*.bms")) + list(bms_dir.glob("*.BMS")):
            if f.stem.upper() not in seen:
                seen[f.stem.upper()] = f

        files = sorted(seen.values(), key=lambda f: f.stem.upper())
        logger.info(f"Parsing {len(files)} BMS files from {bms_dir}")

        results = []
        for f in files:
            results.append(self.parse(f))

        total_maps   = sum(r["map_count"] for r in results)
        total_fields = sum(
            sum(len(m["fields"]) for m in r["maps"])
            for r in results
        )
        logger.info(
            f"BMS batch parse complete: {len(files)} files, "
            f"{total_maps} maps, {total_fields} total fields"
        )
        return results

    def save(self, results: list[dict], output_dir: Optional[Path] = None) -> Path:
        """Save BMS catalog to Layer 6 artifact."""
        output_dir = output_dir or (OUT_DIR / "artifacts" / "layer6")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "bms_catalog.json"
        named_fields = sum(
            sum(1 for f in m["fields"] if f["is_named"])
            for r in results for m in r["maps"]
        )

        artifact = {
            "layer":        "L6",
            "file_count":   len(results),
            "map_count":    sum(r["map_count"] for r in results),
            "named_fields": named_fields,
            "mapsets":      results,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)

        logger.info(
            f"BMS catalog saved: {output_path} "
            f"({len(results)} mapsets, {named_fields} named fields)"
        )
        return output_path
