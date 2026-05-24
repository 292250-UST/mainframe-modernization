"""
canonical_ir.py
===============
Lowers COBOL AST + symbol table + type system into a language-neutral IR.

IR structure per program:
- metadata: program name, type (online/batch), lines, copybooks
- fields: all data items with Java/Python type mappings
- methods: paragraphs as callable units with PERFORM edges
- rules: business rules as typed conditional expressions
- io: file/CICS/IMS/MQ access patterns
- seams: bounded context assignment
"""
import json
import duckdb
from pathlib import Path
from typing import Optional
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR
from src.utils.logger import get_logger

logger = get_logger("layers.l8_ir.canonical_ir")
DB_PATH = OUT_DIR / "graph" / "artifacts.duckdb"
IR_DIR  = OUT_DIR / "artifacts" / "layer8"

# ── Type mapping ────────────────────────────────────────────
def canonical_to_java(ct: dict, pic: str = "") -> dict:
    """Map COBOL canonical type to Java type with full semantic preservation."""
    kind      = ct.get("kind", "alphanumeric")
    precision = ct.get("precision", 0)
    scale     = ct.get("scale", 0)
    signed    = ct.get("signed", False)
    length    = ct.get("length", 0)
    packed    = ct.get("packed", False)

    if kind == "alphanumeric":
        return {
            "java_type":   "String",
            "python_type": "str",
            "constraint":  f"maxLength={length}",
            "note":        f"PIC X({length})"
        }
    elif kind == "decimal":
        return {
            "java_type":   "BigDecimal",
            "python_type": "Decimal",
            "constraint":  f"precision={precision} scale={scale} RoundingMode=HALF_EVEN",
            "note":        f"PIC S9({precision-scale})V9({scale})"
                           + (" COMP-3" if packed else ""),
            "import":      "java.math.BigDecimal"
        }
    elif kind == "packed_decimal":
        return {
            "java_type":   "BigDecimal",
            "python_type": "Decimal",
            "constraint":  f"precision={precision} scale={scale} RoundingMode=HALF_EVEN packed=true",
            "note":        "COMP-3 packed decimal — use BigDecimal to preserve rounding semantics",
            "import":      "java.math.BigDecimal"
        }
    elif kind == "binary":
        if precision <= 4:
            java_t = "short" if not signed else "short"
        elif precision <= 9:
            java_t = "int"
        else:
            java_t = "long"
        return {
            "java_type":   java_t,
            "python_type": "int",
            "constraint":  f"precision={precision} signed={signed}",
            "note":        "COMP/COMP-4 binary"
        }
    elif kind == "numeric":
        java_t = "int" if precision <= 9 else "long"
        return {
            "java_type":   java_t if not signed else java_t,
            "python_type": "int",
            "constraint":  f"precision={precision} signed={signed}",
            "note":        "PIC 9 zoned decimal"
        }
    elif kind == "edited_numeric":
        return {
            "java_type":   "String",
            "python_type": "str",
            "constraint":  "formatted numeric display",
            "note":        "ZZZ,ZZZ display — format on output"
        }
    elif kind == "group":
        return {
            "java_type":   "Object",
            "python_type": "dict",
            "constraint":  "group item — decompose to fields",
            "note":        "01-level group → Java class or record"
        }
    return {"java_type": "Object", "python_type": "Any", "constraint": "", "note": kind}


def canonical_to_perform_type(edge_type: str) -> str:
    """Map CFG edge type to Java call pattern."""
    mapping = {
        "PERFORM":              "methodCall",
        "PERFORM_CONDITIONAL":  "conditionalMethodCall",
        "PERFORM_UNTIL":        "whileLoop",
        "PERFORM_VARYING":      "forLoop",
        "PERFORM_THRU":         "methodCallRange",
    }
    return mapping.get(edge_type, "methodCall")


# ── Seam assignment ─────────────────────────────────────────
SEAM_MAP = {
    "Account":       ["CBACT01C","CBACT02C","CBACT03C","CBACT04C","COACTUPC","COACTVWC"],
    "Card":          ["COCRDLIC","COCRDSLC","COCRDUPC"],
    "Transaction":   ["CBTRN01C","CBTRN02C","CBTRN03C","COTRN00C","COTRN01C","COTRN02C",
                      "CBEXPORT","CBIMPORT"],
    "BillPayment":   ["COBIL00C","CORPT00C"],
    "UserAdmin":     ["COUSR00C","COUSR01C","COUSR02C","COUSR03C","COADM01C","COMEN01C"],
    "SignOn":        ["COSGN00C","COBSWAIT","CSUTLDTC","CSUTLDWY"],
    "Authorization": ["COPAUA0C","COPAUS0C","COPAUS1C","COPAUS2C","CBPAUP0C",
                      "DBUNLDGS","PAUDBLOD","PAUDBUNL"],
    "Batch":         ["CBCUS01C","CBSTM03A","CBSTM03B","CBACT01C","CBACT02C",
                      "CBACT03C","CBACT04C"],
}

def get_seam(program_name: str) -> str:
    prog = program_name.upper()
    for seam, programs in SEAM_MAP.items():
        if prog in programs:
            return seam
    return "Unknown"


# ── IR builder ──────────────────────────────────────────────
def build_canonical_ir(program_name: str, db_path: Optional[Path] = None) -> dict:
    """Build canonical IR for one program."""
    db_path = db_path or DB_PATH
    conn = duckdb.connect(str(db_path), read_only=True)
    prog = program_name.upper().replace(".CBL", "")

    try:
        # Program node
        node = conn.execute("""
            SELECT uuid, source_file, start_line, end_line, payload_json
            FROM nodes WHERE kind='ProgramNode'
            AND UPPER(source_file) = UPPER(?)
            LIMIT 1
        """, [prog + ".cbl"]).fetchone()

        if not node:
            return {"error": f"Program {prog} not found"}

        prog_uuid, source_file, start_line, end_line, payload_json = node
        payload = json.loads(payload_json) if payload_json else {}

        ir = {
            "ir_version":   "1.0",
            "program":      prog,
            "program_uuid": prog_uuid,
            "source_file":  source_file,
            "kind":         payload.get("program_type", "unknown"),
            "total_lines":  end_line - start_line + 1,
            "copybooks":    payload.get("copybooks", []),
            "seam":         get_seam(prog),
            "fields":       [],
            "methods":      [],
            "rules":        [],
            "io":           {},
            "type_imports": set(),
        }

        # ── Fields (symbols → typed IR fields) ─────────────
        symbols = conn.execute("""
            SELECT uuid, name, level, pic, usage, scope,
                   canonical_type, copybook_origin, defined_at_line
            FROM symbols
            WHERE program_uuid = ?
            AND level IN (1, 5, 77)
            ORDER BY defined_at_line
        """, [prog_uuid]).fetchall()

        for s in symbols:
            ct = json.loads(s[6]) if s[6] else {}
            java_mapping = canonical_to_java(ct, s[3] or "")
            field = {
                "uuid":           s[0],
                "name":           s[1],
                "java_name":      to_camel_case(s[1]),
                "level":          s[2],
                "pic":            s[3],
                "usage":          s[4],
                "scope":          s[5],
                "canonical_type": ct,
                "java_type":      java_mapping["java_type"],
                "python_type":    java_mapping["python_type"],
                "constraint":     java_mapping.get("constraint", ""),
                "note":           java_mapping.get("note", ""),
                "copybook_origin":s[7],
                "defined_at_line":s[8],
            }
            if "import" in java_mapping:
                ir["type_imports"].add(java_mapping["import"])
            ir["fields"].append(field)

        # ── Methods (paragraphs + CFG → callable units) ─────
        paragraphs = conn.execute("""
            SELECT uuid, name, start_line, end_line,
                   statement_count, complexity
            FROM paragraphs
            WHERE program_uuid = ?
            ORDER BY start_line
        """, [prog_uuid]).fetchall()

        para_map = {p[1].upper(): p[0] for p in paragraphs}

        for p in paragraphs:
            # Get outgoing CFG edges for this paragraph
            edges = conn.execute("""
                SELECT id, to_uuid, edge_type, condition, line_num
                FROM control_flow
                WHERE UPPER(source_file) = UPPER(?)
                AND UPPER(from_uuid) = UPPER(?)
                ORDER BY line_num
            """, [source_file, p[1]]).fetchall()

            # Get CICS statements in this paragraph range
            cics_path = OUT_DIR / "artifacts" / "layer3" / "cics_statements.json"
            cics_in_para = []
            if cics_path.exists():
                cics_data = json.loads(cics_path.read_text())
                cics_in_para = [
                    s for s in cics_data.get("statements", [])
                    if s.get("source_file","").upper() == source_file.upper()
                    and s.get("paragraph","").upper() == p[1].upper()
                ]

            method = {
                "uuid":            p[0],
                "name":            p[1],
                "java_name":       to_camel_case(p[1]),
                "start_line":      p[2],
                "end_line":        p[3],
                "statement_count": p[4],
                "complexity":      p[5],
                "calls": [
                    {
                        "edge_uuid":   e[0],
                        "target":      e[1],
                        "java_target": to_camel_case(e[1]),
                        "call_type":   canonical_to_perform_type(e[2]),
                        "condition":   e[3],
                        "line":        e[4],
                    }
                    for e in edges
                ],
                "cics": [
                    {
                        "uuid":   s.get("uuid",""),
                        "verb":   s["verb"],
                        "params": s["params"],
                        "line":   s["line"],
                        "java_pattern": cics_to_java(s["verb"], s["params"]),
                    }
                    for s in cics_in_para
                ],
                "is_entry_point": p[1].upper() in ["MAIN-PARA","0000-MAIN","MAIN"],
            }
            ir["methods"].append(method)

        # ── Rules (business rules → typed conditionals) ──────
        rules = conn.execute("""
            SELECT uuid, kind, predicate_raw, then_summary,
                   else_summary, line_num
            FROM business_rules
            WHERE UPPER(source_file) = UPPER(?)
            ORDER BY line_num
        """, [source_file]).fetchall()

        for r in rules:
            ir["rules"].append({
                "uuid":         r[0],
                "kind":         r[1],
                "predicate":    r[2],
                "java_pattern": predicate_to_java(r[2] or ""),
                "then":         r[3],
                "else":         r[4],
                "line":         r[5],
            })

        # ── I/O (file, CICS, IMS, MQ) ───────────────────────
        file_ops = conn.execute("""
            SELECT id, file_name, operation, line_num
            FROM file_io WHERE UPPER(program_uuid) = UPPER(?)
            ORDER BY line_num
        """, [prog]).fetchall()

        ir["io"]["file_access"] = [
            {
                "uuid":           r[0],
                "file":           r[1],
                "operation":      r[2],
                "java_pattern":   file_op_to_java(r[2]),
                "line":           r[3],
            }
            for r in file_ops
        ]

        ims_ops = conn.execute("""
            SELECT id, segment_name, operation, pcb_name, line_num
            FROM ims_io WHERE UPPER(program_uuid) = UPPER(?)
            ORDER BY line_num
        """, [prog]).fetchall()

        ir["io"]["ims_access"] = [
            {
                "uuid": r[0], "segment": r[1],
                "operation": r[2], "pcb": r[3], "line": r[4],
                "java_pattern": f"imsRepository.{r[2].lower()}({r[1]})",
            }
            for r in ims_ops
        ]

        mq_ops = conn.execute("""
            SELECT id, queue_name, operation, line_num
            FROM mq_io WHERE UPPER(program_uuid) = UPPER(?)
            ORDER BY line_num
        """, [prog]).fetchall()

        ir["io"]["mq_access"] = [
            {
                "uuid": r[0], "queue": r[1],
                "operation": r[2], "line": r[3],
                "java_pattern": mq_to_java(r[2], r[1]),
            }
            for r in mq_ops
        ]

        tx_ops = conn.execute("""
            SELECT id, to_program_uuid, edge_type, transid, line_num
            FROM transaction_flow
            WHERE UPPER(from_program_uuid) = UPPER(?)
            ORDER BY line_num
        """, [prog]).fetchall()

        ir["io"]["transaction_flow"] = [
            {
                "uuid": r[0], "to_program": r[1],
                "edge_type": r[2], "transid": r[3], "line": r[4],
                "java_pattern": f"cicsReturn(\"{r[3]}\", commArea)",
            }
            for r in tx_ops
        ]

        # Convert set to list for JSON serialization
        ir["type_imports"] = sorted(list(ir["type_imports"]))

        return ir

    finally:
        conn.close()


# ── Helper functions ─────────────────────────────────────────
def to_camel_case(name: str) -> str:
    """Convert COBOL-style name to Java camelCase."""
    parts = name.replace("-", "_").split("_")
    if not parts:
        return name.lower()
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def cics_to_java(verb: str, params: dict) -> str:
    """Map CICS verb to Java/Spring pattern."""
    mapping = {
        "RETURN":   f"return CicsResponse.returnTo(\"{params.get('TRANSID','')}\", commArea)",
        "XCTL":     f"cicsXctl(\"{params.get('PROGRAM','')}\", commArea)",
        "LINK":     f"cicsLink(\"{params.get('PROGRAM','')}\", commArea)",
        "SEND":     f"cicsMap.send(\"{params.get('MAP','')}\", mapData)",
        "RECEIVE":  f"cicsMap.receive(\"{params.get('MAP','')}\", mapData)",
        "READ":     f"vsam.read(\"{params.get('DATASET','')}\", key)",
        "WRITE":    f"vsam.write(\"{params.get('DATASET','')}\", record)",
        "REWRITE":  f"vsam.rewrite(\"{params.get('DATASET','')}\", record)",
        "DELETE":   f"vsam.delete(\"{params.get('DATASET','')}\", key)",
        "STARTBR":  f"vsam.startBrowse(\"{params.get('DATASET','')}\", key)",
        "READNEXT": f"vsam.readNext(\"{params.get('DATASET','')}\", record)",
        "ENDBR":    f"vsam.endBrowse(\"{params.get('DATASET','')}\", record)",
    }
    return mapping.get(verb, f"cics{verb.capitalize()}({params})")


def file_op_to_java(operation: str) -> str:
    """Map COBOL file operation to Java repository pattern."""
    mapping = {
        "READ":    "repository.findById(key)",
        "WRITE":   "repository.save(record)",
        "REWRITE": "repository.save(record)",
        "DELETE":  "repository.deleteById(key)",
        "OPEN":    "// OPEN — handled by Spring Data lifecycle",
        "CLOSE":   "// CLOSE — handled by Spring Data lifecycle",
        "START":   "repository.findByKeyGreaterThanEqual(key)",
        "READNEXT":"repository.findNext(cursor)",
    }
    return mapping.get(operation.upper(), f"repository.{operation.lower()}()")


def mq_to_java(operation: str, queue: str) -> str:
    """Map MQ operation to Java JMS pattern."""
    mapping = {
        "MQOPEN":  f"jmsTemplate.setDefaultDestinationName(\"{queue}\")",
        "MQGET":   f"jmsTemplate.receive(\"{queue}\")",
        "MQPUT1":  f"jmsTemplate.send(\"{queue}\", message)",
        "MQCLOSE": f"// MQCLOSE — handled by JMS connection lifecycle",
        "GET":     f"jmsTemplate.receive(\"{queue}\")",
        "PUT":     f"jmsTemplate.send(\"{queue}\", message)",
    }
    return mapping.get(operation.upper(), f"jms.{operation.lower()}(\"{queue}\")")


def predicate_to_java(predicate: str) -> str:
    """Convert COBOL predicate to Java boolean expression."""
    java = predicate
    replacements = [
        ("NOT =",    "!="),
        ("NOT >",    "<="),
        ("NOT <",    ">="),
        (" = ",      " == "),
        (" > ",      " > "),
        (" < ",      " < "),
        (" >= ",     " >= "),
        (" <= ",     " <= "),
        ("AND",      "&&"),
        ("OR",       "||"),
        ("NOT ",     "!"),
        ("SPACES",   "\"\""),
        ("LOW-VALUES","\"\\0\""),
        ("HIGH-VALUES","\"\\xFF\""),
        ("ZEROES",   "0"),
        ("ZEROS",    "0"),
    ]
    for cobol, java_op in replacements:
        java = java.replace(cobol, java_op)
    return java.strip()


def build_all_ir(db_path: Optional[Path] = None) -> dict:
    """Build canonical IR for all programs."""
    db_path = db_path or DB_PATH
    conn = duckdb.connect(str(db_path), read_only=True)

    programs = conn.execute("""
        SELECT payload_json->>'program_name' as name
        FROM nodes WHERE kind='ProgramNode'
        ORDER BY name
    """).fetchall()
    conn.close()

    IR_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    for (prog,) in programs:
        if not prog:
            continue
        logger.info(f"Building IR for {prog}...")
        ir = build_canonical_ir(prog, db_path)
        if "error" not in ir:
            out_path = IR_DIR / f"{prog}_ir.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(ir, f, indent=2)
            results[prog] = {
                "fields":  len(ir["fields"]),
                "methods": len(ir["methods"]),
                "rules":   len(ir["rules"]),
                "seam":    ir["seam"],
            }
            logger.info(f"  {prog}: {len(ir['fields'])} fields, {len(ir['methods'])} methods, seam={ir['seam']}")

    # Save summary
    summary = {
        "total_programs": len(results),
        "programs": results,
        "seams": {}
    }
    for prog, data in results.items():
        seam = data["seam"]
        if seam not in summary["seams"]:
            summary["seams"][seam] = []
        summary["seams"][seam].append(prog)

    with open(IR_DIR / "ir_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return summary


if __name__ == "__main__":
    summary = build_all_ir()
    print(f"\nCanonical IR built for {summary['total_programs']} programs")
    print("\nBounded contexts (seams):")
    for seam, programs in summary["seams"].items():
        print(f"  {seam}: {programs}")
