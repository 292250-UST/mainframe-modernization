"""
jcl_parser.py
=============
Regex-based JCL parser for the CardDemo modernization pipeline.

WHY REGEX NOT ANTLR:
    CardDemo JCL corpus contains 0 PROC, 0 IF, 0 INCLUDE statements
    (verified by check_jcl_constructs.py). Regex covers 95%+ of actual
    constructs present. Documented in docs/architecture.md as an
    intentional engineering decision.

WHAT IT EXTRACTS:
    - JOB statement: job name
    - EXEC statement: step name, program name, PARM
    - DD statements: dd name, DSN, DISP, STEPLIB
    - Continuation lines (// in cols 1-2, blank name field)
    - Comments (//*) skipped
    - Inline data (*) skipped

OUTPUT FORMAT:
    {
        "job_name": "POSTTRAN",
        "source_file": "POSTTRAN.jcl",
        "steps": [
            {
                "step_name": "STEP15",
                "program": "CBTRN02C",
                "parm": "",
                "steplib": "AWS.M2.CARDDEMO.LOADLIB",
                "datasets": [
                    {
                        "dd_name": "TRANFILE",
                        "dsn": "AWS.M2.CARDDEMO.TRANSACT.VSAM.KSDS",
                        "disposition": "SHR"
                    }
                ]
            }
        ]
    }

DOWNSTREAM CONSUMERS:
    - loader.py      (loads jcl_job + jcl_dependency tables)
    - jcl_graph.py   (builds job dependency graph — Day 5)
    - batch_chain demo (POSTTRAN->INTCALC->CREASTMT)
"""

import re
import json
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger, PipelineEventLog

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("parsers.jcl_parser")

# ---------------------------------------------------------------------------
# REGEX PATTERNS
# ---------------------------------------------------------------------------

# JOB statement: //JOBNAME JOB ...
# Name in columns 3-10 (up to 8 chars), then JOB keyword
JOB_PATTERN = re.compile(
    r'^//([A-Z0-9@#$]{1,8})\s+JOB\s+',
    re.IGNORECASE
)

# EXEC statement: //STEPNAME EXEC PGM=program or EXEC procname
EXEC_PATTERN = re.compile(
    r'^//([A-Z0-9@#$]{1,8})\s+EXEC\s+(?:PGM=([A-Z0-9@#$]{1,8}))?',
    re.IGNORECASE
)

# PARM= extraction from EXEC statement
PARM_PATTERN = re.compile(
    r'PARM=([^\s,]+)',
    re.IGNORECASE
)

# DD statement: //DDNAME DD ...
DD_PATTERN = re.compile(
    r'^//([A-Z0-9@#$]{1,8})\s+DD\s+',
    re.IGNORECASE
)

# DSN= extraction
DSN_PATTERN = re.compile(
    r'DSN=([^\s,]+)',
    re.IGNORECASE
)

# DISP= extraction — handles DISP=SHR, DISP=(NEW,CATLG,DELETE), DISP=(MOD,...)
DISP_PATTERN = re.compile(
    r'DISP=(?:\(([^)]+)\)|([A-Z]+))',
    re.IGNORECASE
)

# Continuation line: // followed by spaces (no name in cols 3-10)
CONTINUATION_PATTERN = re.compile(r'^//\s{1,}')

# Comment line: //*
COMMENT_PATTERN = re.compile(r'^//\*')

# Inline data delimiter: /*
INLINE_END_PATTERN = re.compile(r'^/\*')

# In-stream data start: DD *
INSTREAM_PATTERN = re.compile(r'DD\s+\*\s*$', re.IGNORECASE)


def _extract_disp(text: str) -> str:
    """
    Extract the primary disposition from a DISP= clause.

    DISP=SHR              → 'SHR'
    DISP=(NEW,CATLG,...)  → 'NEW'
    DISP=(MOD,KEEP)       → 'MOD'
    DISP=(OLD,DELETE)     → 'OLD'

    Args:
        text: Raw JCL text containing DISP=

    Returns:
        str: Primary disposition or 'UNKNOWN'
    """
    match = DISP_PATTERN.search(text)
    if not match:
        return "UNKNOWN"

    if match.group(1):
        # Parenthesized: take first value
        return match.group(1).split(",")[0].strip().upper()
    elif match.group(2):
        # Simple: SHR, OLD, etc.
        return match.group(2).strip().upper()

    return "UNKNOWN"


def _extract_dsn(text: str) -> Optional[str]:
    """
    Extract dataset name from DSN= clause.

    Handles:
        DSN=AWS.M2.CARDDEMO.ACCTDATA.VSAM.KSDS
        DSN=AWS.M2.CARDDEMO.DALYREJS(+1)   ← GDG reference
        DSN=&&TEMPFILE                      ← temporary dataset

    Args:
        text: Raw JCL text

    Returns:
        str: Dataset name or None
    """
    match = DSN_PATTERN.search(text)
    if not match:
        return None
    dsn = match.group(1).strip()
    # Remove trailing comma or whitespace
    dsn = dsn.rstrip(",")
    return dsn


class JCLParser:
    """
    Parses JCL files into structured job/step/dataset records.

    Handles:
    - JOB, EXEC, DD statements
    - Continuation lines (// + spaces)
    - STEPLIB detection
    - DSN and DISP extraction
    - In-stream data (DD *) skipping
    - Comment lines (//*) skipping

    Usage:
        parser = JCLParser()
        result = parser.parse(Path("corpus/app/jcl/POSTTRAN.jcl"))
        print(result["job_name"])  # POSTTRAN
        print(result["steps"][0]["program"])  # CBTRN02C
    """

    def __init__(self):
        self.event_log = PipelineEventLog("jcl_parser")

    def parse(self, jcl_file: Path) -> dict:
        """
        Parse a JCL file into structured records.

        Args:
            jcl_file: Path to .jcl file

        Returns:
            dict with job_name, source_file, steps[]
        """
        logger.info(f"Parsing JCL: {jcl_file.name}")

        try:
            raw = jcl_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Cannot read {jcl_file.name}: {e}")
            return {"job_name": jcl_file.stem, "source_file": jcl_file.name,
                    "steps": [], "status": "error", "error": str(e)}

        # Join continuation lines
        lines = self._join_continuations(raw.splitlines())

        job_name = jcl_file.stem.upper()
        steps    = []
        current_step = None
        current_dd   = None
        in_instream  = False

        for line in lines:
            # Skip comments
            if COMMENT_PATTERN.match(line):
                continue

            # End of in-stream data
            if in_instream:
                if INLINE_END_PATTERN.match(line):
                    in_instream = False
                continue

            # JOB statement
            job_match = JOB_PATTERN.match(line)
            if job_match:
                job_name = job_match.group(1).upper()
                continue

            # EXEC statement
            exec_match = EXEC_PATTERN.match(line)
            if exec_match:
                step_name = exec_match.group(1).upper()
                program   = exec_match.group(2).upper() if exec_match.group(2) else ""

                # Extract PARM
                parm_match = PARM_PATTERN.search(line)
                parm = parm_match.group(1) if parm_match else ""

                current_step = {
                    "step_name": step_name,
                    "program":   program,
                    "parm":      parm,
                    "steplib":   "",
                    "datasets":  [],
                }
                steps.append(current_step)
                current_dd = None
                continue

            # DD statement
            dd_match = DD_PATTERN.match(line)
            if dd_match and current_step is not None:
                dd_name = dd_match.group(1).upper()

                # Check for in-stream data
                if INSTREAM_PATTERN.search(line):
                    in_instream = True
                    continue

                dsn  = _extract_dsn(line)
                disp = _extract_disp(line)

                # STEPLIB is special — it sets the load library
                if dd_name == "STEPLIB":
                    if dsn:
                        current_step["steplib"] = dsn
                    current_dd = {"dd_name": dd_name, "dsn": dsn, "disposition": disp}
                    continue

                # Skip system DDs (SYSPRINT, SYSOUT, SYSIN, etc.)
                if dd_name.startswith("SYS"):
                    current_dd = None
                    continue

                current_dd = {
                    "dd_name":     dd_name,
                    "dsn":         dsn,
                    "disposition": disp,
                }
                if dsn:
                    current_step["datasets"].append(current_dd)
                continue

        result = {
            "job_name":    job_name,
            "source_file": jcl_file.name,
            "status":      "ok",
            "step_count":  len(steps),
            "steps":       steps,
        }

        self.event_log.log_success(
            jcl_file.name,
            details={
                "steps": len(steps),
                "programs": [s["program"] for s in steps if s["program"]],
                "datasets": sum(len(s["datasets"]) for s in steps),
            }
        )

        logger.info(
            f"Parsed {jcl_file.name}: {len(steps)} steps, "
            f"{sum(len(s['datasets']) for s in steps)} datasets"
        )
        return result

    def _join_continuations(self, lines: list[str]) -> list[str]:
        """
        Join JCL continuation lines into single logical lines.

        JCL continuation: a line ending before column 72 with content,
        continued on the next line starting with // + spaces (no name).

        Args:
            lines: Raw JCL lines

        Returns:
            list: Lines with continuations joined
        """
        joined = []
        buffer = ""

        for line in lines:
            # Pad to at least 72 chars for column checking
            padded = line.ljust(72)

            if buffer and CONTINUATION_PATTERN.match(line) and not COMMENT_PATTERN.match(line):
                # This is a continuation — append to buffer
                # Strip the leading // and spaces
                continuation = line[2:].strip()
                buffer = buffer.rstrip() + " " + continuation
            else:
                if buffer:
                    joined.append(buffer)
                buffer = line

        if buffer:
            joined.append(buffer)

        return joined

    def parse_all(self, jcl_dir: Path) -> list[dict]:
        """
        Parse all JCL files in a directory.

        Args:
            jcl_dir: Directory containing .jcl files

        Returns:
            list: Parse results for all files
        """
         # Deduplicate by stem (handle mixed case .jcl/.JCL)
        seen = {}
        for f in list(jcl_dir.glob("*.jcl")) + list(jcl_dir.glob("*.JCL")):
            if f.stem.upper() not in seen:
                seen[f.stem.upper()] = f
        files = sorted(seen.values(), key=lambda f: f.stem.upper())
        logger.info(f"Parsing {len(files)} JCL files from {jcl_dir}")

        results  = []
        passed   = 0
        failed   = 0

        for f in files:
            result = self.parse(f)
            results.append(result)
            if result.get("status") == "ok":
                passed += 1
            else:
                failed += 1

        self.event_log.save()
        logger.info(f"JCL batch parse: {passed} passed, {failed} failed")
        return results

    def save_results(
        self,
        results: list[dict],
        output_dir: Optional[Path] = None
    ) -> Path:
        """
        Save all JCL parse results to a single JSON artifact.

        Args:
            results:    List of parse results
            output_dir: Output directory

        Returns:
            Path to saved file
        """
        output_dir = output_dir or (OUT_DIR / "artifacts" / "jcl")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "jcl_all.json"
        artifact = {
            "layer":      "L4",
            "file_count": len(results),
            "jobs":       results,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)

        logger.info(f"JCL artifacts saved: {output_path}")
        return output_path
