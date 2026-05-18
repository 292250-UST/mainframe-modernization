# Mid-Week Check-In — CardDemo Modernization Pipeline
**Date:** Monday May 18, 2026
**User Name:** 292250-UST (Amit Tewari)
**Repo:** https://github.com/292250-UST/mainframe-modernization

---

## 1. COBOL Parse Coverage

- **Total files:** 31
- **Passed:** 30
- **Failed:** 1 (COACTUPC.cbl — template placeholders, not valid COBOL)
- **Pass rate:** 96.8%

---

## 2. JCL Parse Coverage

- **Total files:** 38
- **Passed:** 38
- **Failed:** 0
- **Pass rate:** 100%

---

## 3. AST for One Program — CBACT01C.cbl

- **UUID:** 875123c70d767e89c93dd62673ba4b01
- **Kind:** ProgramNode
- **Type:** batch
- **Total lines:** 500
- **Paragraphs:** 16
- **Copybooks:** CVACT01Y, CODATECN
- **UUID scheme:** SHA-256(source_file + line + node_kind)[:32] — stable across runs

Sample paragraph nodes:

- 1000-ACCTFILE-GET-NEXT (uuid: 6695feb6...)
- 0000-ACCTFILE-OPEN (uuid: 390493a2...)
- 9999-ABEND-PROGRAM (uuid: ...)
- ... 13 more paragraphs

---

## 4. Symbol Table for One Program — CBACT01C.cbl

- **Total symbols:** 94
- **From copybooks:** 35 (37%)

Sample symbols:

| Name | Level | PIC | Canonical Type | Origin |
|---|---|---|---|---|
| ACCT-ID | 05 | 9(11) | numeric p11 s0 | CBACT01C.cbl:92 |
| ACCT-CURR-BAL | 05 | S9(10)V99 | decimal p12 s2 signed | CVACT01Y.cpy:15 |
| WS-PGMNAME | 05 | X(08) | alphanumeric len=8 | CBACT01C.cbl:45 |
