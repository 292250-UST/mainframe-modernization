"""
test_uuid_stability.py
======================
UUID regression test — verifies UUIDs are stable across pipeline runs.

WHY THIS EXISTS:
    The brief requires stable UUIDs (§8):
    "Regenerating must produce the same UUIDs for the same source."

    If UUIDs change between runs, all cross-links in the graph database
    become invalid — breaking the entire artifact contract.

    This test runs the parser twice on the same file and asserts
    that every UUID produced is identical both times.
"""

import pytest
from pathlib import Path
from src.layers.l1_ast.ast_transformer import ASTTransformer
from src.parsers.proleap_wrapper import parse_cobol_file
from src.preprocess.copybook_processor import CopybookProcessor
from src.preprocess.copybook_cache import clear_cache

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import CORPUS_DIR, COPYBOOK_DIR

TEST_FILE = CORPUS_DIR / "app" / "cbl" / "CBACT01C.cbl"


def run_pipeline(cbl_file: Path) -> dict:
    """Run full parse + transform pipeline on one file."""
    clear_cache()  # ensure fresh cache each run
    processor = CopybookProcessor(copybook_dir=COPYBOOK_DIR)
    preprocess = processor.process(cbl_file)
    parse_result = parse_cobol_file(cbl_file)
    transformer = ASTTransformer()
    return transformer.transform(parse_result, preprocess.provenance_map)


def test_program_uuid_stable():
    """ProgramNode UUID must be identical across two pipeline runs."""
    result1 = run_pipeline(TEST_FILE)
    result2 = run_pipeline(TEST_FILE)
    assert result1["program_node"].uuid == result2["program_node"].uuid, \
        f"Program UUID changed between runs: {result1['program_node'].uuid} != {result2['program_node'].uuid}"


def test_paragraph_uuids_stable():
    """All ParagraphNode UUIDs must be identical across two pipeline runs."""
    result1 = run_pipeline(TEST_FILE)
    result2 = run_pipeline(TEST_FILE)

    uuids1 = [n.uuid for n in result1["paragraph_nodes"]]
    uuids2 = [n.uuid for n in result2["paragraph_nodes"]]

    assert uuids1 == uuids2, \
        f"Paragraph UUIDs changed between runs:\nRun 1: {uuids1}\nRun 2: {uuids2}"


def test_paragraph_count_stable():
    """Paragraph count must be identical across two pipeline runs."""
    result1 = run_pipeline(TEST_FILE)
    result2 = run_pipeline(TEST_FILE)
    assert result1["node_count"] == result2["node_count"], \
        f"Node count changed: {result1['node_count']} != {result2['node_count']}"


def test_uuid_format():
    """UUIDs must be 32-character hex strings."""
    result = run_pipeline(TEST_FILE)
    uuid = result["program_node"].uuid
    assert len(uuid) == 32, f"UUID wrong length: {len(uuid)}"
    assert all(c in "0123456789abcdef" for c in uuid), \
        f"UUID contains non-hex characters: {uuid}"
