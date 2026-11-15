# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Sposta la slice piu' a sinistra in modo inequivocabile, per vedere se il
preset scritto da noi arriva davvero a schermo. Reversibile: 'ripristina'."""
import json
import sys
from pathlib import Path

import resolume_mapping as m

HERE = m.HERE
SNAP = HERE / "mapping_originale.json"


def salva_originale(data):
    if not SNAP.exists():
        SNAP.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"originale messo da parte in {SNAP.name}")


def main():
    preset = m.active_preset()
    data = m.read_setup()
    data.pop("file", None)
    salva_originale(data)

    if len(sys.argv) > 1 and sys.argv[1] == "ripristina":
        data = json.loads(SNAP.read_text(encoding="utf-8"))
        print("rimetto la mappatura originale")
    else:
        sl = min(data["screens"][0]["slices"],
                 key=lambda s: min(p[0] for p in s["output"]))
        sl["name"] = "PROVA CHAT"
        # meta' altezza e spostata in alto: impossibile non accorgersene
        xs = [p[0] for p in sl["output"]]
        ys = [p[1] for p in sl["output"]]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        h = (y1 - y0) / 2
        sl["output"] = [[x0, y0 - 200], [x1, y0 - 200], [x1, y0 - 200 + h], [x0, y0 - 200 + h]]
        print(f"slice '{sl['name']}' spostata: {sl['output']}")

    dest = m.write_preset(data, preset)
    print(f"scritto in {dest}")
    m.refresh_editor(json.loads(json.dumps(data)))
    print("editor riallineato")


main()
