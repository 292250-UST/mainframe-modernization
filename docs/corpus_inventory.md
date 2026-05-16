Generated: 2026-05-15  
Source: https://github.com/aws-samples/aws-mainframe-modernization-carddemo

## File Counts by Type

| Extension | Count | Description |
|---|---|---|
| .cbl | 44 | COBOL programs (online + batch) |
| .cpy | 62 | Copybooks (shared data definitions) |
| .jcl | 46 | JCL batch job definitions |
| .bms | 21 | BMS screen map definitions |
| .csd | 4 | CICS CSD resource definitions |
| .asm | 2 | Assembler routines (MVSWAIT, COBDATFT) |
| **Total** | **179** | **All source artifacts** |

## Notes

- `.cbl` files are split between online (CO prefix) and batch (CB prefix) programs
- `.cpy` copybooks are shared across multiple programs — provenance tracking required
- `.jcl` jobs form dependency chains via shared datasets (e.g. POSTTRAN → INTCALC → CREASTMT)
- `.asm` files are opaque callable stubs — recognized but not fully parsed
- `.csd` definitions map CICS transaction IDs to programs and resources
"@ | Out-File -FilePath docs\corpus_inventory.md -Encoding utf8