# Day 1 Log — Saturday May 17, 2026

## Summary
Batch COBOL parsing pipeline operational. 96.8% pass rate on first run.

## Accomplished

### D1-01 — Batch COBOL Parse ✅
- Ran ProLeap on all 31 COBOL files in corpus/app/cbl/
- Final result: 30/31 passing (96.8%)
- Only failure: COACTUPC.cbl — contains template placeholders (TESTVAR1)
  not valid COBOL — documented as known gap

### D1-06 — copybook_processor.py ✅
- Resolves COPY statements including quoted syntax (COPY 'CSUTLDWY')
- Handles multi-line COPY statements
- Fixed false positive detection of COPY-LAST-TRAN-DATA (paragraph name)
- Logs all missing copybooks with downstream impact

### D1-07 — provenance_tracker.py ✅
- Tracks every expanded line back to origin file + line number
- Tracks REPLACING substitutions per line
- Saves provenance_map.json alongside each Layer 1 artifact

### D1-08 — copybook_cache.py ✅
- LRU cache (maxsize=256) — each copybook read once per run
- Handles mixed case extensions (.cpy/.CPY)
- Cache hits/misses logged for diagnostics

### Architecture Decision: Preprocess-Then-Parse ✅
- Key fix: Python preprocessor runs BEFORE ProLeap
- Preprocessed source written to temp file
- ProLeap receives flat source with all COPYs resolved
- This solved the quoted COPY syntax issue and missing copybook failures
- Improved pass rate from 45.2% to 96.8% in one change

## Stubs Created
- corpus/app/cpy/DFHAID.cpy     — IBM CICS attention identifiers
- corpus/app/cpy/DFHBMSCA.cpy   — IBM CICS BMS attributes
- corpus/app/cpy/COTRN02.cpy    — Transaction Add screen map
- corpus/app/cpy/COACTUP.cpy    — Account Update screen map
- corpus/app/cpy/COACTVW.cpy    — Account View screen map
- corpus/app/cpy/COADM01.cpy    — Admin screen map
- corpus/app/cpy/COBIL00.cpy    — Bill Payment screen map
- corpus/app/cpy/COCRDLI.cpy    — Credit Card List screen map
- corpus/app/cpy/COCRDSL.cpy    — Credit Card Select screen map
- corpus/app/cpy/COCRDUP.cpy    — Credit Card Update screen map
- corpus/app/cpy/COMEN01.cpy    — Main Menu screen map
- corpus/app/cpy/CORPT00.cpy    — Report screen map
- corpus/app/cpy/COSGN00.cpy    — Sign-on screen map
- corpus/app/cpy/COTRN00.cpy    — Transaction List screen map
- corpus/app/cpy/COTRN01.cpy    — Transaction View screen map
- corpus/app/cpy/COUSR00.cpy    — User List screen map
- corpus/app/cpy/COUSR01.cpy    — User Add screen map
- corpus/app/cpy/COUSR02.cpy    — User Update screen map
- corpus/app/cpy/COUSR03.cpy    — User Delete screen map
- corpus/app/cpy/CSUTLDWY.cpy   — Generic date edit variables
- corpus/app/cpy/CSSTRPFY.cpy   — Common PFKey storage code

## Known Gaps
- COACTUPC.cbl: template code with (TESTVAR1) placeholders — not parseable
- BOM characters in PowerShell-generated stubs — fixed via fix_bom.py

## Files Created
- src/utils/logger.py
- src/preprocess/copybook_cache.py
- src/preprocess/provenance_tracker.py
- src/preprocess/copybook_processor.py
- src/parsers/proleap_wrapper.py
- src/parsers/batch_parser.py
- scripts/generate_bms_stubs.py

## Output Artifacts
- out/artifacts/layer1/*.json         — 30 program artifacts
- out/artifacts/layer1/*_provenance.json — 31 provenance maps
- out/reports/parse_coverage.json     — 96.8% pass rate
- out/logs/batch_parse.json           — detailed event log

## Remaining Day 1 Tasks
- D1-02: ast_node.py — typed AST node dataclasses
- D1-03: ast_transformer.py — ProLeap output to clean AST
- D1-09: UUID regression test
- D1-10: Symbol table for CBACT01C
- D1-11: Data dictionary for CBACT01C
