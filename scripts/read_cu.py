from pathlib import Path

f = Path("third_party/proleap-cobol-parser/src/main/java/io/proleap/cobol/asg/metamodel/CompilationUnit.java")
print(f.read_text(encoding="utf-8"))
