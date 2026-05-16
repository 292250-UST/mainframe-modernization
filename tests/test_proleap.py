import subprocess
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))
from config import CORPUS_DIR, PROLEAP_JAR, COPYBOOK_DIR, WRAPPER_DIR, OUT_DIR

def parse_cobol(cbl_file):
    result = subprocess.run(
        ["java", "-cp",
         f"{PROLEAP_JAR};{ROOT}/third_party/proleap-cobol-parser/target/dependency/*;{WRAPPER_DIR}",
         "CobolParserWrapper",
         str(cbl_file),
         str(COPYBOOK_DIR)],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return json.loads(result.stdout.strip().split('\n')[-1])
    else:
        return {"error": result.stderr.split('\n')[-2]}

if __name__ == "__main__":
    test_file = CORPUS_DIR / "app" / "cbl" / "CBACT01C.cbl"
    result = parse_cobol(test_file)
    print(f"Result: {result}")

    # Save to out/debug/day0_first_parse.json
    debug_dir = OUT_DIR / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    output_file = debug_dir / "day0_first_parse.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved to: {output_file}")