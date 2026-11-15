# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Inventario dei tag di un preset: serve a scoprire cosa esiste oltre le Slice."""
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("preset_template.xml")
root = ET.parse(src).getroot()

percorsi = Counter()


def scendi(el, path=""):
    p = f"{path}/{el.tag}"
    percorsi[p] += 1
    for c in el:
        if c.tag not in ("v",):
            scendi(c, p)


scendi(root)
for p, n in percorsi.items():
    if "/Params" in p or "/Param" in p or "ValueRange" in p or "Behaviour" in p or "Phase" in p:
        continue
    print(f"{n:>4}  {p}")
