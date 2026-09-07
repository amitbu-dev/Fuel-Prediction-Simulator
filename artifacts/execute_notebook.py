"""Execute the notebook with the project's Python kernel and refresh its outputs."""

from pathlib import Path
import os
import sys

import nbformat
from nbclient import NotebookClient

root = Path(__file__).resolve().parents[1]
runtime = root / "artifacts" / "jupyter-runtime"
runtime.mkdir(exist_ok=True)
os.environ["JUPYTER_RUNTIME_DIR"] = str(runtime)
path = root / "fuel_prediction_poc.ipynb"
notebook = nbformat.read(path, as_version=4)
client = NotebookClient(
    notebook, timeout=180, kernel_name="python3",
    resources={"metadata": {"path": str(root)}},
)
client.create_kernel_manager()
client.km.kernel_spec.argv = [
    sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}",
]
print("Executing with", sys.executable, flush=True)
client.execute()
nbformat.write(notebook, path)
print("Notebook executed and saved:", len(notebook.cells), "cells")
for index, cell in enumerate(notebook.cells):
    if cell.cell_type == "code":
        for output in cell.get("outputs", []):
            if output.output_type == "stream":
                print("CELL", index, output.text)
            elif output.output_type == "error":
                raise RuntimeError(output)
