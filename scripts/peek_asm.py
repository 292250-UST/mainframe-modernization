from pathlib import Path

for name in ["MVSWAIT.asm", "COBDATFT.asm"]:
    f = Path(f"corpus/app/asm/{name}")
    print(f"\n{'='*50}")
    print(f"FILE: {name}")
    print(f.read_text(encoding="utf-8", errors="replace")[:800])
