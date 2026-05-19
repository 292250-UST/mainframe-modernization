"""
ast_node.py
===========
Typed AST node hierarchy for the CardDemo modernization pipeline.

WHY THIS EXISTS:
    ProLeap returns a raw parse result (program name + paragraphs).
    This module defines our OWN clean node types that:
    - Have stable UUIDs (source-derived, deterministic)
    - Have precise source ranges (file, start_line, end_line)
    - Have parent-child relationships (tree structure)
    - Are serializable to JSON for artifact storage
    - Are the foundation for ALL downstream layers (L2-L8)

NODE HIERARCHY:
    ASTNode (base)
        ProgramNode         — one per .cbl file
            ParagraphNode   — one per paragraph in PROCEDURE DIVISION
                StatementNode — one per statement in a paragraph
        DataItemNode        — one per variable definition (L2)
        CopyStatementNode   — one per COPY statement (provenance)

UUID SCHEME (from docs/architecture.md):
    UUID = SHA256(source_file + ":" + start_line + ":" + node_kind)[:32]
    Same source = same UUID across every pipeline run.
    Verified by UUID regression tests in tests/regression/

DOWNSTREAM CONSUMERS:
    - ast_transformer.py   (creates these nodes from ProLeap output)
    - symbol_table.py      (reads DataItemNode)
    - cfg_builder.py       (reads ParagraphNode + StatementNode)
    - def_use.py           (reads StatementNode)
    - loader.py            (saves to DuckDB nodes table)
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# ---------------------------------------------------------------------------
# UUID FACTORY
# ---------------------------------------------------------------------------

def make_uuid(source_file: str, start_line: int, node_kind: str) -> str:
    """
    Generate a stable, deterministic UUID for an AST node.

    Uses SHA-256 of (source_file + start_line + node_kind).
    Same inputs always produce the same UUID — critical for
    cross-run reproducibility and UUID regression tests.

    Args:
        source_file (str): Source filename (e.g. 'CBACT01C.cbl')
        start_line (int):  Starting line number in the source file
        node_kind (str):   Node type name (e.g. 'ProgramNode')

    Returns:
        str: 32-character hex string UUID

    Example:
        >>> make_uuid('CBACT01C.cbl', 1, 'ProgramNode')
        'a3f9c2e1...'  # always the same for these inputs
    """
    key = f"{source_file}:{start_line}:{node_kind}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# NODE KIND ENUM
# ---------------------------------------------------------------------------

class NodeKind(str, Enum):
    """
    Enumeration of all AST node types in the pipeline.

    Using an Enum ensures:
    - Typos are caught at runtime (not silently wrong)
    - All node kinds are documented in one place
    - DuckDB nodes table has consistent kind values
    """
    PROGRAM         = "ProgramNode"
    PARAGRAPH       = "ParagraphNode"
    STATEMENT       = "StatementNode"
    DATA_ITEM       = "DataItemNode"
    COPY_STATEMENT  = "CopyStatementNode"
    SECTION         = "SectionNode"
    DIVISION        = "DivisionNode"


# ---------------------------------------------------------------------------
# SOURCE RANGE
# ---------------------------------------------------------------------------

@dataclass
class SourceRange:
    """
    Precise location of an AST node in the source file.

    Used for:
    - Traceability (every claim traces to a source location)
    - The DuckDB nodes table (start_line, end_line, start_col, end_col)
    - Provenance cross-linking (which copybook did this come from?)

    Attributes:
        source_file (str):  Filename (e.g. 'CBACT01C.cbl')
        start_line (int):   First line (1-indexed)
        end_line (int):     Last line (1-indexed, inclusive)
        start_col (int):    Start column (1-indexed, default 1)
        end_col (int):      End column (1-indexed, default 72)
        copybook (str):     If this range came from a copybook expansion,
                            the copybook name. None if from original file.
    """
    source_file: str
    start_line: int
    end_line: int
    start_col: int = 1
    end_col: int = 72
    copybook: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON output."""
        return {
            "source_file": self.source_file,
            "start_line":  self.start_line,
            "end_line":    self.end_line,
            "start_col":   self.start_col,
            "end_col":     self.end_col,
            "copybook":    self.copybook,
        }


# ---------------------------------------------------------------------------
# BASE AST NODE
# ---------------------------------------------------------------------------

@dataclass
class ASTNode:
    """
    Base class for all AST nodes in the pipeline.

    Every node has:
    - A stable UUID (deterministic, source-derived)
    - A node kind (from NodeKind enum)
    - A source range (file + line range)
    - An optional parent UUID (for tree traversal)
    - A list of child UUIDs (populated by ast_transformer)

    Nodes are designed to be:
    - Serializable to JSON (for Layer 1 artifacts)
    - Loadable into DuckDB (nodes table)
    - Cross-referenced by UUID only (never by name)
    """
    uuid: str                                       # stable deterministic UUID
    kind: NodeKind                                  # node type
    source_range: SourceRange                       # location in source
    parent_uuid: Optional[str] = None              # parent node UUID
    children_uuids: list[str] = field(default_factory=list)  # child UUIDs
    payload: dict = field(default_factory=dict)    # node-specific data

    def to_dict(self) -> dict:
        """
        Serialize this node to a dictionary for JSON artifact storage.

        Output format matches the DuckDB nodes table schema:
            nodes(uuid, kind, source_file, start_line, end_line,
                  start_col, end_col, parent_uuid, payload_json)
        """
        return {
            "uuid":           self.uuid,
            "kind":           self.kind.value,
            "source_range":   self.source_range.to_dict(),
            "parent_uuid":    self.parent_uuid,
            "children_uuids": self.children_uuids,
            "payload":        self.payload,
        }

    def add_child(self, child: "ASTNode") -> None:
        """
        Add a child node UUID to this node and set child's parent.

        Args:
            child: The child ASTNode to attach.
        """
        child.parent_uuid = self.uuid
        self.children_uuids.append(child.uuid)


# ---------------------------------------------------------------------------
# PROGRAM NODE
# ---------------------------------------------------------------------------

@dataclass
class ProgramNode(ASTNode):
    """
    Represents one COBOL program (.cbl file).

    One ProgramNode is created per source file.
    It is the root of the AST for that program.

    Payload fields:
        program_name (str):     PROGRAM-ID value (e.g. 'CBACT01C')
        source_file (str):      Original .cbl filename
        program_type (str):     'online' (CO prefix) or 'batch' (CB prefix)
        copybooks (list):       List of copybook names used by this program
        total_lines (int):      Total lines in preprocessed source
        paragraph_count (int):  Number of paragraphs found
    """

    @classmethod
    def create(
        cls,
        program_name: str,
        source_file: str,
        total_lines: int,
        copybooks: list[str] = None
    ) -> "ProgramNode":
        """
        Factory method — create a ProgramNode with auto-generated UUID.

        Args:
            program_name (str): PROGRAM-ID (e.g. 'CBACT01C')
            source_file (str):  .cbl filename (e.g. 'CBACT01C.cbl')
            total_lines (int):  Total lines in source
            copybooks (list):   Copybook names used

        Returns:
            ProgramNode with stable UUID
        """
        # Determine program type from naming convention
        # CO prefix = online (CICS), CB prefix = batch
        prefix = program_name[:2].upper()
        if prefix == "CO":
            program_type = "online"
        elif prefix == "CB":
            program_type = "batch"
        else:
            program_type = "unknown"

        uuid = make_uuid(source_file, 1, NodeKind.PROGRAM.value)

        return cls(
            uuid=uuid,
            kind=NodeKind.PROGRAM,
            source_range=SourceRange(
                source_file=source_file,
                start_line=1,
                end_line=total_lines,
            ),
            payload={
                "program_name":    program_name,
                "source_file":     source_file,
                "program_type":    program_type,
                "copybooks":       copybooks or [],
                "total_lines":     total_lines,
                "paragraph_count": 0,  # updated by transformer
            }
        )


# ---------------------------------------------------------------------------
# PARAGRAPH NODE
# ---------------------------------------------------------------------------

@dataclass
class ParagraphNode(ASTNode):
    """
    Represents one paragraph in a COBOL PROCEDURE DIVISION.

    COBOL paragraphs are the basic unit of procedure — like functions.
    They are PERFORM'd (called) by other paragraphs.

    Naming conventions in CardDemo:
        0000-XXXX-OPEN     — file open paragraphs
        1000-XXXX-XXX      — main processing
        9000-XXXX-CLOSE    — file close paragraphs
        9999-ABEND-PROGRAM — error/abend handling

    Payload fields:
        name (str):         Paragraph name (e.g. '1000-ACCTFILE-GET-NEXT')
        statement_count (int): Number of statements in this paragraph
        complexity (int):   Cyclomatic complexity (default 1, updated by CFG)
    """

    @classmethod
    def create(
        cls,
        name: str,
        source_file: str,
        start_line: int,
        end_line: int,
        parent_uuid: str,
        copybook: Optional[str] = None,
        statements: list = None
    ) -> "ParagraphNode":
        """
        Factory method — create a ParagraphNode with auto-generated UUID.

        Args:
            name (str):         Paragraph name
            source_file (str):  Source filename
            start_line (int):   Start line in source
            end_line (int):     End line in source
            parent_uuid (str):  UUID of parent ProgramNode
            copybook (str):     Copybook name if in copybook, else None

        Returns:
            ParagraphNode with stable UUID
        """
        uuid = make_uuid(source_file, start_line, NodeKind.PARAGRAPH.value)

        return cls(
            uuid=uuid,
            kind=NodeKind.PARAGRAPH,
            source_range=SourceRange(
                source_file=source_file,
                start_line=start_line,
                end_line=end_line,
                copybook=copybook
            ),
            parent_uuid=parent_uuid,
            payload={
                "name":            name,
                "statement_count": 0,   # updated by transformer
                "complexity":      1,   # updated by CFG builder
                "statements":      statements or [],
            }
        )


# ---------------------------------------------------------------------------
# STATEMENT NODE
# ---------------------------------------------------------------------------

@dataclass
class StatementNode(ASTNode):
    """
    Represents one COBOL statement within a paragraph.

    COBOL statement types relevant to this pipeline:
        MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE  — data movement/arithmetic
        PERFORM, PERFORM THRU, PERFORM VARYING          — control flow
        IF, EVALUATE                                    — conditional
        GO TO, GO TO DEPENDING ON                       — branching (risky)
        CALL                                            — program call
        READ, WRITE, REWRITE, DELETE, START             — file I/O
        EXEC CICS LINK/XCTL/RETURN                      — CICS transaction
        EXEC CICS READ/WRITE/SEND MAP/RECEIVE MAP       — CICS I/O

    Payload fields:
        statement_type (str):   e.g. 'MOVE', 'PERFORM', 'IF', 'CALL'
        raw_text (str):         Original statement text (for reference)
        line (int):             Line number of statement
        is_risky (bool):        True if migration-risky construct
        risk_reason (str):      Reason if is_risky=True
    """

    @classmethod
    def create(
        cls,
        statement_type: str,
        raw_text: str,
        source_file: str,
        line: int,
        parent_uuid: str,
        is_risky: bool = False,
        risk_reason: str = ""
    ) -> "StatementNode":
        """
        Factory method — create a StatementNode with auto-generated UUID.

        Args:
            statement_type (str): Type of statement (e.g. 'MOVE')
            raw_text (str):       Original statement text
            source_file (str):    Source filename
            line (int):           Line number
            parent_uuid (str):    UUID of parent ParagraphNode
            is_risky (bool):      True if this is a migration risk
            risk_reason (str):    Reason for risk

        Returns:
            StatementNode with stable UUID
        """
        uuid = make_uuid(source_file, line, NodeKind.STATEMENT.value)

        return cls(
            uuid=uuid,
            kind=NodeKind.STATEMENT,
            source_range=SourceRange(
                source_file=source_file,
                start_line=line,
                end_line=line,
            ),
            parent_uuid=parent_uuid,
            payload={
                "statement_type": statement_type,
                "raw_text":       raw_text[:200],  # truncate for storage
                "line":           line,
                "is_risky":       is_risky,
                "risk_reason":    risk_reason,
            }
        )


# ---------------------------------------------------------------------------
# DATA ITEM NODE (Layer 2)
# ---------------------------------------------------------------------------

@dataclass
class DataItemNode(ASTNode):
    """
    Represents one data item (variable) definition in COBOL DATA DIVISION.

    COBOL data items are defined in the DATA DIVISION with:
    - A level number (01-49, 66, 77, 88)
    - A name (or FILLER for unnamed items)
    - A PIC clause (for elementary items)
    - Optional USAGE, OCCURS, REDEFINES clauses

    Level numbers:
        01      — record level (group item or elementary)
        02-49   — subordinate items within a group
        66      — RENAMES (alias)
        77      — independent elementary item
        88      — condition name (boolean flag)

    Payload fields:
        name (str):           Variable name
        level (int):          Level number (1-88)
        pic (str):            PIC clause (e.g. 'X(08)', 'S9(9)V99')
        usage (str):          USAGE clause (DISPLAY/COMP/COMP-3/COMP-4)
        sign (str):           SIGN clause if present
        occurs (dict):        OCCURS bounds {min, max, depending_on}
        redefines (str):      Name of item this redefines, if any
        value_88 (list):      List of 88-level values if condition name
        copybook_origin (str): Copybook this came from, if any
        scope (str):          WORKING-STORAGE/FILE/LINKAGE/LOCAL-STORAGE
        canonical_type (dict): Normalized type {kind, precision, scale, signed}
    """

    @classmethod
    def create(
        cls,
        name: str,
        level: int,
        source_file: str,
        start_line: int,
        parent_uuid: str,
        pic: str = "",
        usage: str = "DISPLAY",
        scope: str = "WORKING-STORAGE",
        copybook_origin: Optional[str] = None
    ) -> "DataItemNode":
        """
        Factory method — create a DataItemNode with auto-generated UUID.

        Args:
            name (str):           Variable name
            level (int):          Level number
            source_file (str):    Source filename
            start_line (int):     Line number of definition
            parent_uuid (str):    UUID of parent node
            pic (str):            PIC clause
            usage (str):          USAGE clause
            scope (str):          Which section this is in
            copybook_origin (str): Which copybook this came from

        Returns:
            DataItemNode with stable UUID
        """
        uuid = make_uuid(source_file, start_line, NodeKind.DATA_ITEM.value)

        return cls(
            uuid=uuid,
            kind=NodeKind.DATA_ITEM,
            source_range=SourceRange(
                source_file=source_file,
                start_line=start_line,
                end_line=start_line,
                copybook=copybook_origin
            ),
            parent_uuid=parent_uuid,
            payload={
                "name":            name,
                "level":           level,
                "pic":             pic,
                "usage":           usage,
                "sign":            None,
                "occurs":          None,
                "redefines":       None,
                "value_88":        [],
                "copybook_origin": copybook_origin,
                "scope":           scope,
                "canonical_type":  None,  # populated by data_type_normalizer
            }
        )


# ---------------------------------------------------------------------------
# SERIALIZATION HELPERS
# ---------------------------------------------------------------------------

def nodes_to_json(nodes: list[ASTNode], indent: int = 2) -> str:
    """
    Serialize a list of AST nodes to a JSON string.

    Args:
        nodes (list):  List of ASTNode objects
        indent (int):  JSON indentation level

    Returns:
        str: JSON string representation
    """
    return json.dumps([n.to_dict() for n in nodes], indent=indent)
