# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Verifica il generatore di preset contro il preset vero salvato da Resolume.

1. la geometria sopravvive al giro scrivi/rileggi
2. il warper ricalca gli angoli della slice
3. il file generato ha la stessa forma di quello di Resolume (stessi tag e
   stessi parametri per slice): e' questo che decide se Resolume lo carica
"""
import json
import xml.etree.ElementTree as ET
from collections import Counter

import resolume_mapping as m

orig = m.read_setup()                      # le preferenze, cioe' lo stato attivo
tree = m.build(orig, "verifica")           # generato con lo stampo
ET.indent(tree, space="\t")
tmp = m.HERE / "verifica.xml"
tree.write(tmp, encoding="utf-8", xml_declaration=True)
back = m.read_setup(tmp)

worst = 0.0
for so, sb in zip(orig["screens"], back["screens"]):
    assert len(so["slices"]) == len(sb["slices"]), "numero di slice diverso"
    for a, b in zip(so["slices"], sb["slices"]):
        assert a["name"] == b["name"], (a["name"], b["name"])
        assert a["source"] == b["source"], (a["source"], b["source"])
        for k in ("input", "output"):
            for pa, pb in zip(a[k], b[k]):
                worst = max(worst, abs(pa[0] - pb[0]), abs(pa[1] - pb[1]))

got = ET.parse(tmp).getroot()
for sl in got.findall(".//Slice"):
    out = m._quad(sl.find("OutputRect"))
    if len(out) != 4:                      # poligono: il warper segue il contenitore
        out = m._bbox_quad(out)
    bez = m._quad(sl.find(".//BezierWarper/vertices"))
    assert len(bez) == 16, len(bez)
    for a, b in ((bez[0], out[0]), (bez[3], out[1]), (bez[15], out[2]), (bez[12], out[3])):
        worst = max(worst, abs(a[0] - b[0]), abs(a[1] - b[1]))


def shape(root):
    """impronta strutturale: quali tag e quali parametri, non i valori"""
    c = Counter()
    for el in root.iter():
        key = el.tag
        if el.get("name") and el.tag != "XmlState":  # il nome del preset cambia apposta
            key += f"[{el.get('name')}]"
        c[key] += 1
    return c


# si confronta UNA slice contro UNA slice dello stampo: il numero di slice e di
# vertici cambia apposta, la forma no
def prima_slice(root):
    s = shape(root.find(".//Slice"))
    del s["v"]
    return s


want, have = prima_slice(ET.parse(m.TEMPLATE).getroot()), prima_slice(got)
mancanti = {k: v for k, v in (want - have).items()}
inventati = {k: v for k, v in (have - want).items()}

print(json.dumps({
    "slice": sum(len(s["slices"]) for s in orig["screens"]),
    "scarto_massimo_px": worst,
    "tag_mancanti_rispetto_a_resolume": mancanti,
    "tag_inventati_da_noi": inventati,
}, indent=2, ensure_ascii=False))

tmp.unlink()
ok = worst < 1e-6 and not mancanti and not inventati
print("OK" if ok else "DA GUARDARE")
