from pathlib import Path

lines = Path("corpus/app/cbl/CBACT01C.cbl").read_text(encoding="utf-8").splitlines()
in_data_div = False
count = 0
for i, line in enumerate(lines, 1):
    if "DATA DIVISION" in line.upper():
        in_data_div = True
    if "PROCEDURE DIVISION" in line.upper():
        break
    if in_data_div and count < 40:
        print(f"{i:4}: {line}")
        count += 1
