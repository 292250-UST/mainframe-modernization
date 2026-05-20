"""
spec_generator.py
=================
Generates program specifications using LLM API (OpenAI).
"""

import json
import os
from openai import OpenAI
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger
from src.llm.retrieval import assemble_program_slice, format_slice_for_llm

import sys
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("llm.spec_generator")
DEMO_DIR = OUT_DIR / "demo"


def get_client():
    """Get LLM client — (OpenAI)."""
    return OpenAI(
        base_url="https://api.openai.com/v1",
        api_key=os.environ["OPENAI_API_KEY"]
    )


def generate_program_spec(program_name: str, output_dir=None) -> dict:
    """Generate a grounded specification for one COBOL program."""
    output_dir = output_dir or DEMO_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Generating spec for: {program_name}")

    slice_data = assemble_program_slice(program_name)
    context    = format_slice_for_llm(slice_data)

    if "error" in slice_data:
        return {"error": slice_data["error"]}

    system_prompt = """You are a COBOL modernization expert analyzing the CardDemo banking system.
Generate a faithful, traceable specification from the artifacts provided.
RULES:
1. Cite sources using UUIDs: [UUID:xxx] for paragraphs and symbols, [LINE:xxx] for line numbers, [COPY:name] for copybooks
2. Every paragraph and variable reference MUST include its UUID from the context
3. Do NOT invent functionality not shown in the artifacts
4. Structure: Purpose, Inputs, Processing Logic, Outputs, Error Handling
5. Keep concise — 300-500 words"""

    user_prompt = f"""Generate a specification for this COBOL program. Cite every claim.

{context}

Generate the specification:"""

    client = get_client()
    logger.info("Calling LLM API...")

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        # max_tokens=1000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )

    spec_text   = response.choices[0].message.content
    tokens_used = response.usage.total_tokens if response.usage else 0
    logger.info(f"Spec generated: {len(spec_text)} chars, {tokens_used} tokens")

    result = {
        "program":      program_name,
        "spec":         spec_text,
        "model":        "gpt-5.4-mini",
        "tokens_used":  tokens_used,
        "artifact_slice": {
            "paragraphs": len(slice_data.get("paragraphs", [])),
            "symbols":    len(slice_data.get("symbols", [])),
            "cics_stmts": len(slice_data.get("cics_statements", [])),
            "file_ops":   len(slice_data.get("file_io", [])),
            "comments":   len(slice_data.get("comments", [])),
        },
    }

    out_path = output_dir / f"{program_name}_spec.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    txt_path = output_dir / f"{program_name}_spec.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"SPECIFICATION: {program_name}\\n")
        f.write("=" * 60 + "\\n\\n")
        f.write(spec_text)

    logger.info(f"Spec saved: {out_path}")
    return result


if __name__ == "__main__":
    import sys
    program = sys.argv[1] if len(sys.argv) > 1 else "COTRN02C"
    result  = generate_program_spec(program)
    print()
    print("="*60)
    print(f"SPEC FOR {result.get('program', 'UNKNOWN')}")
    print("="*60)
    print(result.get("spec", result.get("error", "No spec")))