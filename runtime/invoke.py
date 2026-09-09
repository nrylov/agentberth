"""Executed only inside the sandbox (or explicitly by local developer tests)."""

import importlib.util
import json
import sys
from pathlib import Path

from runtime.context import Context

folder = Path(sys.argv[1])
request = json.loads((folder / "request.json").read_text())
spec = importlib.util.spec_from_file_location("tool_handler", folder / "handler.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.run(request, Context())
(folder / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
