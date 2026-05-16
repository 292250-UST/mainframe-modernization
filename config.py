from pathlib import Path

ROOT = Path(__file__).parent

PROLEAP_JAR = ROOT / "third_party" / "proleap-cobol-parser" / "target" / "proleap-cobol-parser-4.0.0.jar"
WRAPPER_DIR  = ROOT / "third_party" / "cobol-parser-wrapper"
CORPUS_DIR   = ROOT / "corpus"
COPYBOOK_DIR = ROOT / "corpus" / "app" / "cpy"
OUT_DIR      = ROOT / "out"