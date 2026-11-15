# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Mappatura del palco Broken System, ricavata dalla foto stage.jpg.

  layer 1 -> i pannelli bianchi dell'arco in alto
  layer 2 -> le due torri di casse
  layer 3 -> i pannelli laterali

Le coordinate sono in PIXEL DELLA FOTO (945x710) e vengono scalate sullo
schermo di uscita. Why: cosi' i quad combaciano con lo sfondo dell'editor, che
disegna la foto stirata sul rettangolo dello schermo.

ATTENZIONE: questa foto e' scattata dal punto di vista di chi la scattava, non
del proiettore. Va benissimo per preparare la struttura (quante superfici, come
sono raggruppate, che layer va dove), ma la geometria esatta si rifa' sul posto
con calibra.py, dalla posizione vera del proiettore.

  uv run --script stage_broken.py [--preset NOME]
"""
import argparse
import json

import resolume_mapping as m

FOTO_W, FOTO_H = 945, 710

# --------------------------------------------------------------- le superfici
# ogni quad in ordine TL, TR, BR, BL, letto sulla foto

ARCO = [                                        # layer 1
    ("Arco 1 sx",     [[188, 133], [352, 121], [352, 238], [190, 232]]),
    ("Arco 2",        [[352, 141], [470, 137], [470, 248], [352, 238]]),
    ("Arco 3",        [[470, 137], [586, 143], [586, 250], [470, 248]]),
    ("Arco 4 dx",     [[586, 143], [703, 168], [700, 252], [586, 250]]),
]

CASSE = [                                       # layer 2
    ("Cassa sx alta", [[148, 243], [307, 243], [307, 357], [148, 357]]),
    ("Cassa sx bassa", [[120, 360], [293, 360], [291, 580], [122, 578]]),
    ("Cassa dx alta", [[578, 255], [713, 255], [713, 368], [578, 368]]),
    ("Cassa dx bassa", [[568, 372], [731, 372], [729, 578], [569, 576]]),
]

CENTRO = [                                      # layer 2, con le casse
    ("Centro",        [[334, 352], [558, 347], [562, 484], [330, 489]]),
]

LATERALI = [                                    # layer 3
    ("Laterale sx",   [[18, 132], [128, 127], [123, 372], [21, 366]]),
    ("Laterale dx",   [[735, 160], [846, 149], [839, 351], [731, 342]]),
]


GRUPPI = [(ARCO, 1), (CASSE, 2), (CENTRO, 2), (LATERALI, 3)]


def scala(quad, W, H):
    return [[round(x * W / FOTO_W, 1), round(y * H / FOTO_H, 1)] for x, y in quad]


def riquadro(quads):
    xs = [p[0] for q in quads for p in q]
    ys = [p[1] for q in quads for p in q]
    return min(xs), min(ys), max(xs), max(ys)


def adatta(quad, box, CW, CH):
    """Porta il quad da coordinate foto a coordinate composizione, stirando il
    riquadro occupato dalle superfici su TUTTA la composizione.

    Why: le superfici non coprono l'intera foto — sopra c'e' cielo, sotto sabbia.
    Senza questo passaggio un terzo dell'altezza della composizione non finirebbe
    su nessun pannello, e ci lavoreresti dentro senza vederlo mai.
    """
    x0, y0, x1, y1 = box
    return [[round((x - x0) * CW / (x1 - x0), 1),
             round((y - y0) * CH / (y1 - y0), 1)] for x, y in quad]


def costruisci(setup: dict, modo: str = "unico") -> dict:
    """modo 'unico'    -> il palco e' un solo schermo: ogni superficie prende la
                          PROPRIA porzione della composizione, e un'immagine sola
                          si spezza su tutti i pannelli.
       modo 'per-layer' -> stessa divisione, ma ogni gruppo legge il suo layer:
                          l'immagine del layer 1 si stende sui quattro pannelli
                          dell'arco, quella del layer 2 sulle casse, e cosi' via.
       modo 'copia'     -> ogni superficie ripete tutta la composizione.
    """
    sc = setup["screens"][0]
    W, H = sc["width"], sc["height"]
    CW, CH = setup["composition"]["width"], setup["composition"]["height"]
    tutta = [[0, 0], [CW, 0], [CW, CH], [0, CH]]

    # in 'unico' il riquadro e' quello di TUTTE le superfici: l'immagine e' una
    # sola e si spezza su tutto il palco. In 'per-layer' ogni gruppo ha il suo,
    # cosi' l'immagine di ogni layer si stende sul proprio gruppo.
    tutti = [q for gruppo, _ in GRUPPI for _, q in gruppo]
    box_globale = riquadro(tutti)

    slices = []
    for gruppo, layer in GRUPPI:
        box = box_globale if modo == "unico" else riquadro([q for _, q in gruppo])
        for nome, quad in gruppo:
            ingresso = tutta if modo == "copia" else adatta(quad, box, CW, CH)
            sorgente = "0:1" if modo == "unico" else f"3:{layer}"
            slices.append({"name": f"{nome} L{layer}",
                           "source": sorgente,
                           "input": ingresso,
                           "output": scala(quad, W, H)})
    return {"composition": setup["composition"],
            "screens": [{**{k: sc[k] for k in ("name", "device", "width", "height")},
                         "slices": slices}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default=None)
    ap.add_argument("--modo", default="unico", choices=["unico", "per-layer", "copia"],
                    help="come le superfici leggono la composizione")
    args = ap.parse_args()

    setup = m.read_setup()
    setup.pop("file", None)
    sc = setup["screens"][0]
    data = costruisci(setup, args.modo)
    preset = args.preset or m.active_preset() or "chat"
    dest = m.write_preset(data, preset)
    m.refresh_editor(json.loads(json.dumps(data)), sfondo=m.HERE / "stage.jpg")

    print(f"schermo {sc['width']}x{sc['height']}, "
          f"{len(data['screens'][0]['slices'])} superfici, modo '{args.modo}'")
    for s in data["screens"][0]["slices"]:
        xs = [p[0] for p in s["input"]]
        ys = [p[1] for p in s["input"]]
        print(f"  {s['name']:<18} sorgente {s['source']}  ingresso "
              f"{min(xs):.0f},{min(ys):.0f} -> {max(xs):.0f},{max(ys):.0f}")
    print(f"preset '{preset}' scritto: {dest}")


main()
