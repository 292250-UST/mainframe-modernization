"""
batch_parser.py
===============
Batch COBOL parser — runs ProLeap on ALL .cbl files in the corpus.

WHY THIS EXISTS:
    D1-01 requires parsing all ~80 COBOL programs and logging
    pass/fail per file. This module orchestrates that batch run,
    combining the copybook preprocessor and ProLeap wrapper.

WHAT IT DOES:
    1. Finds all .cbl/.CBL files in corpus/app/cbl/
    2. For each file:
       a. Runs copybook preprocessor (provenance tracking)
       b. Runs ProLeap parser (paragraph + structure extraction)
       c. Saves Layer 1 JSON artifact to out/artifacts/layer1/
       d. Logs pass/fail/gaps to event log
    3. Saves parse coverage report to out/reports/parse_coverage.json

OUTPUT STRUCTURE:
    out/
      artifacts/
        layer1/
          CBACT01C.json          <- ProLeap parse result
          CBACT01C_provenance.json <- line-level copybook provenance
          COTRN02C.json
          COTRN02C_provenance.json
          ...
      reports/
        parse_coverage.json      <- summary: pass/fail counts + gap list

DOWNSTREAM CONSUMERS:
    - ast_transformer.py   (reads layer1 JSON artifacts)
    - coverage_report.py   (reads parse_coverage.json)
    - run_pipeline.py      (calls run_batch_parse())
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.utils.logger import get_logger, PipelineEventLog
from src.parsers.proleap_wrapper import parse_cobol_file
from src.preprocess.copybook_processor import CopybookProcessor

from src.layers.l1_ast.ast_transformer import ASTTransformer
from src.layers.l2_symbols.symbol_table import SymbolTableBuilder

from src.layers.l2_symbols.paragraph_inventory import ParagraphInventoryBuilder

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import CORPUS_DIR, COPYBOOK_DIR, OUT_DIR



logger = get_logger("parsers.batch_parser")

# ---------------------------------------------------------------------------
# OUTPUT DIRECTORIES
# ---------------------------------------------------------------------------
LAYER1_DIR = OUT_DIR / "artifacts" / "layer1"
REPORTS_DIR = OUT_DIR / "reports"


def find_cobol_files(corpus_dir: Path) -> list[Path]:
    """
    Find all COBOL source files in the corpus directory.

    Handles mixed case extensions (.cbl and .CBL) which both
    exist in the CardDemo corpus.

    Args:
        corpus_dir (Path): Root of the CardDemo corpus (corpus/app/cbl/)

    Returns:
        list[Path]: Sorted list of .cbl file paths found.
    """
    cbl_dir = corpus_dir / "app" / "cbl"
    files = list(cbl_dir.glob("*.cbl")) + list(cbl_dir.glob("*.CBL"))
    files = sorted(set(files))  # deduplicate + sort
    logger.info(f"Found {len(files)} COBOL files in {cbl_dir}")
    return files


def save_layer1_artifact(
    parse_result: dict,
    provenance_summary: dict,
    output_dir: Path
) -> Path:
    """
    Save the Layer 1 JSON artifact for one parsed COBOL program.

    Artifact format:
    {
        'program': 'CBACT01C',
        'status': 'ok',
        'paragraphs': [...],
        'source_file': 'CBACT01C.cbl',
        'provenance_summary': { ... },
        'parsed_at': '2026-05-16T23:00:00'
    }

    Args:
        parse_result (dict):        Output from proleap_wrapper.parse_cobol_file()
        provenance_summary (dict):  Summary from ProvenanceMap.summary()
        output_dir (Path):          Where to save the artifact JSON

    Returns:
        Path: Path to the saved artifact file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    program_name = parse_result.get("program", "UNKNOWN")
    artifact = {
        **parse_result,
        "provenance_summary": provenance_summary,
        "layer": "L1",
        "parsed_at": datetime.now().isoformat(),
    }

    artifact_path = output_dir / f"{program_name}.json"
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.debug(f"Saved Layer 1 artifact: {artifact_path.name}")
    return artifact_path


def run_batch_parse(
    corpus_dir: Optional[Path] = None,
    copybook_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> dict:
    """
    Run ProLeap on ALL COBOL files in the corpus — the D1-01 batch parse.

    For each file:
    - Runs copybook preprocessor
    - Runs ProLeap parser
    - Saves Layer 1 artifact JSON
    - Saves provenance map JSON
    - Logs pass/fail/gaps

    Args:
        corpus_dir (Path):   CardDemo corpus root. Defaults to config.CORPUS_DIR
        copybook_dir (Path): Copybook directory. Defaults to config.COPYBOOK_DIR
        output_dir (Path):   Output root. Defaults to config.OUT_DIR

    Returns:
        dict: Parse coverage summary:
        {
            'total': 44,
            'passed': 40,
            'failed': 4,
            'pass_rate': 90.9,
            'failed_files': ['COTRN02C.cbl', ...],
            'gaps': [ {gap details}, ... ]
        }
    """
    # Apply defaults from config
    corpus_dir   = corpus_dir   or CORPUS_DIR
    copybook_dir = copybook_dir or COPYBOOK_DIR
    output_dir   = output_dir   or OUT_DIR

    layer1_dir  = output_dir / "artifacts" / "layer1"
    reports_dir = output_dir / "reports"
    layer1_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Initialize event log + preprocessor
    event_log   = PipelineEventLog("batch_parse")
    preprocessor = CopybookProcessor(copybook_dir=copybook_dir)

    # Find all COBOL files
    cobol_files = find_cobol_files(corpus_dir)
    if not cobol_files:
        logger.error(f"No COBOL files found in {corpus_dir}/app/cbl/")
        return {}

    logger.info(f"Starting batch parse: {len(cobol_files)} files")
    logger.info("=" * 60)

    # -----------------------------------------------------------------------
    # Main parse loop
    # -----------------------------------------------------------------------
    passed   = []
    failed   = []
    all_gaps = []

    for i, cbl_file in enumerate(cobol_files, 1):
        # Progress display
        pct = round(i / len(cobol_files) * 100)
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\r[{bar}] {pct}% ({i}/{len(cobol_files)}) {cbl_file.name:<30}", end="", flush=True)
        logger.debug(f"[{i}/{len(cobol_files)}] {cbl_file.name}")

        # -------------------------------------------------------------------
        # Step 1: Copybook preprocessing + provenance tracking
        # -------------------------------------------------------------------
        preprocess_result = preprocessor.process(cbl_file)

        # Collect gaps from preprocessing
        if preprocess_result.copybooks_missing:
            for missing in preprocess_result.copybooks_missing:
                all_gaps.append({
                    "file": cbl_file.name,
                    "gap_type": "MISSING_COPYBOOK",
                    "missing": missing,
                    "downstream_impact": [
                        "Layer 1: incomplete AST",
                        "Layer 2: incomplete symbol table",
                        "Layer 3: def-use chains may be broken",
                    ]
                })

        # Save provenance map regardless of success
        if preprocess_result.provenance_map:
            provenance_path = layer1_dir / f"{cbl_file.stem}_provenance.json"
            preprocess_result.provenance_map.save(provenance_path)

        # -------------------------------------------------------------------
        # Step 2: ProLeap parse
        # -------------------------------------------------------------------
        parse_result = parse_cobol_file(
            cbl_file=cbl_file,
            copybook_dir=copybook_dir,
            preprocessed_lines=preprocess_result.preprocessed_lines
        )

        # -------------------------------------------------------------------
        # Step 3: Save Layer 1 artifact
        # -------------------------------------------------------------------
        provenance_summary = (
            preprocess_result.provenance_map.summary()
            if preprocess_result.provenance_map
            else {}
        )

        save_layer1_artifact(
            parse_result=parse_result,
            provenance_summary=provenance_summary,
            output_dir=layer1_dir
        )

        # -------------------------------------------------------------------
        # Step 4: AST transformation (Layer 1 typed nodes)
        # -------------------------------------------------------------------
        if parse_result.get("status") == "ok":
            transformer = ASTTransformer()
            ast_result = transformer.transform(
                parse_result, preprocess_result.provenance_map
            )
            transformer.save(ast_result, layer1_dir)

            # ---------------------------------------------------------------
            # Step 5: Symbol table (Layer 2)
            # ---------------------------------------------------------------
            sym_dir = output_dir / "artifacts" / "layer2"
            sym_builder = SymbolTableBuilder()
            sym_result = sym_builder.build(
                parse_result, preprocess_result.provenance_map
            )
            sym_builder.save(sym_result, sym_dir)

            # ---------------------------------------------------------------
            # Step 6: Paragraph inventory (Layer 2)
            # ---------------------------------------------------------------
            para_builder = ParagraphInventoryBuilder()
            para_result = para_builder.build(
                parse_result, preprocess_result.provenance_map
            )
            para_builder.save(para_result, sym_dir)

        # Save token stream separately — too large for main artifact
        # Hidden channel tokens (comments, col 7) are critical for spec gen
        if "token_stream" in parse_result:
            token_path = layer1_dir / f"{cbl_file.stem}_tokens.json"
            token_artifact = {
                "layer":        "L1",
                "source_file":  cbl_file.name,
                "token_count":  len(parse_result["token_stream"]),
                "hidden_count": sum(1 for t in parse_result["token_stream"] if t["hidden"]),
                "comment_count": sum(1 for t in parse_result["token_stream"]
                                    if t["hidden"] and t["text"].strip().startswith("*")),
                "tokens": parse_result.pop("token_stream")
            }
            with open(token_path, "w", encoding="utf-8") as f:
                json.dump(token_artifact, f, indent=2)
            logger.debug(f"Token stream saved: {token_path.name}")

        

        # -------------------------------------------------------------------
        # Step 4: Log pass/fail
        # -------------------------------------------------------------------
        if parse_result.get("status") == "ok":
            passed.append(cbl_file.name)
            event_log.log_success(
                source_file=cbl_file.name,
                details={
                    "paragraphs": len(parse_result.get("paragraphs", [])),
                    "copybooks_resolved": preprocess_result.copybooks_found,
                    "copybooks_missing": preprocess_result.copybooks_missing,
                    "total_lines": len(preprocess_result.preprocessed_lines),
                }
            )
        else:
            failed.append(cbl_file.name)
            error_msg = parse_result.get("error", "Unknown error")
            event_log.log_failure(
                source_file=cbl_file.name,
                reason=error_msg[:200],
                downstream_impact=[
                    "Layer 1: no AST produced",
                    "Layer 2: no symbol table",
                    "Layer 3: no CFG or def-use chains",
                    "Layer 4: missing from call graph",
                    "Demos: cannot be used as demo target",
                ]
            )
            all_gaps.append({
                "file": cbl_file.name,
                "gap_type": "PARSE_FAILURE",
                "error": error_msg[:200],
                "downstream_impact": [
                    "All downstream layers affected"
                ]
            })

    print()  # newline after progress bar
    logger.info(f"Batch parse complete: {len(passed)} passed, {len(failed)} failed")

    # -----------------------------------------------------------------------
    # Save parse coverage report (Layer 7 honesty artifact)
    # -----------------------------------------------------------------------
    total     = len(cobol_files)
    pass_rate = round(len(passed) / total * 100, 1) if total > 0 else 0.0

    coverage_report = {
        "generated_at":  datetime.now().isoformat(),
        "corpus_dir":    str(corpus_dir),
        "file_type":     "COBOL (.cbl / .CBL)",
        "total":         total,
        "passed":        len(passed),
        "failed":        len(failed),
        "pass_rate":     pass_rate,
        "passed_files":  passed,
        "failed_files":  failed,
        "gaps":          all_gaps,
    }

    coverage_path = reports_dir / "parse_coverage.json"
    with open(coverage_path, "w", encoding="utf-8") as f:
        json.dump(coverage_report, f, indent=2)

    # Save event log
    event_log.save()

    # -----------------------------------------------------------------------
    # Print final summary
    # -----------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info(f"Batch parse complete:")
    logger.info(f"  Total  : {total}")
    logger.info(f"  Passed : {len(passed)} ({pass_rate}%)")
    logger.info(f"  Failed : {len(failed)}")
    logger.info(f"  Gaps   : {len(all_gaps)}")
    logger.info(f"  Report : {coverage_path}")

    if failed:
        logger.warning(f"Failed files: {failed}")

    return coverage_report


if __name__ == "__main__":
    # Allow running directly: python -m src.parsers.batch_parser
    run_batch_parse()
