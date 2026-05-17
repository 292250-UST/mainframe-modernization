"""
csd_parser.py
=============
Parses CICS CSD (CICS System Definition) files.

WHAT IT EXTRACTS:
    DEFINE FILE        - VSAM file definitions
    DEFINE PROGRAM     - COBOL program registrations
    DEFINE TRANSACTION - Transaction ID to program mappings
    DEFINE MAPSET      - BMS screen map registrations

OUTPUT:
    csd_catalog.json with all CICS resource definitions
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

logger = get_logger("parsers.csd_parser")

# Match DEFINE TYPE(NAME) at start of logical line
DEFINE_PATTERN = re.compile(
    r'DEFINE\s+(FILE|PROGRAM|TRANSACTION|MAPSET|LIBRARY)\s*\(([^)]+)\)',
    re.IGNORECASE
)

# Extract key(value) pairs from CSD lines
PARAM_PATTERN = re.compile(r'([A-Z]+)\(([^)]*)\)', re.IGNORECASE)


def _join_continuations(lines: list[str]) -> list[str]:
    """Join CSD continuation lines into logical lines."""
    joined = []
    buffer = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            if buffer:
                joined.append(buffer)
                buffer = ""
            continue
        if buffer:
            buffer += " " + stripped
        else:
            buffer = stripped
        # CSD lines end their definition when next DEFINE starts
        if stripped.upper().startswith("DEFINE") and buffer != stripped:
            joined.append(buffer[:-len(stripped)].strip())
            buffer = stripped
    if buffer:
        joined.append(buffer)
    return joined


class CSDParser:
    """Parses CICS CSD files into structured resource definitions."""

    def __init__(self):
        self.logger = get_logger("parsers.csd_parser")

    def parse(self, csd_file: Path) -> dict:
        """
        Parse a CSD file into structured resource catalog.

        Args:
            csd_file: Path to .CSD file

        Returns:
            dict with files, programs, transactions, mapsets
        """
        logger.info(f"Parsing CSD: {csd_file.name}")

        content = csd_file.read_text(encoding="utf-8", errors="replace")

        # Split on DEFINE keyword — each define is one resource
        # Use regex to find all DEFINE blocks
        result = {
            "source_file":   csd_file.name,
            "files":         [],
            "programs":      [],
            "transactions":  [],
            "mapsets":       [],
            "libraries":     [],
        }

        # Find all DEFINE statements with their parameters
        # CSD is free-format with continuation — join lines first
        lines = content.splitlines()
        full_text = " ".join(l.strip() for l in lines if l.strip() and not l.strip().startswith("*"))

        # Split on DEFINE keyword
        defines = re.split(r'(?=\bDEFINE\b)', full_text, flags=re.IGNORECASE)

        for block in defines:
            block = block.strip()
            if not block:
                continue

            # Find resource type and name
            define_match = DEFINE_PATTERN.search(block)
            if not define_match:
                continue

            resource_type = define_match.group(1).upper()
            resource_name = define_match.group(2).strip().upper()

            # Extract all parameters
            params = {}
            for pm in PARAM_PATTERN.finditer(block):
                key = pm.group(1).upper()
                val = pm.group(2).strip()
                params[key] = val

            entry = {
                "name":   resource_name,
                "group":  params.get("GROUP", ""),
                "params": params,
            }

            if resource_type == "FILE":
                entry["dsname"]  = params.get("DSNAME", "")
                entry["status"]  = params.get("STATUS", "")
                entry["add"]     = params.get("ADD", "")
                entry["read"]    = params.get("READ", "")
                entry["update"]  = params.get("UPDATE", "")
                entry["delete"]  = params.get("DELETE", "")
                result["files"].append(entry)

            elif resource_type == "PROGRAM":
                entry["language"]  = params.get("LANGUAGE", "COBOL")
                entry["status"]    = params.get("STATUS", "")
                result["programs"].append(entry)

            elif resource_type == "TRANSACTION":
                entry["program"]   = params.get("PROGRAM", "")
                entry["status"]    = params.get("STATUS", "")
                entry["taskdataloc"] = params.get("TASKDATALOC", "")
                result["transactions"].append(entry)

            elif resource_type == "MAPSET":
                entry["status"]  = params.get("STATUS", "")
                result["mapsets"].append(entry)

            elif resource_type == "LIBRARY":
                result["libraries"].append(entry)

        logger.info(
            f"CSD parsed: {len(result['files'])} files, "
            f"{len(result['programs'])} programs, "
            f"{len(result['transactions'])} transactions, "
            f"{len(result['mapsets'])} mapsets"
        )
        return result

    def save(self, result: dict, output_dir: Optional[Path] = None) -> Path:
        """Save CSD catalog to JSON artifact."""
        output_dir = output_dir or (OUT_DIR / "artifacts" / "layer6")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "csd_catalog.json"
        artifact = {"layer": "L6", **result}

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)

        logger.info(f"CSD catalog saved: {output_path}")
        return output_path


def run(csd_dir: Optional[Path] = None) -> dict:
    """Run CSD parser on all CSD files."""
    csd_dir = csd_dir or Path("corpus/app/csd")
    parser  = CSDParser()
    result  = {}

    seen = {}
    for f in list(csd_dir.glob("*.CSD")) + list(csd_dir.glob("*.csd")):
        if f.stem.upper() not in seen:
            seen[f.stem.upper()] = f
    for csd_file in sorted(seen.values()):
        if csd_file.name == ".gitkeep":
            continue
        result = parser.parse(csd_file)
        parser.save(result)

    return result
