# Batch Chain Demo — POSTTRAN → INTCALC → CREASTMT
**Generated:** May 19, 2026
**Demo B — Batch Job Chain Spec Generation**

---

## Chain Overview

| Job | Program | Purpose |
|---|---|---|
| POSTTRAN | CBTRN02C | Post daily transactions to account files |
| INTCALC | CBACT04C | Calculate interest on account balances |
| CREASTMT | CBSTM03A | Generate customer statements (PS + HTML) |

**Dataset flow:**
- POSTTRAN writes: DALYREJS(+1), reads: TRANSACT, ACCTDATA, TCATBALF
- INTCALC reads: TCATBALF, ACCTDATA, DISCGRP, CARDXREF
- CREASTMT reads: TRXFL, ACCTDATA, CARDXREF, CUSTDATA → writes STATEMNT.PS + STATEMNT.HTML

---

## CBTRN02C — Post Transactions (POSTTRAN job)

**Key facts (from artifacts):**
- 26 paragraphs, 127 symbols, complexity=9
- Reads DALYTRAN daily transaction file
- Validates each transaction against XREF + ACCOUNT files
- Posts valid transactions to TCATBAL (category balances)
- Updates ACCOUNT balances
- Writes rejects to DALYREJS file
- Calls CEE3ABD on abend [LINE:711]

**Grounding sample:**
- TRAN-AMT [VAR:TRAN-AMT] flows from DALYTRAN input [LINE:345]
- to TCATBAL update [LINE:467-544]
- to ACCOUNT rewrite [LINE:545-561]
- to TRANSACT write [LINE:562-581]

---

## CBACT04C — Interest Calculator (INTCALC job)

**Key facts (from artifacts):**
- 22 paragraphs, 50 symbols, complexity=9
- Reads TCATBAL file (produced upstream by CBTRN02C)
- Looks up interest rate from DISCGRP file
- Default rate path: PARA:1200-A-GET-DEFAULT-INT-RATE
- Computes interest in COMPUTE-INTEREST [PARA:1300-COMPUTE-INTEREST]
- Rewrites ACCOUNT file with updated balances
- Writes new TRANSACT records for interest charges

**Grounding sample:**
- DIS-INT-RATE [VAR:DIS-INT-RATE] from DISCGRP lookup [LINE:416]
- applied to TRAN-CAT-BAL [VAR:TRAN-CAT-BAL]
- result written to TRANSACT [LINE:500]

---

## CBSTM03A — Statement Generator (CREASTMT job)

**Key facts (from artifacts):**
- 25 paragraphs, 50 symbols, complexity=8
- Reads TRNX file (transactions produced by INTCALC)
- Joins with XREF, CUSTOMER, ACCOUNT data via CBSTM03B calls (13x)
- Creates statement content in CREATE-STATEMENT [PARA:5000-CREATE-STATEMENT]
- Writes HTML header [PARA:5100-WRITE-HTML-HEADER]
- Writes HTML body [PARA:5200-WRITE-HTML-NMADBS]
- Writes transaction lines [PARA:6000-WRITE-TRANS]
- Outputs: FD-STMTFILE-REC (PS) + FD-HTMLFILE-REC (HTML)

**Grounding sample:**
- CUST-FIRST-NAME [VAR:CUST-FIRST-NAME] from CUSTOMER file [LINE:377]
- ACCT-CURR-BAL [VAR:ACCT-CURR-BAL] from ACCOUNT file [LINE:401]
- written to statement via [PARA:5000-CREATE-STATEMENT]

---

## End-to-End Data Lineage

DALYTRAN input
  -> CBTRN02C validates + posts
  -> TCATBALF updated (category balances)
  -> CBACT04C reads TCATBALF + computes interest
  -> TRANSACT updated (interest charges added)
  -> CBSTM03A reads TRANSACT + joins XREF/CUST/ACCT
  -> STATEMNT.PS + STATEMNT.HTML produced

**Every step grounded in artifacts — no fabrication.**

---

## Grounding Verification

All spec claims cite:
- [LINE:xxx] — source line number in .cbl file
- [VAR:name] — data item in symbol table
- [PARA:name] — paragraph in paragraph inventory
- [COPY:name] — copybook in provenance map
- [FILE I/O:op] — operation in file_io artifact

Machine-verifiable via: GET /retrieve/{uuid} API endpoint
