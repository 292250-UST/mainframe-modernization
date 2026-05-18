# Mid-Week Check-In — CardDemo Modernization Pipeline
**Date:** Monday May 18, 2026
**Contestant:** 292250-UST
**Repo:** https://github.com/292250-UST/mainframe-modernization

---

## 1. COBOL Parse Coverage

**Result: 30/31 files (96.8%)**

| Metric | Value |
|---|---|
| Total .cbl files | 31 |
| Successfully parsed | 30 |
| Failed | 1 (COACTUPC.cbl — template code) |
| Pass rate | 96.8% |

**Architecture:** Preprocess-then-parse — Python COPY resolver runs before ProLeap, 
resolving all COPY statements including quoted syntax. 21 stub copybooks created 
(17 BMS-generated + 4 IBM/app) to enable online program parsing.

**Only failure:** COACTUPC.cbl contains template placeholders (TESTVAR1) 
that are not valid COBOL — correctly rejected by ProLeap, documented as known gap.

---

## 2. JCL Parse Coverage

**Result: 38/38 files (100%)**

| Metric | Value |
|---|---|
| Total .jcl files | 38 |
| Successfully parsed | 38 |
| Pass rate | 100% |
| Steps extracted | 202 |
| Job records | 93 |
| Dataset dependencies | 1 (CREASTMT → TXT2PDF1) |

**Known business chain documented:** POSTTRAN → INTCALC → CREASTMT

---

## 3. AST for One Program — CBACT01C.cbl

`json
{
  "layer": "L1",
  "source_file": "CBACT01C.cbl",
  "node_count": 17,
  "program_node": {
    "uuid": "875123c70d767e89c93dd62673ba4b01",
    "kind": "ProgramNode",
    "source_range": {
      "source_file": "CBACT01C.cbl",
      "start_line": 1,
      "end_line": 500
    },
    "payload": {
      "program_name": "CBACT01C",
      "program_type": "batch",
      "copybooks": ["CVACT01Y", "CODATECN"],
      "total_lines": 500,
      "paragraph_count": 16
    }
  },
  "paragraph_nodes": [
    {"uuid": "6695feb6...", "payload": {"name": "1000-ACCTFILE-GET-NEXT"}},
    {"uuid": "390493a2...", "payload": {"name": "0000-ACCTFILE-OPEN"}},
    "... 14 more paragraphs"
  ]
}
`

**UUID scheme:** SHA-256(source_file + ":" + start_line + ":" + node_kind)[:32]
**Same source = same UUID across every pipeline run** — verified by 4 regression tests.

---

## 4. Symbol Table for One Program — CBACT01C.cbl

**94 symbols extracted, 35 (37%) traced to copybooks**

Sample symbols:
`json
[
  {
    "uuid": "a3f9c2e1...",
    "name": "ACCT-ID",
    "level": 5,
    "pic": "9(11)",
    "usage": "DISPLAY",
    "scope": "WORKING-STORAGE",
    "canonical_type": {
      "kind": "numeric",
      "precision": 11,
      "scale": 0,
      "signed": false
    },
    "copybook_origin": null,
    "defined_at": "CBACT01C.cbl:92"
  },
  {
    "uuid": "b7d4e8f2...",
    "name": "ACCT-CURR-BAL",
    "level": 5,
    "pic": "S9(10)V99",
    "usage": "DISPLAY",
    "canonical_type": {
      "kind": "decimal",
      "precision": 12,
      "scale": 2,
      "signed": true,
      "packed": false
    },
    "copybook_origin": "CVACT01Y",
    "defined_at": "CVACT01Y.cpy:15"
  }
]
`

---

## 5. Overall Pipeline Status

| Source Type | Parsed | Total | Rate |
|---|---|---|---|
| COBOL (.cbl) | 30 | 31 | 96.8% |
| JCL (.jcl) | 38 | 38 | 100% |
| BMS (.bms) | 17 | 17 | 100% |
| CSD (.csd) | 1 | 1 | 100% |
| ASM (.asm) | 2 | 2 | 100% |
| **Overall** | **88** | **89** | **98.9%** |

## 6. Artifacts Produced

- out/artifacts/layer1/ — 120 files (AST + provenance + tokens per program)
- out/artifacts/layer2/ — 90 files (symbols + paragraphs per program)
- out/artifacts/jcl/ — JCL graph + dependency map
- out/artifacts/layer6/ — BMS catalog + CSD catalog
- out/artifacts/assembler_stubs.json
- out/graph/artifacts.duckdb — 17 tables, 521 nodes, 6535 symbols, 491 paragraphs
- out/reports/parse_coverage.json — honest coverage report

## 7. What's Next (Days 3-9)

- Day 3: EXEC CICS extractor, EXEC SQL extractor, data lineage
- Day 4-5: CFG, def-use chains, call graph, file I/O graph
- Day 6: FastAPI REST layer, business rules
- Day 7: LLM integration, spec generation demo
- Day 8: Canonical IR (stretch)
- Day 9: Final submission tag
