"""
ims_dbd_parser.py
=================
Parses IMS Database Definition (DBD) files.

Extracts:
- Database name, access method (HIDAM/HDAM/SHISAM etc.)
- Segment definitions (name, parent, key field)
- Field definitions within segments
"""

import re
import json
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("parsers.ims_dbd_parser")

# Patterns
DBD_PATTERN     = re.compile(r'DBD\s+NAME=([A-Z0-9@#$]+),ACCESS=\(?([A-Z,]+)\)?', re.IGNORECASE)
SEGM_PATTERN    = re.compile(r'SEGM\s+NAME=([A-Z0-9@#$]+)(?:,PARENT=([A-Z0-9@#]+))?(?:,BYTES=(\d+))?', re.IGNORECASE)
FIELD_PATTERN   = re.compile(r'FIELD\s+NAME=\(?([A-Z0-9@#$,SEQ]+)\)?(?:,START=(\d+))?(?:,BYTES=(\d+))?(?:,TYPE=([A-Z]+))?', re.IGNORECASE)
LCHILD_PATTERN  = re.compile(r'LCHILD\s+NAME=\(?([A-Z0-9@#$]+),([A-Z0-9@#$]+)\)?', re.IGNORECASE)


def parse_dbd_file(dbd_file: Path) -> dict:
    """Parse one IMS DBD file."""
    content  = dbd_file.read_text(encoding="utf-8", errors="replace")
    result   = {
        "source_file": dbd_file.name,
        "db_name":     "",
        "access":      "",
        "segments":    [],
        "logical_children": [],
    }

    current_segment = None

    for line in content.splitlines():
        # Skip comments and continuations indicator
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue

        # Remove continuation character
        line_clean = line.rstrip()
        if line_clean.endswith("C"):
            line_clean = line_clean[:-1]

        # DBD definition
        dbd_m = DBD_PATTERN.search(line_clean)
        if dbd_m:
            result["db_name"] = dbd_m.group(1).upper()
            result["access"]  = dbd_m.group(2).upper().strip("()")
            continue

        # SEGM definition
        segm_m = SEGM_PATTERN.search(line_clean)
        if segm_m:
            current_segment = {
                "name":    segm_m.group(1).upper(),
                "parent":  (segm_m.group(2) or "ROOT").upper().strip("()"),
                "bytes":   int(segm_m.group(3)) if segm_m.group(3) else 0,
                "fields":  [],
                "key_field": "",
            }
            result["segments"].append(current_segment)
            continue

        # FIELD definition
        field_m = FIELD_PATTERN.search(line_clean)
        if field_m and current_segment is not None:
            field_name = field_m.group(1).upper()
            is_seq     = "SEQ" in field_name
            clean_name = field_name.replace(",SEQ", "").replace("SEQ,", "")
            field = {
                "name":  clean_name,
                "start": int(field_m.group(2)) if field_m.group(2) else 0,
                "bytes": int(field_m.group(3)) if field_m.group(3) else 0,
                "type":  (field_m.group(4) or "CHAR").upper(),
                "seq":   is_seq,
            }
            current_segment["fields"].append(field)
            if is_seq:
                current_segment["key_field"] = clean_name
            continue

        # LCHILD
        lchild_m = LCHILD_PATTERN.search(line_clean)
        if lchild_m:
            result["logical_children"].append({
                "segment": lchild_m.group(1).upper(),
                "db":      lchild_m.group(2).upper(),
            })

    logger.info(
        f"DBD parsed: {result['db_name']} "
        f"({len(result['segments'])} segments, "
        f"access={result['access']})"
    )
    return result


def run(output_dir: Optional[Path] = None) -> dict:
    """Parse all IMS DBD files."""
    output_dir = output_dir or (OUT_DIR / "artifacts" / "layer6")
    output_dir.mkdir(parents=True, exist_ok=True)

    ims_dir = Path("corpus/app/app-authorization-ims-db2-mq/ims")
    dbd_files = sorted(
        list(ims_dir.glob("*.dbd")) + list(ims_dir.glob("*.DBD"))
    )

    # Deduplicate
    seen = {}
    for f in dbd_files:
        if f.stem.upper() not in seen:
            seen[f.stem.upper()] = f
    dbd_files = list(seen.values())

    all_results = []
    for f in dbd_files:
        result = parse_dbd_file(f)
        all_results.append(result)

    artifact = {
        "layer":    "L6",
        "dbd_count": len(all_results),
        "databases": all_results,
    }

    output_path = output_dir / "ims_dbd_schema.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"IMS DBD: {len(all_results)} databases parsed")
    return artifact


if __name__ == "__main__":
    result = run()
    print(f"Databases: {result['dbd_count']}")
    for db in result["databases"]:
        print(f"\n  {db['db_name']} (access={db['access']})")
        for seg in db["segments"]:
            print(f"    SEGM: {seg['name']:<20} parent={seg['parent']:<15} bytes={seg['bytes']}")
            for fld in seg["fields"]:
                seq = " [KEY]" if fld["seq"] else ""
                print(f"      FIELD: {fld['name']:<20} start={fld['start']:3} bytes={fld['bytes']:3}{seq}")
