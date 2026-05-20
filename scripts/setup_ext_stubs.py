import sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import COPYBOOK_DIR, OUT_DIR
from src.parsers.bms_parser import BMSParser

EXT_BMS = Path("corpus/app/app-authorization-ims-db2-mq/bms")
EXT_CPY = Path("corpus/app/app-authorization-ims-db2-mq/cpy")

# Step 1: Copy all extension copybooks to main cpy dir
print("=== Copying extension copybooks ===")
for f in list(EXT_CPY.glob("*.cpy")) + list(EXT_CPY.glob("*.CPY")):
    dst = COPYBOOK_DIR / f.name.lower()
    shutil.copy(f, dst)
    print(f"  Copied: {f.name}")

# Step 2: Generate BMS stubs from extension BMS files
print("\n=== Generating BMS stubs from extension BMS ===")
parser = BMSParser()
for bms_file in sorted(list(EXT_BMS.glob("*.bms")) + list(EXT_BMS.glob("*.BMS"))):
    result = parser.parse(bms_file)
    mapset = result["mapset_name"].upper()
    
    # Generate input/output copybook stubs
    for map_data in result["maps"]:
        fields = [f for f in map_data["fields"] if f["is_named"]]
        if not fields:
            continue
            
        # Generate stub content
        stub_lines = [f"      * BMS-generated stub for {mapset} map {map_data['name']}"]
        stub_lines.append(f"       01 {mapset}I.")
        for field in fields:
            stub_lines.append(f"          05 {field['name']}I PIC X({max(field['length'],1)}).")
        stub_lines.append(f"       01 {mapset}O.")
        for field in fields:
            stub_lines.append(f"          05 {field['name']}O PIC X({max(field['length'],1)}).")
        
        stub_content = "\n".join(stub_lines)
        
        # Save to main cpy dir
        for suffix in ["I", "O", ""]:
            stub_path = COPYBOOK_DIR / f"{mapset}{suffix}.cpy".lower()
        
        stub_path = COPYBOOK_DIR / f"{mapset}.cpy".lower()
        stub_path.write_text(stub_content, encoding="utf-8")
        print(f"  Generated: {stub_path.name}")

print("\nDone!")
