# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Anima cupa per tekno mental a 170 bpm.

Tutto quello che serve e' gia' nella catena master della composizione:
ShiftRGB, HueRotate, WaveWarp, Flip, PolarKaleido, MirrorQuad, TwitchEffect,
Trails. Questo motore li suona a battute invece di lasciarli fermi.

Il buio non si fa abbassando la luce: si fa togliendo il colore (HueRotate
Sat. Scale a zero), tenendo le opacita' basse e lasciando lunghi tratti quasi
neri, cosi' quando arriva l'assalto fa male.

  uv run --script cupo.py sezioni
  uv run --script cupo.py posa assalto
  uv run --script cupo.py vivo
  uv run --script cupo.py riposo

Stato condiviso col server MCP: job.json + stop.flag.
"""
import argparse
import json
import math
import os
import random
import time
from pathlib import Path

import httpx

BASE = os.environ.get("RESOLUME_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
HERE = Path(__file__).resolve().parent
JOB, STOP = HERE / "job.json", HERE / "stop.flag"
http = httpx.Client(timeout=10.0)


def comp() -> dict:
    return http.get(BASE + "/composition").json()


def scrivi(corpo: dict) -> None:
    r = http.put(BASE + "/composition", json=corpo)
    if r.status_code >= 400:
        raise RuntimeError(f"PUT /composition -> {r.status_code}: {r.text[:300]}")


def unisci(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            unisci(a[k], v)
        elif isinstance(v, list) and isinstance(a.get(k), list):
            while len(a[k]) < len(v):
                a[k].append({})
            for i, el in enumerate(v):
                if isinstance(el, dict) and isinstance(a[k][i], dict):
                    unisci(a[k][i], el)
                elif el:
                    a[k][i] = el
        else:
            a[k] = v
    return a


def catena_master(c: dict) -> dict:
    """Indice di ogni effetto master, per nome. Non si danno per scontati:
    basta che l'utente ne sposti uno e gli indici cambiano tutti."""
    eff = (c.get("video") or {}).get("effects") or []
    return {e.get("name"): i for i, e in enumerate(eff)}


def master(indice: int, params: dict) -> dict:
    return {"video": {"effects": [{} for _ in range(indice)] +
                      [{"params": {k: {"value": v} for k, v in params.items()}}]}}


def layer_opacita(i: int, v: float) -> dict:
    return {"layers": [{} for _ in range(i)] + [{"video": {"opacity": {"value": v}}}]}


# ---------------------------------------------------------------- le sezioni
# Ognuna riceve b = battiti trascorsi (frazionari) e restituisce lo stato:
#   master   parametri della catena della composizione, per nome di effetto
#   opacita  opacita' della composizione (e' qui che vive lo strobo)
#   layer    opacita' dei singoli layer

def porta(b: float, per_battito: float, apertura: float) -> bool:
    """Un cancello ritmico: aperto per una frazione di ogni suddivisione.
    per_battito=8 e apertura=0.35 -> ottavi secchi, aperti un terzo del tempo."""
    return (b * per_battito) % 1.0 < apertura


def buio(b):
    """Quasi nero. Il colore non c'e', il movimento e' lento, le scie sbavano.
    Serve a far sembrare enorme quello che viene dopo."""
    respiro = 0.5 + 0.5 * math.sin(2 * math.pi * b / 32)
    return {
        "master": {
            "HueRotate": {"Sat. Scale": 0.0, "Hue Rotate": 0.0},
            "WaveWarp": {"Height": 0.04 + 0.10 * respiro, "Width": 0.8,
                         "Speed": 0.03, "Angle": 0.5},
            "ShiftRGB": {"Distance": 0.0},
            "TwitchEffect": {"Global Twitch": 0.0},
            "Trails": {"Feedback": 0.55 + 0.2 * respiro},
            "PolarKaleido": {"Opacity": 0.0},
            "MirrorQuad": {"Opacity": 0.0},
        },
        "opacita": 0.30 + 0.10 * respiro,
        "layer": [0.55, 0.30, 0.22],
    }


def pressione(b):
    """Il glitch entra ma resta sotto. Lo ShiftRGB pulsa sul quarto."""
    colpo = max(0.0, 1.0 - (b % 1.0) * 3.0)          # attacco secco a ogni battito
    return {
        "master": {
            "HueRotate": {"Sat. Scale": 0.06, "Hue Rotate": 0.0},
            "WaveWarp": {"Height": 0.10, "Width": 0.45, "Speed": 0.18, "Angle": 0.5},
            "ShiftRGB": {"Distance": 0.05 + 0.35 * colpo, "R": 0.4, "B": -0.4},
            "TwitchEffect": {"Global Twitch": 0.18, "Max Light": 0.35,
                             "Light Frequency": 0.5, "Max RGB Shift": 0.8},
            "Trails": {"Feedback": 0.30},
            "PolarKaleido": {"Opacity": 0.0},
            "MirrorQuad": {"Opacity": 0.0},
        },
        "opacita": 0.72,
        "layer": [0.85, 0.55, 0.40],
    }


def assalto(b):
    """Strobo sugli ottavi, glitch al massimo, specchiature che sbattono.
    L'opacita' e' un cancello: o tutto o niente, niente sfumature."""
    acceso = porta(b, 8, 0.42)
    return {
        "master": {
            "HueRotate": {"Sat. Scale": 0.0},
            "WaveWarp": {"Height": 0.22, "Width": 0.25, "Speed": 0.6, "Angle": 0.5},
            "ShiftRGB": {"Distance": 0.55, "R": 0.9, "B": -0.9},
            "TwitchEffect": {"Global Twitch": 0.72, "Max Light": 0.9,
                             "Light Frequency": 1.0, "Max RGB Shift": 1.0,
                             "Max Pos X": 0.25, "Pos Frequency": 0.9,
                             "Max Scale": 0.4, "Scale Frequency": 0.8},
            "Trails": {"Feedback": 0.12},
            "MirrorQuad": {"Opacity": 0.7 if porta(b, 1, 0.5) else 0.0},
            "PolarKaleido": {"Opacity": 0.0},
        },
        "opacita": 1.0 if acceso else 0.0,
        "layer": [1.0, 0.9, 0.75],
    }


def vuoto(b):
    """Nero pieno, rotto da un lampo singolo sul primo movimento di ogni battuta.
    E' la parte 'mental': l'occhio cerca qualcosa e non lo trova."""
    lampo = porta(b, 0.25, 0.06)                     # una battuta intera fra un lampo e l'altro
    return {
        "master": {
            "HueRotate": {"Sat. Scale": 0.0},
            "WaveWarp": {"Height": 0.0, "Speed": 0.0},
            "ShiftRGB": {"Distance": 0.9 if lampo else 0.0, "R": 1.0, "B": -1.0},
            "TwitchEffect": {"Global Twitch": 1.0 if lampo else 0.0,
                             "Max Light": 1.0, "Light Frequency": 1.0},
            "Trails": {"Feedback": 0.0},
            "PolarKaleido": {"Opacity": 0.0},
            "MirrorQuad": {"Opacity": 0.0},
        },
        "opacita": 1.0 if lampo else 0.0,
        "layer": [1.0, 0.8, 0.6],
    }


def caleido(b):
    """Il momento allucinato: kaleidoscopio polare che ruota e si moltiplica,
    ancora in bianco e nero. Rompe la geometria del palco senza accendere colore."""
    return {
        "master": {
            "HueRotate": {"Sat. Scale": 0.10, "Hue Rotate": (b / 64) % 1.0},
            "WaveWarp": {"Height": 0.14, "Width": 0.3, "Speed": 0.35, "Angle": 0.5},
            "ShiftRGB": {"Distance": 0.2, "R": 0.6, "B": -0.6},
            "TwitchEffect": {"Global Twitch": 0.25, "Max Light": 0.4,
                             "Light Frequency": 0.7},
            "Trails": {"Feedback": 0.45},
            "PolarKaleido": {"Opacity": 0.85,
                             "Parts": 2 + 6 * (0.5 + 0.5 * math.sin(2 * math.pi * b / 48)),
                             "Rings": 1 + 3 * (0.5 + 0.5 * math.sin(2 * math.pi * b / 37)),
                             "Angle": (b / 96) % 1.0},
            "MirrorQuad": {"Opacity": 0.0},
        },
        "opacita": 0.80 if porta(b, 4, 0.75) else 0.25,
        "layer": [0.95, 0.7, 0.5],
    }


SEZIONI = {"buio": buio, "pressione": pressione, "assalto": assalto,
           "vuoto": vuoto, "caleido": caleido}

# l'ordine di un set: si scava, si carica, si colpisce, si toglie tutto
PERCORSO = ["buio", "pressione", "assalto", "pressione", "caleido",
            "assalto", "vuoto", "assalto"]


# ---------------------------------------------------------------- il motore

# clip del deck Generators che reggono il buio: niente volti sorridenti
CLIP_CUPE = {1: [3, 4, 1], 2: [4, 1, 2], 3: [3, 2, 1]}   # layer -> colonne, in ordine


def connetti(layer: int, colonna: int) -> None:
    http.post(f"{BASE}/composition/layers/{layer}/clips/{colonna}/connect")


def spegni_cloni(c: dict) -> dict:
    """Il cerchione serviva a un'altra scena: qui i layer devono riempire le
    superfici del palco, quindi una copia sola e maschera trasparente."""
    corpo: dict = {}
    for i, L in enumerate(c["layers"]):
        eff = [e.get("name") for e in (L.get("video") or {}).get("effects") or []]
        if "RadialCloner" in eff:
            j = eff.index("RadialCloner")
            unisci(corpo, {"layers": [{} for _ in range(i)] + [{"video": {"effects":
                   [{} for _ in range(j)] + [{"params": {"Clones": {"value": 1},
                                                         "Start Radius": {"value": 0.0},
                                                         "End Radius": {"value": 0.0},
                                                         "Start Scale": {"value": 100},
                                                         "End Scale": {"value": 100}}}]}}]})
        if "ShapeMask" in eff:
            j = eff.index("ShapeMask")
            unisci(corpo, {"layers": [{} for _ in range(i)] + [{"video": {"effects":
                   [{} for _ in range(j)] + [{"params": {"Opacity": {"value": 0.0}}}]}}]})
    return corpo


def applica(stato: dict, indici: dict, n_layer: int) -> None:
    corpo: dict = {"video": {"opacity": {"value": round(stato["opacita"], 4)}}}
    for nome, params in stato["master"].items():
        if nome in indici:
            unisci(corpo, master(indici[nome], params))
    for i, v in enumerate(stato["layer"][:n_layer]):
        unisci(corpo, layer_opacita(i, round(v, 4)))
    scrivi(corpo)


def battito(nota: str) -> None:
    tmp = JOB.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mode": "cupo", "pid": os.getpid(), "note": nota,
                               "last_tick": time.time()}), encoding="utf-8")
    os.replace(tmp, JOB)


def vivo(battute: float, tick: float, percorso: list[str]) -> None:
    c = comp()
    indici = catena_master(c)
    n_layer = len(c["layers"])
    bpm = float(c.get("bpm") or 170.0)
    mancanti = [n for n in ("ShiftRGB", "HueRotate", "WaveWarp", "TwitchEffect", "Trails")
                if n not in indici]
    if mancanti:
        print(f"nota: mancano dalla catena master {mancanti} — quelle parti restano ferme")
    print(f"{bpm:g} bpm, sezione ogni {battute:g} battute "
          f"({battute * 4 * 60 / bpm:.1f}s), {n_layer} layer")
    print("percorso: " + " -> ".join(percorso))

    scrivi(spegni_cloni(c))
    STOP.unlink(missing_ok=True)
    t0 = ultimo_battito = time.time()
    sezione_prec = None
    try:
        ciclo(t0, ultimo_battito, bpm, battute, tick, percorso, indici, n_layer)
    finally:
        # QUALUNQUE cosa succeda - stop, errore, chiusura - il set torna
        # utilizzabile. Senza questo il motore si ferma dentro un cancello di
        # strobo e lascia l'opacita' a zero: Resolume riapre su un set nero e
        # sembra rotto. Successo davvero il 2026-08-25.
        riposo()


def ciclo(t0, ultimo_battito, bpm, battute, tick, percorso, indici, n_layer) -> None:
    sezione_prec = None
    while not STOP.exists():
        b = (time.time() - t0) * bpm / 60.0                 # battiti trascorsi
        # attenzione alle unita': b sono battiti, le sezioni durano BATTUTE (4/4)
        quale = percorso[int(b // (battute * 4)) % len(percorso)]
        if quale != sezione_prec:
            sezione_prec = quale
            for layer, colonne in CLIP_CUPE.items():
                if layer <= n_layer:
                    connetti(layer, random.choice(colonne))
            battito(f"{quale} — battuta {b / 4:.0f}")
        applica(SEZIONI[quale](b), indici, n_layer)
        if time.time() - ultimo_battito >= 1.0:      # il segnale di vita basta al secondo
            ultimo_battito = time.time()
            battito(f"{quale} — battuta {b / 4:.0f}")
        time.sleep(tick)
    battito("fermato")
    print("fermato")


def riposo() -> None:
    """Rimette la catena master a riposo e riaccende tutto: il set torna
    utilizzabile a mano senza dover ricaricare niente."""
    c = comp()
    indici = catena_master(c)
    stato = {
        "master": {
            "HueRotate": {"Sat. Scale": 0.5, "Hue Rotate": 0.0},
            "WaveWarp": {"Height": 0.0, "Speed": 0.0},
            "ShiftRGB": {"Distance": 0.0, "R": 0.0, "B": 0.0},
            "TwitchEffect": {"Global Twitch": 0.0},
            "Trails": {"Feedback": 0.0},
            "PolarKaleido": {"Opacity": 0.0},
            "MirrorQuad": {"Opacity": 0.0},
        },
        "opacita": 1.0,
        "layer": [1.0] * len(c["layers"]),
    }
    applica(stato, indici, len(c["layers"]))
    print("catena master a riposo, opacita' riaperte")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["sezioni", "posa", "vivo", "riposo", "catena"])
    ap.add_argument("nome", nargs="?", default="assalto")
    ap.add_argument("--battute", type=float, default=16.0, help="durata di una sezione")
    ap.add_argument("--tick", type=float, default=0.02, help="secondi fra un PUT e l'altro")
    ap.add_argument("--percorso", default=None, help="lista separata da virgole")
    args = ap.parse_args()

    if args.comando == "sezioni":
        print(json.dumps({"sezioni": list(SEZIONI), "percorso": PERCORSO}, indent=2))
    elif args.comando == "catena":
        print(json.dumps(catena_master(comp()), indent=2))
    elif args.comando == "riposo":
        riposo()
    elif args.comando == "posa":
        c = comp()
        applica(SEZIONI[args.nome](0.0), catena_master(c), len(c["layers"]))
        print(f"sezione '{args.nome}' posata")
    else:
        percorso = (args.percorso or ",".join(PERCORSO)).split(",")
        for s in percorso:
            if s not in SEZIONI:
                raise SystemExit(f"sezione sconosciuta: {s} (ho {list(SEZIONI)})")
        vivo(args.battute, args.tick, percorso)


main()
