from pathlib import Path

content = Path("corpus/app/jcl/POSTTRAN.jcl").read_text(encoding="utf-8", errors="replace")
# Show only JCL statements (not comments)
for line in content.splitlines():
    if line.startswith("//") and not line.startswith("//*"):
        print(line)
