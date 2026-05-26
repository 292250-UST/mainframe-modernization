#!/usr/bin/env python3
"""
run_pipeline.py - One-command pipeline orchestrator
Usage: python run_pipeline.py [--step all|parse|graph|load|api]
"""
import argparse
import logging
import sys
from pathlib import Path
from config import OUT_DIR, CORPUS_DIR

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
# Prevent duplicate log handlers from multiple imports
logging.root.handlers = logging.root.handlers[:1]
logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent


def parse_args():
    parser = argparse.ArgumentParser(description='CardDemo Modernization Pipeline')
    parser.add_argument('--corpus', default=str(ROOT / 'corpus'), help='Path to CardDemo corpus')
    parser.add_argument('--out', default=str(ROOT / 'out'), help='Output directory')
    parser.add_argument('--step', choices=['parse','graph','load','ir','spec','api','all'])
    parser.add_argument('--port', default=8000, type=int, help='API port (default: 8000)')
    return parser.parse_args()


def step_parse(args):
    import subprocess
    logger.info('Step 1: Parsing COBOL/JCL/BMS/CSD/ASM files...')
    sys.path.insert(0, str(ROOT))
    from src.parsers.batch_parser import run_batch_parse
    from src.parsers.jcl_parser import JCLParser
    from src.parsers.bms_parser import BMSParser
    from src.parsers.csd_parser import run as run_csd
    from src.parsers.assembler_stub_recognizer import run as run_asm
    from src.layers.l4_system_graphs.jcl_graph import build_jcl_graph, save_jcl_graph
    from config import CORPUS_DIR

    # COBOL
    run_batch_parse()
    # JCL
    jcl_parser = JCLParser()
    jcl_results = jcl_parser.parse_all(CORPUS_DIR / 'app' / 'jcl')
    jcl_parser.save_results(jcl_results)
    graph = build_jcl_graph(jcl_results)
    save_jcl_graph(graph)
    # BMS
    bms_parser = BMSParser()
    bms_results = bms_parser.parse_all(CORPUS_DIR / 'app' / 'bms')
    bms_parser.save(bms_results)
    # CSD
    run_csd()
    # ASM
    run_asm()

    # --- Extension module COBOL ---
    subprocess.run([sys.executable, "scripts/parse_ext_cobol.py"], check=True)
    # --- Extension JCL + BMS + CSD ---
    from src.parsers.bms_parser import BMSParser
    from src.parsers.csd_parser import CSDParser
    EXT_DIR = CORPUS_DIR / "app" / "app-authorization-ims-db2-mq"
    bms = BMSParser()
    bms_results = bms.parse_all(EXT_DIR / "bms")
    bms.save(bms_results, OUT_DIR / "artifacts" / "layer6_ext")
    csd = CSDParser()
    for f in list((EXT_DIR / "csd").glob("*.csd")) + list((EXT_DIR / "csd").glob("*.CSD")):
        result = csd.parse(f)
        csd.save(result, OUT_DIR / "artifacts" / "layer6_ext")
    logger.info("Extension module parsed")

    logger.info('Step 1: Parse complete')


def step_graph(args):
    logger.info("Step 2: Building all graphs and extractors...")
    sys.path.insert(0, str(ROOT))
    from config import OUT_DIR
    # Ensure DB directory exists for extractors that write to DuckDB
    (OUT_DIR / "graph").mkdir(parents=True, exist_ok=True)
    # --- Call graph + transaction flow + file I/O ---
    from src.layers.l4_system_graphs.call_graph import build_call_graph
    from src.layers.l4_system_graphs.transaction_flow import build_transaction_flow
    from src.parsers.file_io_extractor import run as run_file_io
    from src.parsers.exec_cics_extractor import run as run_cics
    from src.parsers.move_chain_analyzer import run as run_moves
    build_call_graph()
    run_file_io()
    build_transaction_flow()
    run_cics()
    run_moves()

    # --- CFG builder (main corpus) ---
    from src.layers.l4_system_graphs.cfg_builder import run as run_cfg
    run_cfg()

    # --- Business rules ---
    from src.parsers.business_rules_extractor import run as run_br
    run_br()

    # --- EXEC DLI (extension module) ---
    from src.parsers.exec_dli_extractor import run as run_dli
    run_dli()

    # --- JCL graph ---
    from src.parsers.jcl_parser import JCLParser
    from src.layers.l4_system_graphs.jcl_graph import build_jcl_graph, save_jcl_graph
    from config import CORPUS_DIR
    jcl_parser = JCLParser()
    jcl_results = jcl_parser.parse_all(CORPUS_DIR / "app" / "jcl")
    graph = build_jcl_graph(jcl_results)
    save_jcl_graph(graph)

    # --- DB2 DDL ---
    from src.parsers.db2_ddl_parser import run as run_db2
    run_db2()

    # --- IMS DBD ---
    from src.parsers.ims_dbd_parser import run as run_ims
    run_ims()

    # --- VSAM schemas ---
    import subprocess
    subprocess.run([sys.executable, "scripts/build_vsam_schemas.py"], check=True)
    subprocess.run([sys.executable, "scripts/enrich_vsam2.py"], check=True)

    # --- GDG registry ---
    subprocess.run([sys.executable, "scripts/build_gdg_registry.py"], check=True)

    # --- MQ extraction ---
    subprocess.run([sys.executable, "scripts/load_dli_mq.py"], check=True)

    # --- Extension CFG ---
    subprocess.run([sys.executable, "scripts/build_ext_cfg.py"], check=True)

    # --- Def-use chains ---
    subprocess.run([sys.executable, "scripts/build_def_use.py"], check=True)

    # --- Coverage report ---
    from src.coverage_report import generate_coverage_report
    generate_coverage_report()

    logger.info("Step 2: All graphs and extractors complete")

def step_load(args):
    logger.info("Step 3: Loading artifacts into DuckDB...")
    sys.path.insert(0, str(ROOT))
    from config import OUT_DIR

    # Drop existing DB for clean rebuild
    db_path = OUT_DIR / "graph" / "artifacts.duckdb"
    if db_path.exists():
        db_path.unlink()
        logger.info("Dropped existing DuckDB — rebuilding from scratch")

    from src.storage.loader import run_full_load
    run_full_load()
    logger.info("Step 3: DuckDB load complete")

def step_spec(args):
    """Pre-generate specs for all programs using LLM."""
    import os
    logger.info("Step 4: Pre-generating specs for all programs...")

    nvidia_key = os.environ.get("NVIDIA_API_KEY", "")
    if not nvidia_key:
        logger.warning("NVIDIA_API_KEY not set — skipping spec generation")
        logger.warning("Set NVIDIA_API_KEY and run: python run_pipeline.py --step spec")
        return

    sys.path.insert(0, str(ROOT))
    from src.llm.spec_generator import generate_program_spec
    from src.storage.loader import get_connection
    from config import OUT_DIR

    # Get all programs from DuckDB
    conn = get_connection()
    programs = conn.execute("""
        SELECT payload_json->>'program_name' as name, source_file
        FROM nodes
        WHERE kind = 'ProgramNode'
        ORDER BY name
    """).fetchall()
    conn.close()

    demo_dir = OUT_DIR / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    passed = 0
    failed = 0
    skipped = 0

    logger.info(f"Generating specs for {len(programs)} programs...")

    for prog_name, source_file in programs:
        if not prog_name:
            continue

        # Check if already cached
        cached = demo_dir / f"{prog_name.upper()}_spec.json"
        if cached.exists():
            logger.info(f"  CACHED: {prog_name}")
            skipped += 1
            continue

        try:
            result = generate_program_spec(prog_name.upper(), output_dir=demo_dir)
            if "error" in result:
                logger.warning(f"  SKIP: {prog_name} — {result['error']}")
                skipped += 1
            else:
                logger.info(f"  DONE: {prog_name} ({result.get('tokens_used',0)} tokens)")
                passed += 1
        except Exception as e:
            logger.error(f"  FAIL: {prog_name} — {e}")
            failed += 1

    logger.info(f"Spec generation complete: {passed} generated, {skipped} cached, {failed} failed")

def step_api(args):
    logger.info(f'Step 4: Starting FastAPI server on port {args.port}...')
    import uvicorn
    uvicorn.run(
        'src.api.main:app',
        host='0.0.0.0',
        port=args.port,
        reload=False
    )

def step_ir(args):
    """Build canonical IR for all programs."""
    logger.info("Step: Building canonical IR (Layer 8)...")
    sys.path.insert(0, str(ROOT))
    from src.layers.l8_ir.canonical_ir import build_all_ir
    summary = build_all_ir()
    logger.info(f"IR built for {summary['total_programs']} programs across {len(summary['seams'])} seams")

def main():
    args = parse_args()
    logger.info('CardDemo Modernization Pipeline starting...')
    logger.info(f'Corpus: {args.corpus}')
    logger.info(f'Output: {args.out}')

    if args.step == 'all':
        step_parse(args)
        step_graph(args)
        step_load(args)
        step_ir(args)
        step_spec(args)
        step_api(args)
    else:
        steps = {
            'parse': step_parse,
            'graph': step_graph,
            'load':  step_load,
            'ir':    step_ir,
            'spec':  step_spec,
            'api':   step_api,
        }
        steps[args.step](args)

    logger.info('Pipeline complete.')


if __name__ == '__main__':
    main()
