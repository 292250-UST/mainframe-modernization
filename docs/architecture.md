# Architecture

## Primary AI Agent
Claude (Anthropic) via claude.ai

## Stack

| Layer | Technology | Purpose |
|---|---|---|
| COBOL Parsing | ProLeap 4.0.0 (Java) | Parse .cbl files into AST/ASG |
| Python Bridge | subprocess + JSON | Call ProLeap from Python |
| Graph Store | DuckDB 1.5.2 | Store all graph tables + nodes |
| API Layer | FastAPI 0.135.3 | REST endpoints over artifact store |
| Graph Algorithms | networkx 3.6.1 | CFG, call graph, def-use chains |
| LLM Integration | Anthropic SDK 0.88.0 | Spec generation + grounding |
| Orchestration | LangGraph 0.4.7 | Agentic pipeline (bonus) |
| Testing | pytest 9.0.3 | Unit + integration + API tests |

## UUID Scheme

Every AST node gets a stable deterministic UUID derived from:
- Source file path (relative to corpus root)
- Line number (start line)
- Node kind (e.g. ParagraphNode, StatementNode)

Generated using SHA-256:

import hashlib

def make_uuid(file_path: str, line: int, node_kind: str) -> str:
    key = f'{file_path}:{line}:{node_kind}'
    return hashlib.sha256(key.encode()).hexdigest()[:32]

Same source = same UUID across every pipeline run.
Verified by UUID regression tests in tests/regression/.

## Pipeline Flow

corpus/ (.cbl .jcl .bms .csd .cpy .asm)
        |
    Parsers (ProLeap + ANTLR4 grammars)
        |
    Layer 1-2 artifacts (AST + symbols) -> out/artifacts/
        |
    Layer 3-4 graphs (CFG, call, file I/O, JCL) -> DuckDB
        |
    Layer 5-7 (rules, resources, quality) -> DuckDB + out/reports/
        |
    FastAPI REST layer -> src/api/
        |
    LLM retrieval + grounding -> src/llm/
        |
    Demos (spec-gen + batch chain) -> out/demo/

## Key Design Rules

1. No raw COBOL source reaches the LLM - structured artifacts only
2. All cross-links between artifacts use UUIDs - never string names
3. Every artifact traces back to a source file + line number
4. Parse failures logged honestly in out/reports/parse_coverage.json