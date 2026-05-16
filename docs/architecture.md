@"
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

Every AST node gets a stable, deterministic UUID derived from:

- Source file path (relative to corpus root)
- Line number (start line)
- Node kind (e.g. ParagraphNode, StatementNode)

Generated using SHA-256:

```python