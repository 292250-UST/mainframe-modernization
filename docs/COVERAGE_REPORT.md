# CardDemo Modernization Pipeline — Coverage Report
**Contestant:** 292250-UST | **Date:** May 2026

---

## 1. COBOL Parse Coverage

**Result: 30/31 files (96.8%) — Main Corpus**
**Extension Module: 8/8 files (100%)**

| Metric | Main Corpus | Extension Module | Total |
|---|---|---|---|
| Total .cbl files | 31 | 8 | 39 |
| Successfully parsed | 30 | 8 | 38 |
| Failed | 1 | 0 | 1 |
| Pass rate | 96.8% | 100% | 97.4% |

**Only failure:** `COACTUPC.cbl` — contains template placeholders (TESTVAR1) not valid COBOL. Correctly rejected by ProLeap, documented as known gap.

**Key engineering decisions:**
- Preprocess-then-parse architecture: Python COPY resolver runs before ProLeap
- 21 stub copybooks created for main corpus:
  - 17 BMS-generated stubs (auto-generated from .bms source files)
  - DFHAID.cpy, DFHBMSCA.cpy (IBM CICS system stubs)
  - CSUTLDWY.cpy, CSSTRPFY.cpy (application stubs)
- 6 MQ system stubs created for extension module:
  - CMQV, CMQMDV, CMQODV, CMQGMOV, CMQPMOV, CMQTML
- EXEC DLI pre-stripping: DLI blocks replaced with COBOL comments before ProLeap
- Extension COBOL extracted to separate layer1_ext/layer2_ext artifact dirs

**Extension module programs:**
CBPAUP0C, COPAUA0C (IMS+MQ), COPAUS0C, COPAUS1C, COPAUS2C, DBUNLDGS, PAUDBLOD, PAUDBUNL

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
| Known business chains | 1 (POSTTRAN → INTCALC → CREASTMT) |

**Engineering decision:** Regex-based Python parser chosen over ANTLR grammar after verifying corpus contains 0 PROC, 0 IF, 0 INCLUDE statements.

---

## 3. BMS Parse Coverage

**Result: 17/17 files (100%) — Main + 2/2 Extension**

| Metric | Value |
|---|---|
| Total .bms files | 19 (17 main + 2 extension) |
| Mapsets parsed | 19 |
| Named fields extracted | 441 (main) |
| BMS copybook stubs generated | 17 |

---

## 4. CSD Parse Coverage

**Result: 1/1 Main + 1/1 Extension**

| Resource | Main | Extension | Total |
|---|---|---|---|
| Programs | 18 | 4 | 22 |
| Transactions | 18 | 3 | 21 |
| Mapsets | 17 | 2 | 19 |
| Files | 8 | 0 | 8 |
| Libraries | 2 | 0 | 2 |

**Transaction count note:** Brief references 26 transactions — we find 21 statically. The 5 remaining are dynamically assigned via WS variables (e.g. WS-TRANID) at runtime. Static analysis cannot resolve runtime-assigned transaction IDs.

---

## 5. Assembler Coverage

**Result: 2/2 files recognized**

| File | Purpose |
|---|---|
| COBDATFT.asm | Date/time conversion routine |
| MVSWAIT.asm | Timer wait routine |

---

## 6. EXEC Statement Coverage

| Type | Count | Programs | Status |
|---|---|---|---|
| EXEC CICS | 150 | 17 main + 4 extension | ✅ Extracted |
| EXEC DLI | 52 | 4 extension programs | ✅ Extracted |
| EXEC MQ (CALL-based) | 8 | 1 program (COPAUA0C) | ✅ Extracted |
| EXEC SQL | 0 | 0 | ✅ Verified absent in main corpus |

**MQ note:** MQ uses CALL-based API (MQOPEN/MQGET/MQPUT1/MQCLOSE), not EXEC MQ syntax.

---

## 7. DuckDB Artifact Store

**17 tables, all populated:**

| Table | Count | Description |
|---|---|---|
| nodes | 664 | ProgramNode + ParagraphNode |
| symbols | 8,126 | Data items with canonical types |
| paragraphs | 626 | Paragraph inventory with complexity |
| copybook_use | 196 | Copybook dependency edges |
| call_graph | 57 | CALL + CICS XCTL edges |
| file_io | 245 | READ/WRITE/OPEN/CLOSE operations |
| transaction_flow | 53 | CICS XCTL/LINK/RETURN edges |
| jcl_job | 93 | JCL job step records |
| jcl_dependency | 1 | Inter-job dataset dependencies |
| business_rules | 887 | IF/EVALUATE predicates |
| control_flow | 761 | CFG PERFORM edges |
| def_use | 3,403 | Variable definition/use chains |
| ims_io | 52 | IMS DLI calls |
| mq_io | 4 | MQ API calls |
| db_io | 3 | DB2 DDL definitions |
| screen_map | 0 | BMS screen/map graph (known gap) |
| migration_risk | 0 | Migration risk register (known gap) |

---

## 8. Symbol Type Distribution

| Canonical Type | Count | COBOL Source | Java/Python Target |
|---|---|---|---|
| alphanumeric | 4,239 | PIC X/A | String |
| group | 1,070 | 01-level groups | class/struct |
| numeric | 650 | PIC 9 zoned decimal | long/int |
| binary | 488 | COMP/COMP-4 | int/long |
| decimal | 78 | PIC S9V99 | BigDecimal |
| packed_decimal | 6 | COMP-3 | BigDecimal (packed) |
| edited_numeric | 4 | ZZZ,ZZZ display | String (formatting) |

---

## 9. VSAM File Schemas

| File | Type | Key | Record Length | Copybook |
|---|---|---|---|---|
| ACCTDAT | KSDS | ACCT-ID | 350 bytes | CVACT01Y |
| CARDDAT | KSDS | CARD-NUM | 300 bytes | CVACT03Y |
| CCXREF | KSDS | XREF-CARD-NUM | 50 bytes | CVTRA05Y |
| CUSTDAT | KSDS | CUST-ID | 500 bytes | CUSTREC |
| TRANSACT | KSDS | TRAN-ID | 350 bytes | CVTRA05Y |
| USRSEC | KSDS | SEC-USR-ID | 500 bytes | CSUSR01Y |
| CARDAIX | AIX | CARD-NUM | 300 bytes | CVACT03Y |
| CXACAIX | AIX | XREF-CARD-NUM | 50 bytes | CVTRA05Y |

---

## 10. DB2 Schema

| Table | Columns | Primary Key |
|---|---|---|
| CARDDEMO.AUTHFRDS | 26 | CARD_NUM, AUTH_TS |
| CARDDEMO.TRANSACTION_TYPE | 2 | TR_TYPE |
| CARDDEMO.TRANSACTION_TYPE_CATEGORY | 3 | TRC_TYPE_CODE, TRC_TYPE_CATEGORY |

---

## 11. IMS Database Schema

| Database | Access | Segments |
|---|---|---|
| DBPAUTP0 | HIDAM/VSAM | PAUTSUM0 (key=ACCNTID), PAUTDTL1 (key=PAUT9CTS) |
| DBPAUTX0 | INDEX/VSAM | PAUTINDX (key=INDXU) |
| PADFLDBD | GSAM/BSAM | — |
| PASFLDBD | GSAM/BSAM | — |

---

## 12. GDG Registry

| GDG Base | Generations | Jobs |
|---|---|---|
| AWS.M2.CARDDEMO.TRANSACT.BKUP | +1, 0 | COMBTRAN, TRANREPT |
| AWS.M2.CARDDEMO.TRANSACT.COMBINED | +1 | COMBTRAN |
| AWS.M2.CARDDEMO.SYSTRAN | +1 | INTCALC |
| AWS.M2.CARDDEMO.DALYREJS | +1 | POSTTRAN |
| AWS.M2.CARDDEMO.TCATBALF.BKUP | +1 | PRTCATBL |
| AWS.M2.CARDDEMO.TRANSACT.DALY | +1 | TRANREPT |
| AWS.M2.CARDDEMO.TRANREPT | +1 | TRANREPT |

---

## 13. Architectural Rules Compliance

### Rule 1: No raw source reaches the LLM ✅
`format_slice_for_llm()` sends structured artifacts only:
- Paragraph names + line ranges + UUIDs
- Symbol names + PIC + canonical types + UUIDs
- CFG edges (PERFORM chains)
- Business rules (IF/EVALUATE predicates)
- CICS statements (verb + params)
- File I/O operations
- Def-use chains

### Rule 2: Every artifact is traceable ✅
- 0 nodes with missing source/line
- 0 symbols with missing source
- 0 paragraphs with missing source/line
- 0 business rules with missing source/line
- All UUIDs stable (SHA-256 based, deterministic)

### Rule 3: Artifacts cross-link ✅
- 626 paragraphs → programs (via parent_uuid)
- 8,126 symbols → programs (via program_uuid)
- 887 business rules → programs
- 196 copybook edges → programs
- 3,403 def-use entries → source files
- 761 CFG edges → source files

---

## 14. Known Gaps (Honest Reporting)

| Gap | Reason | Impact |
|---|---|---|
| COACTUPC.cbl fails ProLeap | Template placeholders (TESTVAR1) | 1 program without AST — documented |
| screen_map table empty | BMS catalog exists but map graph not built | Layer 4 gap |
| migration_risk table empty | Extractor not implemented | Layer 7 gap |
| Dead code report missing | Never-PERFORM'd paragraph analysis not built | Layer 7 gap |
| 5 dynamic transaction IDs | Runtime-resolved via WS variables | 21/26 transactions found |
| EXEC SQL = 0 | No embedded SQL in main COBOL programs | DB2 DDL only |
| Mermaid diagrams | Post code-freeze deliverable | §10 pending |

---

## 15. Overall Parse Coverage

| Source | Files | Parsed | Rate |
|---|---|---|---|
| COBOL (.cbl) | 39 | 38 | 97.4% |
| JCL (.jcl) | 38 | 38 | 100% |
| BMS (.bms) | 19 | 19 | 100% |
| CSD (.csd) | 2 | 2 | 100% |
| ASM (.asm) | 2 | 2 | 100% |
| DDL (.ddl) | 6 | 6 | 100% |
| DBD (.dbd) | 4 | 4 | 100% |
| **Overall** | **110** | **109** | **99.1%** |
