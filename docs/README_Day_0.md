# CardDemo Mainframe Modernization Pipeline

COBOL modernization pipeline for the UST CodeCrafter Championship.  
Parses the [AWS CardDemo corpus](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) using ProLeap and produces structured artifacts for LLM-assisted spec generation and forward engineering.

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

Current `requirements.txt`:
```
antlr4-python3-runtime==4.13.1
```

Verify:
```powershell
python -c "import antlr4; print('antlr4 OK')"
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

ProLeap is a library (not a standalone executable), so a thin Java wrapper is needed that:
- Accepts a `.cbl` file + copybooks directory as arguments
- Calls ProLeap internally
- Outputs JSON to stdout for Python to consume

Create the wrapper folder:
```powershell
mkdir third_party\cobol-parser-wrapper
```

Create `third_party\cobol-parser-wrapper\CobolParserWrapper.java`:

```java
import io.proleap.cobol.asg.metamodel.Program;
import io.proleap.cobol.asg.metamodel.CompilationUnit;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.asg.params.impl.CobolParserParamsImpl;
import io.proleap.cobol.asg.params.CobolParserParams;
import io.proleap.cobol.preprocessor.CobolPreprocessor.CobolSourceFormatEnum;
import java.io.File;
import java.util.Arrays;

public class CobolParserWrapper {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: CobolParserWrapper <file.cbl> <copybooks-dir>");
            System.exit(1);
        }

        File inputFile = new File(args[0]);
        File copybookDir = new File(args[1]);

        CobolParserParams params = new CobolParserParamsImpl();
        params.setCopyBookDirectories(Arrays.asList(copybookDir));
        params.setFormat(CobolSourceFormatEnum.FIXED);

        Program program = new CobolParserRunnerImpl()
            .analyzeFile(inputFile, params);

        for (CompilationUnit cu : program.getCompilationUnits()) {
            System.out.println("{\"program\": \"" + cu.getName() + "\", \"status\": \"ok\"}");
        }
    }
}
```

Compile the wrapper:
```powershell
javac -cp "third_party\proleap-cobol-parser\target\proleap-cobol-parser-4.0.0.jar;third_party\proleap-cobol-parser\target\dependency\*" third_party\cobol-parser-wrapper\CobolParserWrapper.java -d third_party\cobol-parser-wrapper\
```

Verify — you should see `CobolParserWrapper.class`:
```powershell
dir third_party\cobol-parser-wrapper\
```

### Step 6 — Configure paths

Ensure `config.py` at project root contains:

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

### What `tests/test_proleap.py` contains

```python
import subprocess
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.append(str(ROOT))
from config import CORPUS_DIR, PROLEAP_JAR, COPYBOOK_DIR, WRAPPER_DIR

def parse_cobol(cbl_file):
    result = subprocess.run(
        ["java", "-cp",
         f"{PROLEAP_JAR};{ROOT}/third_party/proleap-cobol-parser/target/dependency/*;{WRAPPER_DIR}",
         "CobolParserWrapper",
         str(cbl_file),
         str(COPYBOOK_DIR)],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return json.loads(result.stdout.strip().split('\n')[-1])
    else:
        return {"error": result.stderr.split('\n')[-2]}

if __name__ == "__main__":
    test_file = CORPUS_DIR / "app" / "cbl" / "CBACT01C.cbl"
    result = parse_cobol(test_file)
    print(f"Result: {result}")
```

---

## Project Structure (Day 0 state)

```
mainframe-modernization/
│
├── corpus/                           # AWS CardDemo source (git submodule — pinned SHA)
│   └── app/
│       ├── cbl/                      # ~80 COBOL programs (.cbl)
│       ├── cpy/                      # Copybooks (.cpy)
│       ├── jcl/                      # JCL batch jobs
│       └── bms/                      # BMS screen maps
│
├── third_party/
│   ├── proleap-cobol-parser/         # ProLeap source (git submodule)
│   │   └── target/
│   │       ├── proleap-cobol-parser-4.0.0.jar  # built locally via mvn
│   │       └── dependency/           # Runtime dependencies (mvn dependency:copy)
│   └── cobol-parser-wrapper/         # Thin Java wrapper (written by us)
│       ├── CobolParserWrapper.java
│       └── CobolParserWrapper.class
│
├── tools/
│   └── antlr-4.13.1-complete.jar    # ANTLR4 tool (for JCL/BMS grammars later)
│
├── grammars/                         # ANTLR grammar files (populated Day 1-2)
├── src/                              # Pipeline Python code (populated Day 1+)
├── tests/
│   └── test_proleap.py              # Day 0 smoke test ✓
├── docs/
│   └── README_Day_0.md              # Day 0 setup log
├── out/                              # Generated artifacts (git-ignored)
│
├── config.py                         # All paths — no hardcoding anywhere
├── requirements.txt                  # Python dependencies
└── README.md                         # This file
```

---

## Known Issues

| Issue | Cause | Status |
|---|---|---|
| `COTRN02C.cbl` fails to parse | `COTRN02.cpy` missing from corpus | Known — captured in parse coverage report |
| ProLeap INFO logs in terminal | ProLeap uses SLF4J logging by design | Expected — not errors |
| `pip install maven` does nothing | Maven is not a Python package | Use system installer — see Step prerequisites |

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

## Credits

| Tool | Source | License |
|---|---|---|
| ProLeap COBOL Parser | https://github.com/uwol/proleap-cobol-parser | MIT |
| AWS CardDemo Corpus | https://github.com/aws-samples/aws-mainframe-modernization-carddemo | Apache 2.0 |
| ANTLR4 | https://www.antlr.org | BSD |
| antlr4-python3-runtime | https://pypi.org/project/antlr4-python3-runtime | BSD |
