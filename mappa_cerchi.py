# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Cinque cerchi disposti a cerchione, piu' uno sfondo a tutto schermo.

Le slice di Resolume sono quadrilateri e basta: la rotondita' la fanno le Mask,
che invece hanno un contorno bezier. Quindi ogni cerchio e' una coppia
  Slice quadrata (il contenuto)  +  Mask tonda (il ritaglio)

  cerchi -> layer 1 e layer 2 alternati, ognuno che pesca un pezzo diverso
            della composizione (lo sfalsamento)
  sfondo -> layer 3, tutta la composizione su tutto lo schermo

  uv run --script mappa_cerchi.py [--maschere-in-cima] [--sfondo-sopra] [--preset NOME]
"""
import argparse
import json
import math

import resolume_mapping as m


def costruisci(setup: dict, sfondo_sotto: bool) -> dict:
    sc = setup["screens"][0]
    W, H = sc["width"], sc["height"]
    CW, CH = setup["composition"]["width"], setup["composition"]["height"]

    N = 5
    R = min(W, H) * 0.30           # raggio del cerchione
    r = R * 0.55                   # ogni cerchio: 2*R*sin(36°)/2 = 0.588R, quasi a contatto
    cx, cy = W / 2, H / 2

    # ogni cerchio pesca una finestra quadrata diversa della composizione: e' lo
    # "sfalsato". Finestra alta quanto la composizione, che scorre da sinistra a destra.
    lato = CH
    passo = (CW - lato) / (N - 1) if N > 1 else 0

    slices, tondi = [], []
    for i in range(N):
        a = -math.pi / 2 + 2 * math.pi * i / N
        px, py = cx + R * math.cos(a), cy + R * math.sin(a)
        layer = 1 if i % 2 == 0 else 2
        fx = passo * i
        slices.append({
            "name": f"Cerchio {i+1} L{layer}",
            "source": f"3:{layer}",
            "input": [[fx, 0], [fx + lato, 0], [fx + lato, CH], [fx, CH]],
            "output": [[px - r, py - r], [px + r, py - r], [px + r, py + r], [px - r, py + r]],
        })
        tondi.append([px, py, r])

    # UNA sola maschera con cinque contorni. Why: ogni maschera taglia tutto
    # quello che le sta sotto nella lista, quindi cinque maschere separate si
    # intersecano e resta un cerchio solo (verificato a schermo il 2026-08-25).
    maschera = {"kind": "mask", "name": "Cinque tondi", "circles": tondi}

    sfondo = {
        "name": "Sfondo L3",
        "source": "3:3",
        "input": [[0, 0], [CW, 0], [CW, CH], [0, CH]],
        "output": [[0, 0], [W, 0], [W, H], [0, H]],
    }

    # lo sfondo sta SOPRA la maschera per non venire ritagliato anche lui
    ordine = [maschera] + slices + [sfondo] if sfondo_sotto else [sfondo, maschera] + slices

    return {"composition": setup["composition"],
            "screens": [{**{k: sc[k] for k in ("name", "device", "width", "height")},
                         "slices": ordine}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sfondo-sotto", action="store_true",
                    help="mette lo sfondo in fondo alla lista: da provare se lo sfondo "
                         "copre i cerchi invece di stargli dietro")
    ap.add_argument("--preset", default=None)
    args = ap.parse_args()

    setup = m.read_setup()
    setup.pop("file", None)
    sc = setup["screens"][0]
    print(f"schermo: {sc['name']} -> {sc['device']} ({sc['device_type']}) "
          f"{sc['width']}x{sc['height']}")

    data = costruisci(setup, args.sfondo_sotto)
    preset = args.preset or m.active_preset() or "chat"
    dest = m.write_preset(data, preset)
    m.refresh_editor(json.loads(json.dumps(data)))

    print(f"\n{len(data['screens'][0]['slices'])} elementi -> {dest}")
    for s in data["screens"][0]["slices"]:
        tipo = "mask " if s.get("kind") == "mask" else "slice"
        print(f"  {tipo} {s['name']:<16} {s.get('source','-')}")


main()
