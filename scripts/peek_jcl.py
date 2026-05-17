from pathlib import Path

jcl_dir = Path("corpus/app/jcl")
files = sorted(jcl_dir.glob("*.jcl"))
print(f"Total JCL files: {len(files)}")
print("\nFirst file:", files[0].name)
print(files[0].read_text(encoding="utf-8", errors="replace")[:2000])
