"""Run the whole pipeline: download (cached) -> sites -> panel -> estimates -> figures -> demo.

    python run_all.py            # uses cached raw data if present
    python run_all.py --refresh  # re-download from the City of Chicago data portal
"""
import runpy
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SRC))

for step in ["download", "sites", "panel", "estimate", "figures", "demo"]:
    print(f"\n=== {step} ===", flush=True)
    runpy.run_path(str(SRC / f"{step}.py"), run_name="__main__")
