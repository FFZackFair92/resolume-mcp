# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Stampa la prima Mask di un preset, per intero, e riassume le altre."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

src = Path(sys.argv[1])
root = ET.parse(src).getroot()
masks = root.findall(".//layers/Mask")
print(f"{len(masks)} mask\n")

ET.indent(masks[0], space="  ")
print(ET.tostring(masks[0], encoding="unicode")[:4000])

print("\n--- riassunto ---")
for mk in masks:
    nome = "?"
    for p in mk.iter("Param"):
        if p.get("name") == "Name":
            nome = p.get("value")
            break
    pts = mk.find(".//Contour/points")
    seg = mk.find(".//Contour/segments")
    rect = mk.find("./ShapeObject/Rect")
    print(f"{nome:<16} punti={len(list(pts)) if pts is not None else 0:<3} "
          f"segmenti={len(list(seg)) if seg is not None else 0:<3} "
          f"rect={rect.attrib if rect is not None else None}")
