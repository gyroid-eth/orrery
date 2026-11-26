"""Derive fixed asset routes from the bundled local model maker table."""

import json
from pathlib import Path


_source = Path(__file__).with_suffix(".js").read_text(encoding="utf-8")
_table = _source.split("window.OrreryLocalModelMakers = ", 1)[1].split(";\n", 1)[0]
LOCAL_MAKER_ASSETS = tuple(f"{maker}.svg" for maker in json.loads(_table))
