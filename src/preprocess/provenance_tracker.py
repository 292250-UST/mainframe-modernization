"""
provenance_tracker.py
=====================
Tracks the origin of every line in a preprocessed COBOL source file.

WHY THIS EXISTS:
    When a COBOL program contains a COPY statement, the copybook lines
    are expanded inline during preprocessing. After expansion, it becomes
    impossible to know which lines came from the original program and
    which came from which copybook — unless we track it explicitly.

    The brief marks this as CRITICAL (§6):
    'Every expanded line must remember its origin copybook and the
    substitutions applied. This is what makes forward engineering
    tractable.'

WHAT IT PRODUCES:
    A ProvenanceLine dataclass for every line in the preprocessed source:
    - Lines from the original .cbl file: copybook=None
    - Lines expanded from a COPY statement: copybook='CVACT01Y', etc.
    - Lines with REPLACING applied: replacing=[{from: x, to: y}, ...]

    Saved as provenance_map.json alongside the AST artifact.

EXAMPLE OUTPUT:
    Line 1:  {origin: 'CBACT01C.cbl', line: 1,  copybook: None}
    Line 45: {origin: 'CVACT01Y.cpy', line: 12, copybook: 'CVACT01Y',
              replacing: [{from: 'WS-ACCOUNT', to: 'WS-ACCT'}]}

DOWNSTREAM CONSUMERS:
    - ast_transformer.py    (source range on AST nodes)
    - forward engineering   (trace emitted code back to origin)
    - grounding_check.py    (verify LLM claims against source)
"""

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
import json

from src.utils.logger import get_logger

logger = get_logger("preprocess.provenance_tracker")


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class ReplacingRule:
    """
    Represents one REPLACING substitution applied during COPY expansion.

    COBOL syntax: COPY CVACT01Y REPLACING ==WS-ACCOUNT== BY ==WS-ACCT==
    This becomes: ReplacingRule(original='WS-ACCOUNT', replacement='WS-ACCT')
    """
    original: str       # The text being replaced (inside == ==)
    replacement: str    # The replacement text (inside == ==)


@dataclass
class ProvenanceLine:
    """
    Tracks the origin of a single line in the preprocessed COBOL source.

    Attributes:
        expanded_line_num (int):    Line number in the PREPROCESSED (flat) source.
                                    This is what ProLeap sees.
        content (str):              Actual text content of the line.
        origin_file (str):          Which file this line came from.
                                    Either the .cbl program or a .cpy copybook.
        origin_line_num (int):      Line number within the origin file.
        copybook (Optional[str]):   Copybook name if expanded from COPY,
                                    None if from the original .cbl file.
        replacing (list):           List of ReplacingRule applied to this line.
                                    Empty list if no REPLACING was used.
        copy_depth (int):           Nesting depth of COPY resolution.
                                    0 = original file, 1 = direct COPY,
                                    2 = COPY within a COPY (nested copybook).
    """
    expanded_line_num: int                          # line in flat preprocessed source
    content: str                                    # actual line text
    origin_file: str                                # .cbl or .cpy filename
    origin_line_num: int                            # line number in origin file
    copybook: Optional[str] = None                  # None if from original program
    replacing: list[ReplacingRule] = field(default_factory=list)
    copy_depth: int = 0                             # 0 = original, 1 = copybook, etc.

    def is_from_copybook(self) -> bool:
        """Return True if this line was expanded from a COPY statement."""
        return self.copybook is not None

    def has_replacing(self) -> bool:
        """Return True if any REPLACING substitution was applied to this line."""
        return len(self.replacing) > 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "expanded_line_num": self.expanded_line_num,
            "content": self.content,
            "origin_file": self.origin_file,
            "origin_line_num": self.origin_line_num,
            "copybook": self.copybook,
            "replacing": [
                {"original": r.original, "replacement": r.replacement}
                for r in self.replacing
            ],
            "copy_depth": self.copy_depth,
        }


# ---------------------------------------------------------------------------
# PROVENANCE MAP
# ---------------------------------------------------------------------------

class ProvenanceMap:
    """
    Holds the complete provenance record for one preprocessed COBOL program.

    Contains one ProvenanceLine per line in the preprocessed source.
    Provides lookup methods for upstream tools (AST transformer, grounding).

    Usage:
        pmap = ProvenanceMap('CBACT01C.cbl')
        pmap.add_line(ProvenanceLine(...))
        pmap.save(Path('out/artifacts/layer1/CBACT01C_provenance.json'))
    """

    def __init__(self, source_file: str):
        """
        Initialize a provenance map for one COBOL source file.

        Args:
            source_file (str): Name of the original .cbl file
                               (e.g. 'CBACT01C.cbl')
        """
        self.source_file = source_file
        self.lines: list[ProvenanceLine] = []

        # Quick-lookup index: expanded_line_num -> ProvenanceLine
        self._index: dict[int, ProvenanceLine] = {}

        logger.debug(f"ProvenanceMap created for: {source_file}")

    def add_line(self, pline: ProvenanceLine) -> None:
        """
        Add a tracked line to the provenance map.

        Args:
            pline (ProvenanceLine): The provenance record for one line.
        """
        self.lines.append(pline)
        self._index[pline.expanded_line_num] = pline

    def get_line(self, expanded_line_num: int) -> Optional[ProvenanceLine]:
        """
        Look up provenance for a specific line in the preprocessed source.

        Args:
            expanded_line_num (int): Line number in the preprocessed source.

        Returns:
            ProvenanceLine if found, None otherwise.
        """
        return self._index.get(expanded_line_num)

    def get_copybook_lines(self, copybook_name: str) -> list[ProvenanceLine]:
        """
        Return all lines that came from a specific copybook.

        Useful for:
        - Verifying COPY expansion worked correctly
        - Forward engineering: knowing which output lines came from shared structs

        Args:
            copybook_name (str): Copybook name without extension (e.g. 'CVACT01Y')

        Returns:
            List of ProvenanceLine from that copybook.
        """
        return [l for l in self.lines if l.copybook == copybook_name]

    def get_copybooks_used(self) -> list[str]:
        """
        Return sorted list of all copybooks referenced in this program.

        Returns:
            List of copybook names (without extension), sorted alphabetically.
        """
        return sorted(set(
            l.copybook for l in self.lines if l.copybook is not None
        ))

    def summary(self) -> dict:
        """
        Return a summary of the provenance map for logging/reporting.

        Returns:
            dict with total lines, copybook lines, original lines, copybooks used.
        """
        copybook_lines = sum(1 for l in self.lines if l.is_from_copybook())
        replacing_lines = sum(1 for l in self.lines if l.has_replacing())
        return {
            "source_file":      self.source_file,
            "total_lines":      len(self.lines),
            "original_lines":   len(self.lines) - copybook_lines,
            "copybook_lines":   copybook_lines,
            "replacing_lines":  replacing_lines,
            "copybooks_used":   self.get_copybooks_used(),
        }

    def save(self, output_path: Path) -> None:
        """
        Save the provenance map to a JSON file.

        Output format:
            {
                "source_file": "CBACT01C.cbl",
                "summary": { ... },
                "lines": [ { ProvenanceLine.to_dict() }, ... ]
            }

        Args:
            output_path (Path): Where to write the JSON file.
                                Typically: out/artifacts/layer1/CBACT01C_provenance.json
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "source_file": self.source_file,
            "summary":     self.summary(),
            "lines":       [l.to_dict() for l in self.lines],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        logger.info(
            f"Provenance map saved: {output_path.name} "
            f"({len(self.lines)} lines, "
            f"{len(self.get_copybooks_used())} copybooks)"
        )
