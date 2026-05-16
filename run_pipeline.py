#!/usr/bin/env python3
"""
run_pipeline.py - One-command pipeline orchestrator
Usage: python run_pipeline.py
"""
import argparse
import logging
import sys
from pathlib import Path

# Setup logging
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
    return parser.parse_args()


def step_parse(args):
    logger.info('Step 1: Parsing COBOL/JCL/BMS/CSD files...')
    # TODO Day 1: implement batch parse
    logger.info('Step 1: STUB - not yet implemented')


def step_graph(args):
    logger.info('Step 2: Building graphs (CFG, call, file I/O, JCL)...')
    # TODO Day 4-5: implement graph builders
    logger.info('Step 2: STUB - not yet implemented')


def step_load(args):
    logger.info('Step 3: Loading artifacts into DuckDB...')
    # TODO Day 4-5: implement DB loader
    logger.info('Step 3: STUB - not yet implemented')


def step_api(args):
    logger.info('Step 4: Starting FastAPI server...')
    # TODO Day 6: implement API
    logger.info('Step 4: STUB - not yet implemented')


def main():
    args = parse_args()
    logger.info('CardDemo Modernization Pipeline starting...')
    logger.info(f'Corpus: {args.corpus}')
    logger.info(f'Output: {args.out}')

    steps = {
        'parse': step_parse,
        'graph': step_graph,
        'load': step_load,
        'api': step_api,
    }

    if args.step == 'all':
        for name, fn in steps.items():
            fn(args)
    else:
        steps[args.step](args)

    logger.info('Pipeline complete.')


if __name__ == '__main__':
    main()