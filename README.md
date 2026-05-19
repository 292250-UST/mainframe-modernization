**Primary AI Agent:** Claude (Anthropic) via claude.ai

# CardDemo Mainframe Modernization Pipeline

COBOL modernization pipeline for the UST CodeCrafter Championship.  
Parses the [AWS CardDemo corpus](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) using ProLeap and produces structured artifacts for LLM-assisted spec generation and forward engineering.

---

## Parse Coverage

| Source | Files | Parsed | Rate |
|---|---|---|---|
| COBOL (.cbl) | 31 | 30 | 96.8% |
| JCL (.jcl) | 38 | 38 | 100% |
| BMS (.bms) | 17 | 17 | 100% |
| CSD (.csd) | 1 | 1 | 100% |
| ASM (.asm) | 2 | 2 | 100% |
| **Overall** | **89** | **88** | **98.9%** |

---

## Architecture

```
CardDemo Corpus (179 files)
         |
         v
[Copybook Preprocessor]  resolves COPY + provenance tracking
         |
         v
[ProLeap COBOL Parser]   ANTLR4-based, Java subprocess
         |
         v
Layer 1: AST              521 nodes, stable SHA-256 UUIDs
Layer 2: Symbols          6,535 symbols + 491 paragraphs
Layer 3: EXEC CICS        150 statements, 19 verbs
Layer 4: Graphs           Call(57) + File I/O(245) + TxFlow(53) + CFG(761)
Layer 5: Analysis         Move chains(2,779) + Business rules(887)
Layer 6: Resources        BMS(441 fields) + CSD(18 transactions)
Layer 7: Coverage         98.9% parse rate, honest gap reporting
         |
         v
DuckDB (17 tables, all layers queryable)
         |
         v
FastAPI REST (15 endpoints + Swagger UI + CFG Visualizer)
         |
         v
LLM Spec Generation (grounded citations: [LINE] [VAR] [PARA] [COPY])
```

---

## Quick Start

```bash
pip install -r requirements.txt
python run_pipeline.py --step all        # full pipeline
python run_pipeline.py --step api        # API only (port 8000)
```

Swagger UI: http://localhost:8000/docs  
CFG Viewer: http://localhost:8000/cfg/COTRN02C

---

## Prerequisites

Make sure the following are installed before starting:

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Pipeline code |
| Java JDK | 17+ | Required to build + run ProLeap |
| Maven | 3.9+ | Required to build ProLeap from source |
| Git | Any | Clone repos |

### Verify prerequisites

```powershell
python --version    # Python 3.11+
java --version      # openjdk 17+
javac --version     # javac 17+  (confirms JDK not just JRE)
mvn --version       # Apache Maven 3.9+
git --version
```

---

## Installation Guide

### Step 1 — Clone this repo

```powershell
git clone <YOUR_REPO_URL> mainframe-modernization
cd mainframe-modernization
```

### Step 2 — Clone the CardDemo corpus

```powershell
git submodule add https://github.com/aws-samples/aws-mainframe-modernization-carddemo corpus
```

When cloning this repo fresh, use:
```powershell
git clone --recurse-submodules <YOUR_REPO_URL> mainframe-modernization
```

Verify:
```powershell
dir corpus\app\cbl\
# Should show CBACT01C.cbl, COTRN02C.cbl, etc.
```

### Step 3 — Set up Python virtual environment

```powershell
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
```

Verify:
```powershell
python -c "import duckdb, fastapi, openai; print('deps OK')"
```

### Step 4 — Clone and build ProLeap COBOL parser

ProLeap is a Java COBOL parser. It is added as a git submodule and built once from source using Maven.

```powershell
# Add ProLeap as submodule
git submodule add https://github.com/uwol/proleap-cobol-parser third_party/proleap-cobol-parser

# Build the JAR (requires JDK 17 + Maven)
cd third_party\proleap-cobol-parser
mvn clean package -DskipTests

# Copy runtime dependencies
mvn dependency:copy-dependencies -DoutputDirectory=target\dependency

cd ..\..
```

> Note: The `target/` folder (built JAR + dependencies) is NOT tracked by the submodule.
> You must run the Maven build locally after cloning.

Verify the JAR was built:
```powershell
dir third_party\proleap-cobol-parser\target\proleap-cobol-parser-4.0.0.jar
```

### Step 5 — Build the Java wrapper

ProLeap is a library (not a standalone executable), so a thin Java wrapper accepts a `.cbl` file + copybooks directory, calls ProLeap, and outputs JSON to stdout for Python to consume.

Compile the wrapper:
```powershell
javac -cp "third_party\proleap-cobol-parser\target\proleap-cobol-parser-4.0.0.jar;third_party\proleap-cobol-parser\target\dependency\*" third_party\cobol-parser-wrapper\CobolParserWrapper.java -d third_party\cobol-parser-wrapper\
```

Verify — you should see `CobolParserWrapper.class`:
```powershell
dir third_party\cobol-parser-wrapper\
```

### Step 6 — Configure paths

Ensure `config.py` at project root contains correct paths:

```python
from pathlib import Path

ROOT = Path(__file__).parent

PROLEAP_JAR  = ROOT / "third_party" / "proleap-cobol-parser" / "target" / "proleap-cobol-parser-4.0.0.jar"
WRAPPER_DIR  = ROOT / "third_party" / "cobol-parser-wrapper"
CORPUS_DIR   = ROOT / "corpus"
COPYBOOK_DIR = ROOT / "corpus" / "app" / "cpy"
OUT_DIR      = ROOT / "out"
```

> **Important:** Never hardcode paths anywhere in the pipeline. Always import from `config.py`.

### Step 7 — Set LLM API key

```powershell
$env:NVIDIA_API_KEY = "nvapi-xxxx"   # Windows
# export NVIDIA_API_KEY="nvapi-xxxx" # Mac/Linux
```

---

## Smoke Test

Run the smoke test to verify the full Python → Java → ProLeap → JSON pipeline:

```powershell
python tests/test_proleap.py
```

Expected output:
```
Result: {'program': 'CBACT01C', 'status': 'ok'}
```

> Note: ProLeap INFO logs will appear in the terminal — these are normal, not errors.

---

## Running the Pipeline

```powershell
# Run all steps end-to-end
python run_pipeline.py --step all

# Or run individual steps
python run_pipeline.py --step parse   # Parse all source files
python run_pipeline.py --step graph   # Build all graphs
python run_pipeline.py --step load    # Load into DuckDB
python run_pipeline.py --step api     # Start REST API (port 8000)
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| GET /health | Health check |
| GET /coverage | Parse coverage report |
| GET /program/{name} | Program metadata + UUID |
| GET /paragraph/{uuid} | Paragraph AST |
| GET /dataitem/{uuid} | Data definition |
| GET /callers/{name} | Call graph — who calls this |
| GET /callees/{name} | Call graph — what this calls |
| GET /fileaccesses/{name} | File I/O operations |
| GET /transactionflow/{transid} | CICS navigation graph |
| GET /jobchain/{name} | JCL dependency chain |
| GET /copybookconsumers/{name} | Copybook usage |
| GET /retrieve/{uuid} | Artifact slice retrieval |
| GET /businessrules/{name} | IF/EVALUATE rule catalog |
| GET /controlflow/{uuid} | CFG edges (JSON) |
| **GET /cfg/{name}** | **Interactive CFG visualizer (HTML, live from DuckDB)** |

---

## Key Metrics

| Metric | Value |
|---|---|
| Total symbols | 6,535 |
| Symbols from copybooks | 1,797 (27.5%) |
| Total paragraphs | 491 |
| Total statements | 5,094 |
| EXEC CICS statements | 150 (19 verbs) |
| MOVE statements | 2,779 |
| Call graph edges | 57 (31 CALL + 26 XCTL) |
| CFG edges | 761 |
| File I/O operations | 245 |
| Transaction flow edges | 53 |
| Business rules | 887 (774 IF + 113 EVALUATE) |
| DuckDB tables | 17 |

---

## Demo A — Online Program (COTRN02C)

Transaction Add screen — complexity=55, 18 paragraphs, 1,160 lines.

```bash
python -m src.llm.spec_generator COTRN02C
# Output: out/demo/COTRN02C_spec.txt
```

CFG visualization: http://localhost:8000/cfg/COTRN02C

Sample grounded claim from generated spec:
> "COTRN02C receives user input from COTRN2A via CICS RECEIVE [LINE:539]
> and validates card number [VAR:XREF-CARD-NUM] against XREF file [LINE:576]"

---

## Demo B — Batch Chain (POSTTRAN → INTCALC → CREASTMT)

```bash
python -m src.llm.spec_generator CBTRN02C  # POSTTRAN
python -m src.llm.spec_generator CBACT04C  # INTCALC
python -m src.llm.spec_generator CBSTM03A  # CREASTMT
# Output: out/demo/*_spec.txt
```

End-to-end data lineage:
```
DALYTRAN input
  -> CBTRN02C validates + posts -> TCATBALF updated
  -> CBACT04C computes interest -> TRANSACT updated
  -> CBSTM03A generates statements -> STATEMNT.PS + HTML
```

See: docs/demo_batch_chain.md

---

## Known Gaps (Honest Reporting)

| Gap | Reason | Impact |
|---|---|---|
| COACTUPC.cbl | Template placeholders (TESTVAR1) | No AST — documented in coverage report |
| EXEC SQL/DLI/MQ | 0 occurrences in corpus | Tables empty — verified by grep |
| JCL ANTLR grammar | Regex chosen (0 PROC/IF/INCLUDE in corpus) | 100% JCL coverage achieved |
| BMS copybook stubs (17) | Generated from .bms source | Programs parse correctly |
| DFHAID / DFHBMSCA | IBM standard stubs from documentation | High accuracy |

---

## Repository Structure

```
mainframe-modernization/
│
├── corpus/                      # AWS CardDemo source (git submodule — pinned SHA)
│   └── app/
│       ├── cbl/                 # 31 COBOL programs
│       ├── cpy/                 # Copybooks (+ generated stubs)
│       ├── jcl/                 # 38 JCL batch jobs
│       ├── bms/                 # 17 BMS screen maps
│       ├── csd/                 # CICS CSD file
│       └── asm/                 # 2 Assembler stubs
│
├── third_party/
│   ├── proleap-cobol-parser/    # ProLeap source (git submodule)
│   │   └── target/
│   │       ├── proleap-cobol-parser-4.0.0.jar  # built locally via mvn
│   │       └── dependency/      # Runtime dependencies
│   └── cobol-parser-wrapper/    # Thin Java wrapper (written by us)
│       ├── CobolParserWrapper.java
│       └── CobolParserWrapper.class
│
├── tools/
│   └── antlr-4.13.1-complete.jar
│
├── src/
│   ├── parsers/                 # COBOL, JCL, BMS, CSD, ASM parsers
│   ├── preprocess/              # Copybook resolver + provenance tracker
│   ├── layers/                  # AST, symbols, call graph, CFG, tx flow
│   ├── storage/                 # DuckDB schema + loader
│   ├── api/                     # FastAPI REST layer + CFG visualizer
│   ├── llm/                     # Artifact retrieval + spec generator
│   └── coverage_report.py
│
├── tests/
│   ├── test_proleap.py          # Smoke test
│   └── regression/              # UUID stability tests
│
├── out/                         # Generated artifacts (git-ignored)
│   ├── artifacts/               # JSON artifacts by layer
│   ├── graph/                   # artifacts.duckdb
│   ├── demo/                    # Generated specs
│   └── reports/                 # Coverage report
│
├── docs/                        # Architecture, READMEs, demos
├── scripts/                     # Utility + debug scripts
├── config.py                    # All paths — no hardcoding anywhere
├── requirements.txt
├── run_pipeline.py              # One-command pipeline orchestrator
└── README.md
```

---

## Tech Stack

| Component | Technology |
|---|---|
| COBOL Parser | ProLeap 4.0.0 (ANTLR4, Java) |
| Storage | DuckDB 1.5.2 |
| API | FastAPI 0.135.3 + uvicorn |
| LLM | NVIDIA API (qwen3-coder-480b) via OpenAI SDK |
| CFG Visualizer | SVG/D3 (self-contained HTML, live from DuckDB) |
| Python | 3.12 |
| Graphs | networkx 3.6.1 |

---

## Java + Maven Installation (Windows)

If `mvn --version` is not recognised:

**Install JDK 17:**
1. Download from https://adoptium.net/temurin/releases/?version=17
2. Select Windows / x64 / JDK / 17 — download `.msi`
3. Run installer — PATH is set automatically

**Install Maven:**
1. Download from https://maven.apache.org/download.cgi
2. Download `apache-maven-3.9.x-bin.zip`
3. Unzip to `C:\maven`
4. Add `C:\maven\bin` to system PATH:

```powershell
# Run as Administrator
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\maven\bin", "Machine")
```

5. Restart terminal and verify: `mvn --version`

---

## Known Issues

| Issue | Cause | Status |
|---|---|---|
| `COACTUPC.cbl` fails to parse | Template placeholders (TESTVAR1) | Known — in coverage report |
| ProLeap INFO logs in terminal | ProLeap uses SLF4J logging by design | Expected — not errors |
| `pip install maven` does nothing | Maven is not a Python package | Use system installer above |

---

## Credits

| Tool | Source | License |
|---|---|---|
| ProLeap COBOL Parser | https://github.com/uwol/proleap-cobol-parser | MIT |
| AWS CardDemo Corpus | https://github.com/aws-samples/aws-mainframe-modernization-carddemo | Apache 2.0 |
| ANTLR4 | https://www.antlr.org | BSD |
| antlr4-python3-runtime | https://pypi.org/project/antlr4-python3-runtime | BSD |
| DuckDB | https://duckdb.org | MIT |
| FastAPI | https://fastapi.tiangolo.com | MIT |
