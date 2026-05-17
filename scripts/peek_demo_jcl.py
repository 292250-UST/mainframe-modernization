from pathlib import Path

jcl_dir = Path("corpus/app/jcl")
for name in ["POSTTRAN.jcl", "INTCALC.jcl", "CREASTMT.JCL"]:
    f = jcl_dir / name
    print(f"\n{'='*60}")
    print(f"FILE: {f.name}")
    print(f.read_text(encoding="utf-8", errors="replace")[:1200])
