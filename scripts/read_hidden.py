from pathlib import Path

f = Path("third_party/proleap-cobol-parser/src/main/java/io/proleap/cobol/preprocessor/sub/document/impl/CobolHiddenTokenCollectorListenerImpl.java")
print(f.read_text(encoding="utf-8"))
