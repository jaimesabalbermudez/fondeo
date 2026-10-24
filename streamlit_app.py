"""Punto de entrada para Streamlit Community Cloud (el paquete vive en src/)."""

import runpy
import sys
from pathlib import Path

SRC = Path(__file__).parent / "src"
sys.path.insert(0, str(SRC))
runpy.run_path(str(SRC / "fondeos_sim" / "dashboard.py"), run_name="__main__")
