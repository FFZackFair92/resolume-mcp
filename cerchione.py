# /// script
# requires-python = ">=3.14"
# dependencies = ["httpx>=0.27"]
# ///
"""Il cerchione vive nella composizione, non nell'output.

Ogni layer che ha in catena ShapeMask + RadialCloner diventa un cerchione da
solo: la maschera rende tondo il contenuto, il cloner lo moltiplica in cerchio.
Numero di copie, raggio, scala e rotazione sono parametri, quindi la geometria
cambia in tempo reale senza toccare nessun preset dell'Advanced Output.

I layer senza cloner restano a schermo pieno e fanno da sfondo.

  uv run --script cerchione.py figure
  uv run --script cerchione.py posa cerchione
  uv run --script cerchione.py vivo --figure cerchione,respiro,spirale
  uv run --script cerchione.py riposo

Stato condiviso col server MCP: job.json + stop.flag.
"""
import argparse
import json
import math
import os
import time
from pathlib import Path

import httpx

BASE = os.environ.get("RESOLUME_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
HERE = Path(__file__).resolve().parent
JOB, STOP = HERE / "job.json", HERE / "stop.flag"
http = httpx.Client(timeout=10.0)


# ---------------------------------------------------------------- il dialogo

def comp() -> dict:
    return http.get(BASE + "/composition").json()


def scrivi(corpo: dict) -> None:
    r = http.put(BASE + "/composition", json=corpo)
    if r.status_code >= 400:
        raise RuntimeError(f"PUT /composition -> {r.status_code}: {r.text[:300]}")


def unisci(a: dict, b: dict) -> dict:
    """Fonde due corpi parziali. Serve perche' in un tick tocchiamo piu'
    effetti dello stesso layer e vogliamo mandare comunque un solo PUT."""
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


def corpo_effetto(layer: int, effetto: int, params: dict) -> dict:
    """Gli array vanno riempiti di {} fino all'indice voluto: e' il merge
    parziale di Resolume, l'unico modo di scrivere in questa versione."""
    return {"layers": [{} for _ in range(layer)] + [
        {"video": {"effects": [{} for _ in range(effetto)] + [
            {"params": {k: {"value": v} for k, v in params.items()}}]}}]}


def corpo_transform(layer: int, params: dict) -> dict:
    return corpo_effetto(layer, 0, params)      # il Transform di serie e' sempre effects[0]


# ---------------------------------------------------------------- le figure
# Ognuna dice, data la fase t (0..1 per giro) e la posizione k del layer fra i
# cerchioni, come stanno maschera e cloner. Niente coordinate: qui si ragiona
# per raggio, numero di copie e rotazione, che e' il linguaggio del cloner.

def grado(x: float) -> float:
    """Master Rotation vive fra -180 e 180: gli angoli vanno riportati li'."""
    return (x + 180.0) % 360.0 - 180.0


def sfasa(k: int, cloni: int) -> float:
    """Il secondo cerchione cade a meta' passo del primo: e' cosi' che i
    contenuti si alternano lungo l'anello invece di sovrapporsi."""
    return k * (360.0 / cloni) / 2.0


def cerchione(t, k, cloni):
    return {"mask": {"Shape": "Circle", "Scale": 62, "Feather": 10},
            "cloner": {"Clones": cloni, "Fan": 100, "Fan Offset": 0,
                       "Start Radius": 0.62, "End Radius": 0.62,
                       "Start Scale": 34, "End Scale": 34,
                       "Start Rotation": 0, "End Rotation": 360,
                       "Master Rotation": grado(t * 360 + sfasa(k, cloni))}}


def respiro(t, k, cloni):
    r = 0.32 + 0.34 * (0.5 + 0.5 * math.sin(2 * math.pi * t))
    s = 26 + 16 * (0.5 + 0.5 * math.sin(2 * math.pi * t))
    return {"mask": {"Shape": "Circle", "Scale": 62, "Feather": 22},
            "cloner": {"Clones": cloni, "Fan": 100, "Fan Offset": 0,
                       "Start Radius": r, "End Radius": r,
                       "Start Scale": s, "End Scale": s,
                       "Start Rotation": 0, "End Rotation": 360,
                       "Master Rotation": grado(sfasa(k, cloni))}}


def spirale(t, k, cloni):
    """Raggio e scala crescono lungo la sequenza: non un anello, una chiocciola."""
    return {"mask": {"Shape": "Circle", "Scale": 58, "Feather": 14},
            "cloner": {"Clones": max(cloni, 8), "Fan": 100, "Fan Offset": 0,
                       "Start Radius": 0.12, "End Radius": 0.92,
                       "Start Scale": 12, "End Scale": 46,
                       "Start Rotation": 0, "End Rotation": 360,
                       "Master Rotation": grado(t * 360 * 0.5 + sfasa(k, cloni))}}


def ventaglio(t, k, cloni):
    """Il cerchio si chiude a ventaglio e si riapre: l'anello diventa un arco."""
    f = 18 + 82 * (0.5 + 0.5 * math.sin(2 * math.pi * t))
    return {"mask": {"Shape": "Circle", "Scale": 62, "Feather": 10},
            "cloner": {"Clones": cloni, "Fan": f, "Fan Offset": 0,
                       "Start Radius": 0.66, "End Radius": 0.66,
                       "Start Scale": 30, "End Scale": 30,
                       "Start Rotation": 0, "End Rotation": 360,
                       "Master Rotation": grado(t * 180 + sfasa(k, cloni))}}


def caos(t, k, cloni):
    """Orbite sfasate: raggio, ventaglio e rotazione battono a periodi diversi,
    cosi' la figura non torna mai uguale a se stessa."""
    r = 0.30 + 0.45 * abs(math.sin(2 * math.pi * (t * 1.3 + k * 0.31)))
    f = 40 + 60 * abs(math.sin(2 * math.pi * (t * 0.7 + k * 0.17)))
    return {"mask": {"Shape": "Circle", "Scale": 55,
                     "Feather": 6 + 40 * abs(math.sin(2 * math.pi * t * 2.1))},
            "cloner": {"Clones": cloni, "Fan": f,
                       "Fan Offset": 100 * ((t * 0.9 + k * 0.4) % 1.0),
                       "Start Radius": r, "End Radius": r * 0.75,
                       "Start Scale": 34, "End Scale": 22,
                       "Start Rotation": 0, "End Rotation": 360,
                       "Master Rotation": grado(t * 720 * (1 + k * 0.4))}}


FIGURE = {"cerchione": cerchione, "respiro": respiro, "spirale": spirale,
          "ventaglio": ventaglio, "caos": caos}


# ---------------------------------------------------------------- il motore

def catena(c: dict) -> list[dict]:
    """Chi puo' fare il cerchione e con quali indici di effetto.

    Gli indici NON si danno per scontati: dipendono da quanti effetti c'erano
    gia' sul layer, e cambiano appena l'utente ne aggiunge o toglie uno.
    """
    fuori = []
    for i, L in enumerate(c["layers"]):
        # JSON grezzo: gli effetti stanno in video.effects, come oggetti con 'name'
        eff = [e.get("name") for e in (L.get("video") or {}).get("effects") or []]
        fuori.append({
            "layer": i,
            "mask": eff.index("ShapeMask") if "ShapeMask" in eff else None,
            "cloner": eff.index("RadialCloner") if "RadialCloner" in eff else None,
        })
    return fuori


def posa(figura: str, t: float, cloni: float, catene: list[dict]) -> None:
    f = FIGURE[figura]
    attivi = [c for c in catene if c["cloner"] is not None]
    corpo: dict = {}
    for c in catene:
        # ogni layer parte da un Transform neutro: qui comanda il cloner
        unisci(corpo, corpo_transform(c["layer"], {
            "Position X": 0.0, "Position Y": 0.0, "Scale": 100.0, "Rotation Z": 0.0}))
    for k, c in enumerate(attivi):
        stato = f(t, k, int(cloni))
        if c["mask"] is not None:
            unisci(corpo, corpo_effetto(c["layer"], c["mask"], stato["mask"]))
        unisci(corpo, corpo_effetto(c["layer"], c["cloner"], stato["cloner"]))
    scrivi(corpo)


def battito(nota: str) -> None:
    tmp = JOB.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mode": "cerchione", "pid": os.getpid(),
                               "note": nota, "last_tick": time.time()}), encoding="utf-8")
    os.replace(tmp, JOB)


def vivo(figure: list[str], cloni: int, giro: float, tick: float) -> None:
    c = comp()
    catene = catena(c)
    attivi = [x for x in catene if x["cloner"] is not None]
    if not attivi:
        raise SystemExit("nessun layer ha un RadialCloner in catena: "
                         "aggiungilo a mano in Resolume e riprova")
    bpm = float(c.get("bpm") or 120.0)
    sec_giro = giro * 4 * 60.0 / bpm
    print(f"{len(attivi)} cerchioni, {cloni} copie ciascuno, {bpm:g} bpm, "
          f"un giro ogni {sec_giro:.1f}s")
    STOP.unlink(missing_ok=True)
    t0 = time.time()
    try:
        while not STOP.exists():
            passato = time.time() - t0
            t = (passato / sec_giro) % 1.0
            fig = figure[int(passato / (sec_giro * 2)) % len(figure)]
            posa(fig, t, cloni, catene)
            battito(f"{fig}, giro {passato / sec_giro:.1f}")
            time.sleep(tick)
    finally:
        # il set deve restare utilizzabile comunque vada: fermandosi a meta'
        # figura lascerebbe cloni e maschere dove capita
        riposo()
    battito("fermato")
    print("fermato")


def riposo() -> None:
    """Rimette tutto com'era: cloner a una copia sola, maschera spenta,
    Transform neutro. Cosi' il set torna utilizzabile a mano."""
    catene = catena(comp())
    corpo: dict = {}
    for c in catene:
        unisci(corpo, corpo_transform(c["layer"], {
            "Position X": 0.0, "Position Y": 0.0, "Scale": 100.0, "Rotation Z": 0.0}))
        if c["cloner"] is not None:
            unisci(corpo, corpo_effetto(c["layer"], c["cloner"], {
                "Clones": 1, "Start Radius": 0.0, "End Radius": 0.0,
                "Start Scale": 100, "End Scale": 100, "Master Rotation": 0}))
        if c["mask"] is not None:
            unisci(corpo, corpo_effetto(c["layer"], c["mask"], {"Opacity": 0.0}))
    scrivi(corpo)
    print("layer rimessi a schermo pieno")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("comando", choices=["figure", "catena", "posa", "vivo", "riposo"])
    ap.add_argument("nome", nargs="?", default="cerchione")
    ap.add_argument("--cloni", type=int, default=5, help="copie per cerchione (1-50)")
    ap.add_argument("--giro", type=float, default=8.0, help="battute per giro")
    ap.add_argument("--tick", type=float, default=0.08, help="secondi fra un PUT e l'altro")
    ap.add_argument("--figure", default=None, help="lista separata da virgole")
    args = ap.parse_args()

    if args.comando == "figure":
        print(json.dumps(list(FIGURE), ensure_ascii=False))
    elif args.comando == "catena":
        print(json.dumps(catena(comp()), indent=2))
    elif args.comando == "riposo":
        riposo()
    elif args.comando == "posa":
        catene = catena(comp())
        posa(args.nome, 0.0, args.cloni, catene)
        attivi = sum(1 for c in catene if c["cloner"] is not None)
        print(f"figura '{args.nome}' posata su {attivi} cerchioni")
    else:
        figure = (args.figure or args.nome).split(",")
        for f in figure:
            if f not in FIGURE:
                raise SystemExit(f"figura sconosciuta: {f} (ho {list(FIGURE)})")
        vivo(figure, args.cloni, args.giro, args.tick)


main()
