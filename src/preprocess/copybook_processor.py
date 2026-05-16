"""
copybook_processor.py
=====================
COBOL copybook preprocessor with line-level provenance tracking.

WHY THIS EXISTS:
    COBOL programs use COPY statements to include shared code from
    copybook files (.cpy). Before parsing, these must be resolved
    (expanded inline) so the parser sees a complete flat source.

    The brief marks provenance tracking as CRITICAL (section 6):
    'Every expanded line must remember its origin copybook and the
    substitutions applied. This is what makes forward engineering
    tractable.'

WHAT IT DOES:
    1. Reads a .cbl source file line by line
    2. When it finds a COPY statement:
       a. Loads the copybook from the cpy/ directory (via cache)
       b. Applies any REPLACING rules (text substitution)
       c. Expands the copybook lines inline
       d. Tracks provenance for every expanded line
    3. Returns:
       - preprocessed_lines: flat list of strings (what ProLeap sees)
       - ProvenanceMap: line-level origin tracking

COBOL COPY SYNTAX HANDLED:
    COPY CVACT01Y.                          -- simple copy
    COPY CVACT01Y REPLACING                 -- with substitution
        ==WS-ACCOUNT== BY ==WS-ACCT==.
    COPY CVACT01Y IN 'COPYLIB'.             -- with library (treated same)

KNOWN LIMITATIONS:
    - Nested COPY (copybook that COPYs another) is handled recursively
      up to MAX_COPY_DEPTH levels
    - COPY REPLACING with partial word replacement (--suffix--) not yet
      supported — logged as WARNING
    - Library qualifier (IN/OF) is accepted but ignored (path from config)

DOWNSTREAM CONSUMERS:
    - proleap_wrapper.py   (receives preprocessed source)
    - ast_transformer.py   (uses provenance map for source ranges)
    - layer1 artifacts     (provenance_map.json saved alongside AST)
"""

import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from src.utils.logger import get_logger, PipelineEventLog
from src.preprocess.copybook_cache import load_copybook
from src.preprocess.provenance_tracker import (
    ProvenanceMap, ProvenanceLine, ReplacingRule
)

logger = get_logger("preprocess.copybook_processor")

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Maximum depth of nested COPY resolution to prevent infinite loops
MAX_COPY_DEPTH = 5

# Regex to detect a COPY statement (COBOL fixed format)
# Handles: COPY name. / COPY name REPLACING ... / COPY name IN lib.
# COBOL is case-insensitive so we use re.IGNORECASE
COPY_PATTERN = re.compile(
    r'^\s{6,}'                      # at least 6 spaces (Area A/B)
    r'COPY(?![-\w])\s+'            # COPY keyword — NOT followed by hyphen or word char
    r"['\"]?([A-Z0-9#@$-]+)['\"]?" # copybook name — optional quotes around name
    r'(?:\s+IN\s+[^\s.]+)?'        # optional IN library-name (ignored)
    r'(?:\s+REPLACING\s+(.+?))?'   # optional REPLACING clause
    r'\s*\.',                       # terminating period
    re.IGNORECASE | re.DOTALL
)

# Regex to extract REPLACING pairs: ==original== BY ==replacement==
REPLACING_PATTERN = re.compile(
    r'==\s*(.+?)\s*=='              # original text in == ==
    r'\s+BY\s+'                     # BY keyword
    r'==\s*(.+?)\s*==',            # replacement text in == ==
    re.IGNORECASE
)

# COBOL comment line: column 7 (index 6) is '*' or '/'
# In fixed format, columns are 1-indexed so index 6 = column 7
COMMENT_PATTERN = re.compile(r'^.{6}[*/]')


# ---------------------------------------------------------------------------
# RESULT DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class PreprocessResult:
    """
    Result of preprocessing one COBOL source file.

    Attributes:
        source_file (str):          Original .cbl filename
        preprocessed_lines (list):  Flat list of lines after COPY expansion
                                    This is what ProLeap receives as input
        provenance_map (ProvenanceMap): Line-level origin tracking
        copybooks_found (list):     Copybook names successfully resolved
        copybooks_missing (list):   Copybook names that could not be found
        success (bool):             True if all COPYs resolved successfully
    """
    source_file: str
    preprocessed_lines: list[str] = field(default_factory=list)
    provenance_map: Optional[ProvenanceMap] = None
    copybooks_found: list[str] = field(default_factory=list)
    copybooks_missing: list[str] = field(default_factory=list)
    success: bool = True

    def preprocessed_source(self) -> str:
        """Return preprocessed lines joined as a single string."""
        return '\n'.join(self.preprocessed_lines)


# ---------------------------------------------------------------------------
# MAIN PROCESSOR CLASS
# ---------------------------------------------------------------------------

class CopybookProcessor:
    """
    Preprocesses COBOL source files by resolving COPY statements.

    Produces a flat preprocessed source with full provenance tracking.
    One instance can process multiple files — state is reset per file.

    Usage:
        processor = CopybookProcessor(copybook_dir=Path('corpus/app/cpy'))
        result = processor.process(Path('corpus/app/cbl/CBACT01C.cbl'))
        print(result.provenance_map.summary())
    """

    def __init__(self, copybook_dir: Path):
        """
        Initialize the copybook processor.

        Args:
            copybook_dir (Path): Directory containing .cpy copybook files.
                                 Typically: corpus/app/cpy/
        """
        self.copybook_dir = copybook_dir
        self.event_log = PipelineEventLog("copybook_processor")
        logger.info(f"CopybookProcessor initialized. Copybook dir: {copybook_dir}")

    def process(self, source_path: Path) -> PreprocessResult:
        """
        Preprocess one COBOL source file — resolve all COPY statements.

        Args:
            source_path (Path): Path to the .cbl source file.

        Returns:
            PreprocessResult with preprocessed lines and provenance map.
        """
        logger.info(f"Preprocessing: {source_path.name}")

        # Read the source file
        try:
            raw_lines = source_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except Exception as e:
            logger.error(f"Cannot read source file: {source_path} — {e}")
            self.event_log.log_failure(
                source_path.name,
                reason=f"Cannot read file: {e}",
                downstream_impact=["Layer 1 AST", "Layer 2 symbols", "All downstream layers"]
            )
            return PreprocessResult(source_file=source_path.name, success=False)

        # Initialize result and provenance map
        result = PreprocessResult(
            source_file=source_path.name,
            provenance_map=ProvenanceMap(source_path.name)
        )

        # Expand all COPY statements recursively
        self._expand_lines(
            lines=raw_lines,
            origin_file=source_path.name,
            result=result,
            copy_depth=0
        )

        # Log outcome
        if result.copybooks_missing:
            self.event_log.log_gap(
                source_file=source_path.name,
                gap_type="MISSING_COPYBOOK",
                missing=", ".join(result.copybooks_missing),
                downstream_impact=[
                    "Layer 1: incomplete AST (missing data structures)",
                    "Layer 2: incomplete symbol table",
                    "Layer 3: def-use chains may be broken",
                    "Forward engineering: cannot trace copybook origin lines"
                ]
            )
            result.success = False
        else:
            self.event_log.log_success(
                source_file=source_path.name,
                details={
                    "total_lines": len(result.preprocessed_lines),
                    "copybooks_resolved": result.copybooks_found
                }
            )

        logger.info(
            f"Preprocessed {source_path.name}: "
            f"{len(result.preprocessed_lines)} lines total, "
            f"{len(result.copybooks_found)} copybooks resolved, "
            f"{len(result.copybooks_missing)} missing"
        )

        return result

    def _expand_lines(
        self,
        lines: list[str],
        origin_file: str,
        result: PreprocessResult,
        copy_depth: int,
        replacing_rules: list[ReplacingRule] = None
    ) -> None:
        """
        Recursively expand lines — resolving COPY statements inline.

        This is the core of the preprocessor. It walks through lines
        and when it finds a COPY statement, loads the copybook and
        recursively expands it (handling nested COPYs).

        Args:
            lines:          Lines to process (from .cbl or .cpy file)
            origin_file:    Name of the file these lines came from
            result:         PreprocessResult being built (mutated in place)
            copy_depth:     Current nesting level (0 = original program)
            replacing_rules: REPLACING rules to apply to each line
        """
        # Guard against infinite recursion from circular COPY references
        if copy_depth > MAX_COPY_DEPTH:
            logger.error(
                f"MAX_COPY_DEPTH ({MAX_COPY_DEPTH}) exceeded in {origin_file}. "
                f"Possible circular COPY reference. Stopping expansion."
            )
            return

        replacing_rules = replacing_rules or []
        origin_line_num = 0

        # Multi-line COPY statement buffer
        # COPY ... REPLACING ... can span multiple lines in COBOL
        in_copy_statement = False
        copy_buffer = []

        for raw_line in lines:
            origin_line_num += 1

            # ---------------------------------------------------------------
            # Handle multi-line COPY statements
            # COBOL allows COPY to span lines — collect until period found
            # ---------------------------------------------------------------
            if in_copy_statement:
                copy_buffer.append(raw_line)
                if '.' in raw_line:
                    # End of COPY statement — process accumulated buffer
                    full_copy_stmt = ' '.join(copy_buffer)
                    in_copy_statement = False
                    copy_buffer = []
                    self._handle_copy(
                        full_copy_stmt, origin_file, origin_line_num,
                        result, copy_depth, replacing_rules
                    )
                continue

            # ---------------------------------------------------------------
            # Check if this line starts a COPY statement
            # ---------------------------------------------------------------
            stripped = raw_line.strip()

            # Skip comment lines and empty lines quickly
            if not stripped or COMMENT_PATTERN.match(raw_line):
                # Still track in provenance as original file line
                pline = ProvenanceLine(
                    expanded_line_num=len(result.preprocessed_lines) + 1,
                    content=raw_line,
                    origin_file=origin_file,
                    origin_line_num=origin_line_num,
                    copybook=None if copy_depth == 0 else origin_file.replace('.cpy','').replace('.CPY',''),
                    replacing=replacing_rules if copy_depth > 0 else [],
                    copy_depth=copy_depth
                )
                result.preprocessed_lines.append(raw_line)
                result.provenance_map.add_line(pline)
                continue

            # Check if line contains COPY as standalone keyword
            # Must NOT be followed by hyphen (e.g. COPY-LAST-TRAN-DATA is a paragraph name)
            if re.search(r'\bCOPY(?![-\w])', raw_line, re.IGNORECASE):
                # Check if COPY statement is complete (has period)
                if '.' in raw_line:
                    self._handle_copy(
                        raw_line, origin_file, origin_line_num,
                        result, copy_depth, replacing_rules
                    )
                else:
                    # Multi-line COPY — start buffering
                    in_copy_statement = True
                    copy_buffer = [raw_line]
                continue

            # ---------------------------------------------------------------
            # Regular line — apply any REPLACING rules and track provenance
            # ---------------------------------------------------------------
            processed_line = self._apply_replacing(raw_line, replacing_rules)

            pline = ProvenanceLine(
                expanded_line_num=len(result.preprocessed_lines) + 1,
                content=processed_line,
                origin_file=origin_file,
                origin_line_num=origin_line_num,
                copybook=None if copy_depth == 0 else origin_file.replace('.cpy','').replace('.CPY',''),
                replacing=replacing_rules if replacing_rules else [],
                copy_depth=copy_depth
            )
            result.preprocessed_lines.append(processed_line)
            result.provenance_map.add_line(pline)

    def _handle_copy(
        self,
        copy_stmt: str,
        origin_file: str,
        origin_line_num: int,
        result: PreprocessResult,
        copy_depth: int,
        parent_replacing: list[ReplacingRule]
    ) -> None:
        """
        Handle a single COPY statement — load copybook and expand inline.

        Args:
            copy_stmt:          Full COPY statement text (may span lines)
            origin_file:        File containing the COPY statement
            origin_line_num:    Line number of the COPY statement
            result:             PreprocessResult being built
            copy_depth:         Current nesting depth
            parent_replacing:   REPLACING rules from parent COPY (if nested)
        """
        # Parse the COPY statement
        match = COPY_PATTERN.search(copy_stmt)
        if not match:
            logger.warning(
                f"Could not parse COPY statement in {origin_file}:{origin_line_num}: "
                f"{copy_stmt.strip()}"
            )
            return

        copybook_name = match.group(1).strip()
        replacing_clause = match.group(2)

        # Parse REPLACING rules from this COPY statement
        replacing_rules = self._parse_replacing(replacing_clause or "")

        # Combine with parent replacing rules (for nested COPYs)
        all_replacing = parent_replacing + replacing_rules

        logger.debug(
            f"COPY {copybook_name} at {origin_file}:{origin_line_num} "
            f"(depth={copy_depth}, replacing={len(replacing_rules)} rules)"
        )

        # Load the copybook from cache
        copybook_lines = load_copybook(
            copybook_name,
            str(self.copybook_dir)
        )

        if copybook_lines is None:
            # Copybook not found — record gap and continue
            logger.warning(
                f"Missing copybook: {copybook_name} "
                f"(referenced in {origin_file}:{origin_line_num})"
            )
            if copybook_name not in result.copybooks_missing:
                result.copybooks_missing.append(copybook_name)

            self.event_log.log_gap(
                source_file=origin_file,
                gap_type="MISSING_COPYBOOK",
                missing=copybook_name,
                downstream_impact=[
                    f"Layer 1: lines from {copybook_name} missing from AST",
                    f"Layer 2: data items defined in {copybook_name} not in symbol table",
                    f"Layer 3: def-use chains involving {copybook_name} items broken",
                ]
            )
            return

        # Track copybook as found
        if copybook_name not in result.copybooks_found:
            result.copybooks_found.append(copybook_name)

        # Recursively expand the copybook lines
        self._expand_lines(
            lines=copybook_lines,
            origin_file=f"{copybook_name}.cpy",
            result=result,
            copy_depth=copy_depth + 1,
            replacing_rules=all_replacing
        )

    def _parse_replacing(self, replacing_clause: str) -> list[ReplacingRule]:
        """
        Parse REPLACING clause into a list of ReplacingRule objects.

        COBOL syntax: REPLACING ==original== BY ==replacement==
                                ==orig2==    BY ==repl2==

        Args:
            replacing_clause (str): The text after REPLACING keyword.

        Returns:
            List of ReplacingRule objects, empty if no valid pairs found.
        """
        if not replacing_clause:
            return []

        rules = []
        for match in REPLACING_PATTERN.finditer(replacing_clause):
            original = match.group(1).strip()
            replacement = match.group(2).strip()
            rules.append(ReplacingRule(original=original, replacement=replacement))
            logger.debug(f"REPLACING rule: '{original}' -> '{replacement}'")

        if replacing_clause and not rules:
            # Had REPLACING clause but couldn't parse it
            logger.warning(
                f"Could not parse REPLACING clause: {replacing_clause.strip()[:80]}"
            )

        return rules

    def _apply_replacing(
        self,
        line: str,
        rules: list[ReplacingRule]
    ) -> str:
        """
        Apply REPLACING substitution rules to a single line of text.

        COBOL REPLACING does whole-word substitution (not substring).
        'WS-ACCOUNT' should not match 'WS-ACCOUNT-ID' unless the full
        token matches.

        Args:
            line (str):            The line of text to process.
            rules (list):          ReplacingRule objects to apply.

        Returns:
            The line with all substitutions applied.
        """
        if not rules:
            return line

        result = line
        for rule in rules:
            # Use word-boundary matching for safe substitution
            # \b matches at word boundaries in COBOL identifiers
            pattern = r'\b' + re.escape(rule.original) + r'\b'
            result = re.sub(pattern, rule.replacement, result, flags=re.IGNORECASE)

        return result

    def save_event_log(self) -> dict:
        """
        Save the event log for all files processed by this instance.

        Returns:
            Summary dict with counts of success/failure/gaps.
        """
        return self.event_log.save()
