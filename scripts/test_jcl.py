import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers.jcl_parser import JCLParser

parser = JCLParser()

for jcl_name in ["POSTTRAN.jcl", "INTCALC.jcl", "CREASTMT.JCL"]:
    result = parser.parse(Path(f"corpus/app/jcl/{jcl_name}"))
    print(f"\n{'='*50}")
    print(f"JOB: {result['job_name']}  ({result['step_count']} steps)")
    for step in result["steps"]:
        print(f"  STEP: {step['step_name']}  PGM={step['program']}")
        if step["steplib"]:
            print(f"    STEPLIB: {step['steplib']}")
        for ds in step["datasets"]:
            print(f"    DD={ds['dd_name']:<12} DISP={ds['disposition']:<8} DSN={ds['dsn']}")
