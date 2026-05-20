import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OUT_DIR

jcl_path = OUT_DIR / "artifacts" / "jcl" / "jcl_all.json"
jcl_data = json.loads(jcl_path.read_text())

gdg_bases = {}
pds_refs  = []

for job in jcl_data["jobs"]:
    for step in job["steps"]:
        for ds in step["datasets"]:
            dsn  = ds.get("dsn", "")
            disp = ds.get("disposition", "")
            dd   = ds.get("dd_name", "")

            # GDG detection: (+1), (0), (-1) suffix
            gdg_m = re.search(r'(.+?)\(([+-]?\d+)\)$', dsn)
            if gdg_m:
                base = gdg_m.group(1)
                gen  = gdg_m.group(2)
                if base not in gdg_bases:
                    gdg_bases[base] = {
                        "base_dsn":   base,
                        "references": [],
                    }
                gdg_bases[base]["references"].append({
                    "job":         job["job_name"],
                    "dd_name":     dd,
                    "generation":  gen,
                    "disposition": disp,
                })

            # PDS detection: member reference (LOADLIB, PROCLIB etc.)
            elif "(" in dsn and "LOADLIB" in dsn.upper():
                pds_refs.append({
                    "job":    job["job_name"],
                    "dsn":    dsn,
                    "dd":     dd,
                })

# Build artifact
artifact = {
    "layer":      "L4",
    "gdg_count":  len(gdg_bases),
    "pds_count":  len(pds_refs),
    "gdg_bases":  list(gdg_bases.values()),
    "pds_refs":   pds_refs,
    "notes": [
        "GDG (Generation Data Group): versioned sequential datasets",
        "(+1) = next generation (new), (0) = current, (-1) = previous",
        "Used for: daily transaction backups, reject files, report archives",
        "PDS (Partitioned Dataset): library datasets used as STEPLIB",
    ]
}

output_path = OUT_DIR / "artifacts" / "layer4" / "gdg_pds_registry.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(artifact, f, indent=2)

print(f"GDG bases: {len(gdg_bases)}")
for base, info in gdg_bases.items():
    gens = set(r["generation"] for r in info["references"])
    jobs = set(r["job"] for r in info["references"])
    print(f"  {base}")
    print(f"    Generations: {sorted(gens)}")
    print(f"    Jobs: {sorted(jobs)}")

print(f"\nPDS references: {len(pds_refs)}")
print(f"Saved: {output_path}")
