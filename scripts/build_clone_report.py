import sys, json, duckdb
from pathlib import Path
sys.path.insert(0, '.')
from config import OUT_DIR

DB_PATH = OUT_DIR / 'graph' / 'artifacts.duckdb'
conn = duckdb.connect(str(DB_PATH), read_only=True)

print('=== CLONE ANALYSIS ===')

programs = conn.execute("""
    SELECT DISTINCT program_uuid,
           SUBSTR(source_file, 1, LENGTH(source_file)-4) as prog_name
    FROM paragraphs ORDER BY prog_name
""").fetchall()

fingerprints = {}
for prog_uuid, prog_name in programs:
    paras = conn.execute("""
        SELECT name, statement_count, complexity
        FROM paragraphs WHERE program_uuid = ?
        ORDER BY start_line
    """, [prog_uuid]).fetchall()
    fp = tuple(sorted((p[1], p[2]) for p in paras))
    fingerprints[prog_name] = {
        'uuid': prog_uuid,
        'fingerprint': fp,
        'para_count': len(paras),
        'paragraphs': [p[0] for p in paras]
    }

clones = []
prog_names = list(fingerprints.keys())
for i in range(len(prog_names)):
    for j in range(i+1, len(prog_names)):
        a, b = prog_names[i], prog_names[j]
        fa = set(fingerprints[a]['fingerprint'])
        fb = set(fingerprints[b]['fingerprint'])
        if not fa or not fb: continue
        overlap    = len(fa & fb)
        union      = len(fa | fb)
        similarity = overlap / union if union > 0 else 0
        if similarity >= 0.6:
            clones.append({
                'program_a':    a,
                'program_b':    b,
                'similarity':   round(similarity, 3),
                'shared_paras': overlap,
                'total_paras':  union,
                'para_count_a': fingerprints[a]['para_count'],
                'para_count_b': fingerprints[b]['para_count'],
            })

clones.sort(key=lambda x: x['similarity'], reverse=True)
print(f'Programs analyzed: {len(fingerprints)}')
print(f'Clone pairs found: {len(clones)} (>=60% similarity)')
for c in clones[:15]:
    print(f"  {c['program_a']:<15} ~ {c['program_b']:<15} {c['similarity']:.1%} shared={c['shared_paras']}/{c['total_paras']}")

report = {
    "analysis_method":   "Paragraph (statement_count, complexity) fingerprint Jaccard similarity",
    "threshold":         0.6,
    "programs_analyzed": len(fingerprints),
    "clone_pairs_found": len(clones),
    "clone_pairs":       clones,
    "caveats": [
        "Fingerprint uses (statement_count, complexity) pairs not paragraph names or AST text",
        "Structural similarity only — programs with same structure but different logic may appear",
        "Full AST diffing would be more precise — not implemented",
        "Threshold 60% chosen to surface obvious clones like COUSR01C/02C/03C"
    ]
}
out_path = OUT_DIR / 'artifacts' / 'layer7' / 'clone_report.json'
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w') as f:
    json.dump(report, f, indent=2)
print(f'Saved: {out_path}')
conn.close()
