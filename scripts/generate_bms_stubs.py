"""
generate_bms_stubs.py
=====================
Auto-generates COBOL copybook stubs from BMS map files.

BMS maps define screen fields (DFHMDF entries). Each named field
generates two entries in the copybook:
- Input structure (COXXXXXXI): fieldL (length), fieldA (attribute), fieldI (data)
- Output structure (COXXXXXXO): FILLER + fieldO (data)

This is the standard IBM BMS copybook generation pattern.
"""

import re
from pathlib import Path

BMS_DIR  = Path("corpus/app/bms")
CPY_DIR  = Path("corpus/app/cpy")

# Regex to find named DFHMDF fields (fields with a label)
# Example: TRNNAME DFHMDF ATTRB=..., LENGTH=4, POS=(1,7)
FIELD_PATTERN = re.compile(
    r'^([A-Z0-9#@$]{2,8})\s+DFHMDF.*?LENGTH=(\d+)',
    re.IGNORECASE | re.MULTILINE
)

# Regex to find DFHMSD mapset name
MAPSET_PATTERN = re.compile(
    r'^([A-Z0-9#@$]{2,8})\s+DFHMSD',
    re.IGNORECASE | re.MULTILINE
)

# Regex to find DFHMDI map name
MAP_PATTERN = re.compile(
    r'^([A-Z0-9#@$]{2,8})\s+DFHMDI',
    re.IGNORECASE | re.MULTILINE
)

def read_bms_continued(bms_path: Path) -> str:
    """
    Read BMS file joining continuation lines (lines ending with -)
    into single logical lines for easier parsing.
    """
    lines = bms_path.read_text(encoding="utf-8", errors="replace").splitlines()
    joined = []
    buffer = ""
    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith('-'):
            buffer += stripped[:-1] + " "
        else:
            buffer += stripped
            joined.append(buffer)
            buffer = ""
    if buffer:
        joined.append(buffer)
    return "\n".join(joined)


def generate_stub(bms_path: Path) -> str:
    """
    Generate a COBOL copybook stub from a BMS map file.

    Args:
        bms_path: Path to the .bms file

    Returns:
        String content of the generated .cpy stub
    """
    content = read_bms_continued(bms_path)
    mapset_name = bms_path.stem  # e.g. COTRN02

    # Find map name (DFHMDI)
    map_match = MAP_PATTERN.search(content)
    map_name = map_match.group(1) if map_match else mapset_name + "A"

    # Find all named fields
    fields = FIELD_PATTERN.findall(content)

    # Filter out BMS keywords that look like field names
    bms_keywords = {
        'DFHMSD', 'DFHMDI', 'DFHMDF', 'DFHMS', 'DFHMD',
        'COBOL', 'TYPE', 'LANG', 'MODE', 'CTRL', 'STORAGE',
    }
    fields = [
        (name, length) for name, length in fields
        if name.upper() not in bms_keywords
    ]

    # Build copybook content
    lines = []
    lines.append(f"      {'*' * 62}")
    lines.append(f"      * {mapset_name} - BMS Map Copybook Stub")
    lines.append(f"      * Generated from {bms_path.name}")
    lines.append(f"      * Map: {map_name}, Mapset: {mapset_name}")
    lines.append(f"      {'*' * 62}")

    # Input structure
    input_name = f"{map_name}I"
    lines.append(f"       01  {input_name}.")
    lines.append(f"           02  FILLER                    PIC X(12).")
    for name, length in fields:
        lines.append(f"           02  {name+'L':<22}  PIC S9(4) COMP.")
        lines.append(f"           02  {name+'A':<22}  PIC X.")
        lines.append(f"           02  {name+'I':<22}  PIC X({length}).")

    # Output structure (REDEFINES input)
    output_name = f"{map_name}O"
    lines.append(f"       01  {output_name} REDEFINES {input_name}.")
    lines.append(f"           02  FILLER                    PIC X(12).")
    for name, length in fields:
        lines.append(f"           02  FILLER                    PIC X(3).")
        lines.append(f"           02  {name+'O':<22}  PIC X({length}).")

    return "\n".join(lines)


def generate_all_stubs():
    """Generate stubs for all BMS files that don't have a copybook yet."""
    bms_files = sorted(BMS_DIR.glob("*.bms"))
    generated = []
    skipped = []

    for bms_file in bms_files:
        cpy_path = CPY_DIR / f"{bms_file.stem}.cpy"

        if cpy_path.exists():
            print(f"  SKIP (exists): {cpy_path.name}")
            skipped.append(bms_file.stem)
            continue

        stub_content = generate_stub(bms_file)
        cpy_path.write_text(stub_content, encoding="utf-8")
        print(f"  GENERATED: {cpy_path.name} ({len(stub_content)} bytes)")
        generated.append(bms_file.stem)

    print(f"\nDone: {len(generated)} generated, {len(skipped)} skipped")
    return generated


if __name__ == "__main__":
    print("Generating BMS copybook stubs...")
    generate_all_stubs()
