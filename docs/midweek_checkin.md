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
| Failed | 1 |
| Pass rate | 96.8% |

**Only failure:** COACTUPC.cbl — contains template placeholders (TESTVAR1) that are not valid COBOL. Correctly rejected by ProLeap and documented as a known gap.

**Key engineering decisions:**
- Preprocess-then-parse architecture: Python COPY resolver runs before ProLeap, resolving all COPY statements including quoted syntax (COPY name)
- 21 stub copybooks created to enable online program parsing:
  - 17 BMS-generated stubs (auto-generated from .bms source files)
  - DFHAID.cpy, DFHBMSCA.cpy (IBM CICS system stubs)
  - CSUTLDWY.cpy, CSSTRPFY.cpy (application stubs)

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
| Dataset dependencies | 1 (CREASTMT to TXT2PDF1) |

**Engineering decision:** Regex-based Python parser chosen over ANTLR grammar after verifying corpus contains 0 PROC, 0 IF, 0 INCLUDE statements. Known business chain documented: POSTTRAN to INTCALC to CREASTMT.

---

## 3. AST for One Program — CBACT01C.cbl

| Metric | Value |
|---|---|
| Program type | batch |
| Total lines | 500 |
| Paragraphs | 16 |
| Copybooks resolved | CVACT01Y, CODATECN |
| UUID | 875123c70d767e89c93dd62673ba4b01 |

**UUID scheme:** SHA-256(source_file + line + node_kind)[:32] — deterministic across pipeline runs. Verified by 4 regression tests.

Paragraph inventory (sample):

| Paragraph | Start | End | Statements | Complexity |
|---|---|---|---|---|
| 0000-ACCTFILE-OPEN | 112 | 144 | 8 | 3 |
| 1000-ACCTFILE-GET-NEXT | 145 | 180 | 12 | 5 |
| 1100-DISPLAY-ACCT-RECORD | 181 | 210 | 9 | 2 |
| 9999-ABEND-PROGRAM | 468 | 500 | 3 | 1 |
| ... 12 more paragraphs | | | | |

---

## 4. Symbol Table for One Program — CBACT01C.cbl

| Metric | Value |
|---|---|
| Total symbols | 94 |
| From copybooks | 35 (37%) |
| Scope: WORKING-STORAGE | 67 |
| Scope: FILE | 27 |

Sample symbols:

| Name | Level | PIC | Canonical Type | Origin |
|---|---|---|---|---|
| ACCT-ID | 05 | 9(11) | numeric p11 s0 | CBACT01C.cbl:92 |
| ACCT-CURR-BAL | 05 | S9(10)V99 | decimal p12 s2 signed | CVACT01Y.cpy:15 |
| ACCT-CREDIT-LIMIT | 05 | S9(10)V99 | decimal p12 s2 signed | CVACT01Y.cpy:18 |
| WS-PGMNAME | 05 | X(08) | alphanumeric len=8 | CBACT01C.cbl:45 |
| END-OF-FILE | 05 | X(01) | alphanumeric len=1 | CBACT01C.cbl:55 |

---

## 5. Additional Parsers Complete (Day 2)

| Parser | Files | Result |
|---|---|---|
| BMS parser | 17 | 17 mapsets, 441 named fields |
| CSD parser | 1 | 18 programs, 18 transactions, 8 VSAM files |
| ASM stub recognizer | 2 | COBDATFT (CSECT), MVSWAIT (START) |

---

## 6. Assumptions and Known Gaps

| Item | Status | Notes |
|---|---|---|
| COACTUPC.cbl | Gap | Template placeholders — ProLeap correctly rejects |
| BMS copybook stubs | Assumption | Generated from .bms source — structurally correct |
| DFHAID / DFHBMSCA | Assumption | IBM standard stubs — high accuracy |
| EXEC SQL | Out of scope | 0 occurrences verified in corpus |
| EXEC DLI (IMS) | Out of scope | 0 occurrences in main CardDemo programs |
| EXEC MQ | Out of scope | 0 occurrences in main CardDemo programs |
| JCL ANTLR grammar | Decision | Regex chosen — 0 PROC/IF/INCLUDE in corpus |
