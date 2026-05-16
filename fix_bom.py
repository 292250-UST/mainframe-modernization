from pathlib import Path

cpy_dir = Path("corpus/app/cpy")
fixed = 0
for cpy_file in cpy_dir.glob("*.cpy"):
    content = cpy_file.read_text(encoding="utf-8-sig")  # utf-8-sig strips BOM on read
    cpy_file.write_text(content, encoding="utf-8")       # write back without BOM
    fixed += 1
print(f"Fixed {fixed} files")
