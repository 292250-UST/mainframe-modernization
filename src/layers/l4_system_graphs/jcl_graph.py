"""
jcl_graph.py
============
Builds JCL job dependency graph from parsed JCL artifacts.

WHY THIS EXISTS:
    Layer 4 requires: job dependency graph — which job produces
    a dataset that another job consumes. This is derived by
    finding shared dataset names across jobs.

    Producer: DISP=NEW or DISP=MOD (job creates/updates dataset)
    Consumer: DISP=SHR or DISP=OLD (job reads dataset)

WHAT IT PRODUCES:
    jcl_dependency edges:
    {
        "producer_job": "POSTTRAN",
        "consumer_job": "INTCALC",
        "dataset_name": "AWS.M2.CARDDEMO.TCATBALF.VSAM.KSDS",
        "producer_disp": "MOD",
        "consumer_disp": "SHR"
    }

DOWNSTREAM CONSUMERS:
    - loader.py         (loads jcl_job + jcl_dependency tables)
    - batch chain demo  (POSTTRAN->INTCALC->CREASTMT)
    - getJobChain() API endpoint
"""

import json
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

import sys
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import OUT_DIR

logger = get_logger("layers.l4_system_graphs.jcl_graph")

# Dispositions that indicate a job PRODUCES a dataset
PRODUCER_DISPS = {"NEW", "MOD"}

# Dispositions that indicate a job CONSUMES a dataset
CONSUMER_DISPS = {"SHR", "OLD"}


def build_jcl_graph(jcl_results: list[dict]) -> dict:
    """
    Build JCL job and dependency graphs from parsed JCL results.

    Algorithm:
    1. For each job, collect datasets it produces (NEW/MOD)
    2. For each job, collect datasets it consumes (SHR/OLD)
    3. Find pairs where producer DSN == consumer DSN
    4. Each pair is a dependency edge

    Args:
        jcl_results: List of parse results from JCLParser.parse_all()

    Returns:
        dict with:
            jobs: flat list of job/step/dataset records
            dependencies: list of producer->consumer edges
    """
    logger.info(f"Building JCL graph from {len(jcl_results)} jobs")

    # Build dataset index
    # producers[dsn] = list of job names that write this dataset
    # consumers[dsn] = list of job names that read this dataset
    producers = {}  # dsn -> [(job_name, disp)]
    consumers = {}  # dsn -> [(job_name, disp)]

    # Flat job records for jcl_job table
    job_records = []

    for job in jcl_results:
        if job.get("status") != "ok":
            continue

        job_name = job["job_name"]

        for step in job.get("steps", []):
            step_name   = step["step_name"]
            program     = step["program"]
            steplib     = step.get("steplib", "")
            parm        = step.get("parm", "")

            for ds in step.get("datasets", []):
                dd_name = ds["dd_name"]
                dsn     = ds.get("dsn", "")
                disp    = ds.get("disposition", "UNKNOWN")

                if not dsn:
                    continue

                # Normalize DSN — remove GDG suffix (+1, +0, -1)
                dsn_normalized = dsn.split("(")[0] if "(" in dsn else dsn

                # Add to job records
                record_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
                job_records.append({
                    "id":           record_id,
                    "job_name":     job_name,
                    "step_name":    step_name,
                    "program_name": program,
                    "dd_name":      dd_name,
                    "dataset_name": dsn,
                    "disposition":  disp,
                    "steplib":      steplib,
                    "parm":         parm,
                    "source_file":  job["source_file"],
                })

                # Track producers and consumers
                if disp in PRODUCER_DISPS:
                    if dsn_normalized not in producers:
                        producers[dsn_normalized] = []
                    producers[dsn_normalized].append((job_name, disp))

                elif disp in CONSUMER_DISPS:
                    if dsn_normalized not in consumers:
                        consumers[dsn_normalized] = []
                    consumers[dsn_normalized].append((job_name, disp))

    # Build dependency edges
    dependencies = []
    for dsn, producer_list in producers.items():
        if dsn in consumers:
            for prod_job, prod_disp in producer_list:
                for cons_job, cons_disp in consumers[dsn]:
                    # Don't create self-dependency
                    if prod_job == cons_job:
                        continue

                    dep_id = str(uuid_lib.uuid4()).replace("-", "")[:32]
                    dependencies.append({
                        "id":            dep_id,
                        "producer_job":  prod_job,
                        "consumer_job":  cons_job,
                        "dataset_name":  dsn,
                        "producer_disp": prod_disp,
                        "consumer_disp": cons_disp,
                    })

                    logger.debug(
                        f"Dependency: {prod_job} → {cons_job} "
                        f"via {dsn}"
                    )

    # Known business chains — documented in brief §10
    # These are sequential job chains not necessarily linked by datasets
    known_chains = [
        {
            "chain_name": "Daily Transaction Processing",
            "jobs": ["POSTTRAN", "INTCALC", "CREASTMT"],
            "description": "Post transactions -> Calculate interest -> Generate statements"
        }
    ]

    logger.info(
        f"JCL graph built: {len(job_records)} job records, "
        f"{len(dependencies)} dependency edges"
    )

    # Deduplicate dependencies by (producer, consumer, dataset)
    seen_deps = set()
    unique_deps = []
    for dep in dependencies:
        key = (dep["producer_job"], dep["consumer_job"], dep["dataset_name"])
        if key not in seen_deps:
            seen_deps.add(key)
            unique_deps.append(dep)

    logger.info(f"Unique dependencies after dedup: {len(unique_deps)}")

    return {
        "jobs":         job_records,
        "dependencies": unique_deps,
        "known_chains": known_chains,
    }


def save_jcl_graph(graph: dict, output_dir: Optional[Path] = None) -> Path:
    """
    Save JCL graph to JSON artifact.

    Args:
        graph:      Output from build_jcl_graph()
        output_dir: Output directory

    Returns:
        Path to saved artifact
    """
    output_dir = output_dir or (OUT_DIR / "artifacts" / "jcl")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "jcl_graph.json"
    artifact = {
        "layer":            "L4",
        "job_record_count": len(graph["jobs"]),
        "dependency_count": len(graph["dependencies"]),
        "jobs":             graph["jobs"],
        "dependencies":     graph["dependencies"],
        "known_chains":     graph.get("known_chains", []),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"JCL graph saved: {output_path}")
    return output_path
