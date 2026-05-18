## D3-04, D3-05, D3-06 — Out of Scope

Verified by grep on all .cbl files in corpus/app/cbl/:

| Construct | Count | Verdict |
|---|---|---|
| EXEC SQL | 0 | Out of scope — no DB2 in main CardDemo programs |
| EXEC DLI | 0 | Out of scope — IMS only in app-authorization extension |
| EXEC MQ  | 0 | Out of scope — MQ only in app-authorization extension |

All three are documented in out/reports/parse_coverage.json under out_of_scope section.
DB2 DDL exists in corpus/app/app-transaction-type-db2/ but no embedded SQL in COBOL.
