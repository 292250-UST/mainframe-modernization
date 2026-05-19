"""
proleap_wrapper.py - updated to preprocess before parsing
"""
import subprocess
import json
import tempfile
import os
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger
from src.preprocess.copybook_processor import CopybookProcessor

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import PROLEAP_JAR, WRAPPER_DIR, COPYBOOK_DIR

logger = get_logger("parsers.proleap_wrapper")

LOG_PREFIXES = ["[main] INFO", "[main] DEBUG", "[main] WARN", "[main] ERROR"]


def _is_log_line(line: str) -> bool:
    return any(prefix in line for prefix in LOG_PREFIXES)


def _build_classpath() -> str:
    import platform
    separator = ";" if platform.system() == "Windows" else ":"
    dependency_dir = PROLEAP_JAR.parent / "dependency" / "*"
    classpath_parts = [
        str(PROLEAP_JAR),
        str(dependency_dir),
        str(WRAPPER_DIR),
    ]
    return separator.join(classpath_parts)


def parse_cobol_file(
    cbl_file: Path,
    copybook_dir: Optional[Path] = None,
    timeout_seconds: int = 120,
    use_preprocessor: bool = True,
    preprocessed_lines: Optional[list[str]] = None
) -> dict:
    """
    Parse a COBOL file using ProLeap.

    If use_preprocessor=True (default):
        - First runs Python copybook preprocessor
        - Writes preprocessed source to temp file
        - Passes temp file to ProLeap
        This avoids ProLeap failing on missing/quoted copybooks.

    If use_preprocessor=False:
        - Passes original file directly to ProLeap
        This is faster but may fail on missing copybooks.

    Args:
        cbl_file:          Path to the .cbl file
        copybook_dir:      Copybook directory (default: config.COPYBOOK_DIR)
        timeout_seconds:   Max seconds to wait for ProLeap
        use_preprocessor:  Whether to preprocess before parsing

    Returns:
        dict with status, program name, paragraphs, etc.
    """
    if copybook_dir is None:
        copybook_dir = COPYBOOK_DIR

    logger.info(f"Parsing: {cbl_file.name}")

    tmp_path = None
    preprocess_result = None

    try:
        # -------------------------------------------------------------------
        # Step 1: Preprocess COPY statements via Python preprocessor
        # This resolves all COPY statements including quoted syntax
        # and produces a flat source ProLeap can handle
        # -------------------------------------------------------------------
        if use_preprocessor:
            # Use already-preprocessed lines if provided
            # This avoids double preprocessing when called from batch_parser
            if preprocessed_lines is not None:
                logger.debug(f"Using provided preprocessed lines for {cbl_file.name}")
                lines_to_parse = preprocessed_lines
            else:
                processor = CopybookProcessor(copybook_dir=copybook_dir)
                preprocess_result = processor.process(cbl_file)
                lines_to_parse = preprocess_result.preprocessed_lines

            # Write preprocessed source to temp file
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".cbl",
                delete=False,
                encoding="utf-8"
            ) as tmp:
                tmp.write("\n".join(lines_to_parse))
                tmp_path = tmp.name

            parse_target = Path(tmp_path)
            logger.debug(f"Using preprocessed temp file: {tmp_path}")
        else:
            parse_target = cbl_file

        # -------------------------------------------------------------------
        # Step 2: Run ProLeap via subprocess on the (preprocessed) file
        # -------------------------------------------------------------------
        cmd = [
            "java",
            "-cp", _build_classpath(),
            "CobolParserWrapper",
            str(parse_target),
            str(copybook_dir)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds
        )

        # Filter log lines from stdout
        stdout_lines = result.stdout.strip().split("\n")
        json_lines = [
            line for line in stdout_lines
            if line.strip() and not _is_log_line(line)
        ]
        json_str = "\n".join(json_lines).strip()

        if not json_str:
            error_msg = result.stderr.strip() if result.stderr else "No output from ProLeap"
            logger.warning(f"No JSON output for {cbl_file.name}: {error_msg[:100]}")
            return {
                "program": cbl_file.stem,
                "status": "error",
                "error": error_msg,
                "source_file": cbl_file.name,
                "paragraphs": [],
                "copybooks_missing": preprocess_result.copybooks_missing if preprocess_result else [],
            }

        parsed = json.loads(json_str)
        # Always use original filename (not temp file name)
        parsed["program"] = cbl_file.stem
        parsed["source_file"] = cbl_file.name
        if preprocess_result:
            parsed["copybooks_resolved"] = preprocess_result.copybooks_found
            parsed["copybooks_missing"] = preprocess_result.copybooks_missing

        # paragraphs is now list of dicts {name, statements[]}
        # Extract names for backward compatibility with all downstream code
        para_data = parsed.get("paragraphs", [])
        if para_data and isinstance(para_data[0], dict):
            parsed["paragraph_statements"] = para_data  # full AST with statements
            parsed["paragraphs"] = [p["name"] for p in para_data]  # names only — backward compat
        
        logger.info(
            f"Parsed {cbl_file.name}: "
            f"{len(parsed.get('paragraphs', []))} paragraphs"
        )
        return parsed

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout ({timeout_seconds}s) parsing {cbl_file.name}")
        return {
            "program": cbl_file.stem,
            "status": "error",
            "error": f"Timeout after {timeout_seconds} seconds",
            "source_file": cbl_file.name,
            "paragraphs": []
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {cbl_file.name}: {e}")
        return {
            "program": cbl_file.stem,
            "status": "error",
            "error": f"JSON parse error: {e}",
            "source_file": cbl_file.name,
            "paragraphs": []
        }

    except Exception as e:
        logger.error(f"Unexpected error parsing {cbl_file.name}: {e}")
        return {
            "program": cbl_file.stem,
            "status": "error",
            "error": str(e),
            "source_file": cbl_file.name,
            "paragraphs": []
        }

    finally:
        # Always clean up temp file
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
            logger.debug(f"Cleaned up temp file: {tmp_path}")
