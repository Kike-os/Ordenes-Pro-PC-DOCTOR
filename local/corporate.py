"""Identidad documental centralizada; no contiene datos de órdenes."""
import json
from pathlib import Path

def settings():
    return json.loads((Path(__file__).resolve().parent/'data/corporate.json').read_text())

def terms_draft():
    return json.loads((Path(__file__).resolve().parent/'data/service-terms-draft.json').read_text())
