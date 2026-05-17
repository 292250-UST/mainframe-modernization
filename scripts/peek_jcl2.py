from pathlib import Path

jcl_dir = Path("corpus/app/jcl")
# Find POSTTRAN or similar batch chain files
for name in ["POSTTRAN", "INTCALC", "CREASTMT", "CBTRN"]:
    matches = list(jcl_dir.glob(f"*{name}*.jcl"))
    for f in matches:
        print(f"\n{'='*60}")
        print(f"FILE: {f.name}")
        print(f.read_text(encoding="utf-8", errors="replace")[:1500])
