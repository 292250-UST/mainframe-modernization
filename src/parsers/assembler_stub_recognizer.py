"""
assembler_stub_recognizer.py
============================
Recognizes Assembler stub routines called by COBOL programs.

WHY THIS EXISTS:
    CardDemo has 2 Assembler routines:
    - MVSWAIT  (timer wait — called by batch jobs)
    - COBDATFT (date/time conversion — called by COBOL programs)

    These are opaque callable units — we don't parse their internals,
    just record their entry points so the call graph knows they exist.

WHAT IT PRODUCES:
    assembler_stubs.json:
    {
        "stubs": [
            {
                "name": "MVSWAIT",
                "source_file": "MVSWAIT.asm",
                "entry_type": "START",
                "description": "Timer wait routine"
            },
            {
                "name": "COBDATFT",
                "source_file": "COBDATFT.asm",
                "entry_type": "CSECT",
                "description": "Date/time conversion routine"
            }
        ]
    }
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

logger = get_logger("parsers.assembler_stub_recognizer")

# Regex to find CSECT or START entry points
# Pattern: NAME CSECT or NAME START n
ENTRY_PATTERN = re.compile(
    r'^([A-Z0-9@#$]{1,8})\s+(CSECT|START|ENTRY)\b',
    re.IGNORECASE
)

# Known descriptions for CardDemo assembler routines
KNOWN_DESCRIPTIONS = {
    "MVSWAIT":  "Timer wait routine — pauses batch job for specified interval",
    "COBDATFT": "Date/time conversion routine — converts dates between formats",
    "COBSWAIT": "COBOL-callable wait routine — wrapper around MVSWAIT",
}


def recognize_stubs(asm_dir: Path) -> list[dict]:
    """
    Scan assembler files and extract entry point stubs.

    Args:
        asm_dir: Directory containing .asm files

    Returns:
        list of stub records
    """
    # Deduplicate by stem (handle mixed case .asm/.ASM)
    seen = {}
    for f in list(asm_dir.glob("*.asm")) + list(asm_dir.glob("*.ASM")):
        if f.stem.upper() not in seen:
            seen[f.stem.upper()] = f
    asm_files = sorted(seen.values())
    
    logger.info(f"Scanning {len(asm_files)} assembler files in {asm_dir}")

    stubs = []
    for asm_file in sorted(asm_files):
        try:
            lines = asm_file.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except Exception as e:
            logger.error(f"Cannot read {asm_file.name}: {e}")
            continue

        for line in lines:
            match = ENTRY_PATTERN.match(line)
            if match:
                name       = match.group(1).upper()
                entry_type = match.group(2).upper()

                stub = {
                    "name":        name,
                    "source_file": asm_file.name,
                    "entry_type":  entry_type,
                    "description": KNOWN_DESCRIPTIONS.get(name, "Assembler routine"),
                    "calling_convention": "standard",
                    "parameters": "via registers or COBOL CALL USING",
                }
                stubs.append(stub)
                logger.info(f"Found stub: {name} ({entry_type}) in {asm_file.name}")
                break  # One entry point per file is enough

    return stubs


def save_stubs(stubs: list[dict], output_dir: Optional[Path] = None) -> Path:
    """
    Save assembler stub catalog to JSON.

    Args:
        stubs:      List of stub records
        output_dir: Output directory

    Returns:
        Path to saved artifact
    """
    output_dir = output_dir or (OUT_DIR / "artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "assembler_stubs.json"
    artifact = {
        "layer":      "L6",
        "stub_count": len(stubs),
        "stubs":      stubs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"Assembler stubs saved: {output_path} ({len(stubs)} stubs)")
    return output_path


def run(asm_dir: Optional[Path] = None) -> list[dict]:
    """Run the assembler stub recognizer."""
    asm_dir = asm_dir or Path("corpus/app/asm")
    stubs   = recognize_stubs(asm_dir)
    save_stubs(stubs)
    return stubs
