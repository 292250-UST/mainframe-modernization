#!/usr/bin/env python3
"""
run_pipeline.py - One-command pipeline orchestrator
Usage: python run_pipeline.py [--step all|parse|graph|load|api]
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent


def parse_args():
    parser = argparse.ArgumentParser(description='CardDemo Modernization Pipeline')
    parser.add_argument('--corpus', default=str(ROOT / 'corpus'), help='Path to CardDemo corpus')
    parser.add_argument('--out', default=str(ROOT / 'out'), help='Output directory')
    parser.add_argument('--step', choices=['parse', 'graph', 'load', 'api', 'all'], default='all')
    parser.add_argument('--port', default=8000, type=int, help='API port (default: 8000)')
    return parser.parse_args()


def step_parse(args):
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
    logger.info('Step 1: Parse complete')


def step_graph(args):
    logger.info('Step 2: Building graphs...')
    sys.path.insert(0, str(ROOT))
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
    logger.info('Step 2: Graph build complete')


def step_load(args):
    logger.info('Step 3: Loading artifacts into DuckDB...')
    sys.path.insert(0, str(ROOT))
    from src.storage.loader import run_full_load
    run_full_load()

    # Load Day 4 artifacts
    import subprocess
    subprocess.run([sys.executable, 'scripts/load_day4.py'], check=True)
    logger.info('Step 3: DuckDB load complete')


def step_api(args):
    logger.info(f'Step 4: Starting FastAPI server on port {args.port}...')
    import uvicorn
    uvicorn.run(
        'src.api.main:app',
        host='0.0.0.0',
        port=args.port,
        reload=False
    )


def main():
    args = parse_args()
    logger.info('CardDemo Modernization Pipeline starting...')
    logger.info(f'Corpus: {args.corpus}')
    logger.info(f'Output: {args.out}')

    steps = {
        'parse': step_parse,
        'graph': step_graph,
        'load':  step_load,
        'api':   step_api,
    }

    if args.step == 'all':
        step_parse(args)
        step_graph(args)
        step_load(args)
        step_api(args)
    else:
        steps[args.step](args)

    logger.info('Pipeline complete.')


if __name__ == '__main__':
    main()
