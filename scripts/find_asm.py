from pathlib import Path

corpus = Path("corpus")
for ext in [".asm", ".ASM", ".s", ".S"]:
    files = list(corpus.rglob(f"*{ext}"))
    if files:
        print(f"{ext}: {[f.name for f in files]}")

# Also check corpus inventory
print("\nAll files in corpus/app/:")
for f in sorted(Path("corpus/app").rglob("*")):
    if f.is_file() and f.suffix.lower() not in [".cbl", ".cpy", ".jcl", ".bms", ".csd", ".md", ".txt"]:
        print(f"  {f.relative_to('corpus')}")
