# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Motore di automazione per Resolume Arena 7 (REST API).

Gira da solo, anche a Claude chiuso. Comandi:

    python resolume_auto.py snapshot scene.json     salva lo stato come scena
    python resolume_auto.py restore  scene.json     richiama una scena
    python resolume_auto.py record   set.jsonl      registra le mosse finche' non lo fermi
    python resolume_auto.py play     set.jsonl [--loop]   riproduce le mosse registrate
    python resolume_auto.py auto     config.json    pilota automatico generativo

Stato condiviso con il server MCP (stessa cartella dello script):
  job.json    scritto dal job in corso (mode, pid, avvio, ultimo tick, nota)
  stop.flag   crearlo ferma il job in modo pulito
"""
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx

BASE = os.environ.get("RESOLUME_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
HERE = Path(__file__).resolve().parent
JOB, STOP = HERE / "job.json", HERE / "stop.flag"
http = httpx.Client(timeout=10.0)

INDEXED = re.compile(r"^([^\[]+)\[(\d+)\]")
CLIP_CONNECTED = re.compile(r"^layers\[(\d+)\][^/]*/clips\[(\d+)\][^/]*/connected$")
# rumore che non ha senso registrare o rimettere in una scena
SKIP = ("/name", "/selected", "/colorid", "/thumbnail", "/dashboard/",
        "/transport/", "/audio/", "/description", "columns[", "decks[",
        # i layer dentro un gruppo compaiono anche in "layers": qui sono doppioni,
        # e il loro "connected" e' read-only (le clip si lanciano via POST)
        "/layergroups")


def get_composition() -> dict:
    r = http.get(BASE + "/composition")
    r.raise_for_status()
    return r.json()


def put(body: dict) -> None:
    r = http.put(BASE + "/composition", json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"PUT /composition -> {r.status_code}: {r.text[:300]}")


def walk(obj, path=""):
    """Genera (path, value) per ogni parametro della composizione."""
    if isinstance(obj, dict):
        if "id" in obj and "value" in obj and not isinstance(obj.get("value"), (dict, list)):
            yield path, obj["value"]
            return
        for k, v in obj.items():
            if k in ("view", "thumbnail"):
                continue
            yield from walk(v, f"{path}/{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            n = v.get("name") if isinstance(v, dict) else None
            if isinstance(n, dict):  # parametro {"value": ...}; a volte e' gia' una stringa
                n = n.get("value")
            yield from walk(v, f"{path}[{i}]" + (f":{n}" if n else ""))


def interesting(path: str) -> bool:
    # "/" davanti: i campi in cima alla composizione ("name", "selected") non hanno
    # barra iniziale e sfuggivano allo SKIP, e il PUT li rifiuta come read-only
    return not any(s in "/" + path for s in SKIP)


def state() -> dict:
    return {p: v for p, v in walk(get_composition()) if interesting(p)}


def merge_into(body: dict, path: str, value) -> dict:
    """Innesta {path: value} dentro body, nel formato che vuole PUT /composition."""
    node = body
    tokens = path.split("/")
    for tok in tokens[:-1]:
        m = INDEXED.match(tok)
        if m:
            key, idx = m.group(1), int(m.group(2))
            arr = node.setdefault(key, [])
            while len(arr) <= idx:
                arr.append({})
            node = arr[idx]
        else:
            node = node.setdefault(tok, {})
    last = tokens[-1]
    m = INDEXED.match(last)
    if m:
        arr = node.setdefault(m.group(1), [])
        while len(arr) <= int(m.group(2)):
            arr.append({})
        arr[int(m.group(2))] = {"value": value}
    else:
        node[last] = {"value": value}
    return body


def apply_values(pairs) -> int:
    """Applica (path, value) in un solo PUT. I trigger di clip usano la loro rotta."""
    body: dict = {}
    n = 0
    for path, value in pairs:
        m = CLIP_CONNECTED.match(path)
        if m:
            if value in (True, "Connected"):
                http.post(f"{BASE}/composition/layers/{int(m.group(1)) + 1}"
                          f"/clips/{int(m.group(2)) + 1}/connect")
                n += 1
            continue
        merge_into(body, path, value)
        n += 1
    if body:
        put(body)
    return n


_ultimo_battito = 0.0


def heartbeat(mode: str, note: str = "", forza: bool = False) -> None:
    """Scrittura atomica: il server MCP legge job.json in qualsiasi momento.

    Why due battiti al secondo e non uno per tick: su Windows os.replace fallisce
    con "accesso negato" se qualcun altro ha il file aperto proprio in
    quell'istante, e a 20 battiti al secondo capita davvero — il 2026-08-26 il
    pilota e' morto cosi', ucciso da un job_status che leggeva. Battere piano e
    non considerare fatale un fallimento toglie di mezzo la corsa.
    """
    global _ultimo_battito
    ora = time.time()
    if not forza and ora - _ultimo_battito < 0.5:
        return
    _ultimo_battito = ora
    tmp = JOB.with_suffix(".tmp")
    tmp.write_text(json.dumps({"mode": mode, "pid": os.getpid(), "note": note,
                               "last_tick": ora}), encoding="utf-8")
    try:
        os.replace(tmp, JOB)
    except OSError:
        pass          # il battito successivo arriva fra mezzo secondo


def running() -> bool:
    return not STOP.exists()


def start_job(mode: str) -> None:
    STOP.unlink(missing_ok=True)
    heartbeat(mode, "avviato", forza=True)


def end_job(mode: str, note: str) -> None:
    heartbeat(mode, note, forza=True)


# ---------------------------------------------------------------- comandi

def cmd_snapshot(dest: str) -> None:
    s = state()
    Path(dest).write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"scena salvata: {dest} ({len(s)} parametri)")


def cmd_restore(src: str) -> None:
    s = json.loads(Path(src).read_text(encoding="utf-8"))
    # i layer che nella scena non avevano nessuna clip attiva vanno svuotati,
    # altrimenti resta acceso quello che gira adesso
    seen: dict[int, bool] = {}
    for path, value in s.items():
        m = CLIP_CONNECTED.match(path)
        if m:
            n = int(m.group(1)) + 1
            seen[n] = seen.get(n, False) or value in (True, "Connected")
    for n, has_clip in seen.items():
        if not has_clip:
            http.post(f"{BASE}/composition/layers/{n}/clear")
    # filtra anche qui: le scene salvate prima della correzione hanno campi read-only
    valori = [(p, v) for p, v in s.items() if interesting(p)]
    print(f"scena richiamata: {src} ({apply_values(valori)} parametri)")


def cmd_record(dest: str, hz: float = 4.0) -> None:
    start_job("record")
    prev, t0, n = state(), time.time(), 0
    with open(dest, "w", encoding="utf-8") as f:
        f.write(json.dumps({"t": 0.0, "snapshot": prev}, ensure_ascii=False) + "\n")
        f.flush()
        while running():
            time.sleep(1.0 / hz)
            try:
                cur = state()
            except Exception as e:
                print("errore lettura:", e)
                continue
            changed = {p: v for p, v in cur.items() if prev.get(p) != v}
            if changed:
                f.write(json.dumps({"t": round(time.time() - t0, 3), "set": changed},
                                   ensure_ascii=False) + "\n")
                f.flush()
                n += len(changed)
                prev = cur
            heartbeat("record", f"{n} cambi in {int(time.time() - t0)}s")
    end_job("record", f"fermato, {n} cambi registrati in {dest}")
    print("registrazione conclusa:", dest)


def cmd_play(src: str, loop: bool = False) -> None:
    events = [json.loads(l) for l in Path(src).read_text(encoding="utf-8").splitlines() if l.strip()]
    start_job("play")
    while running():
        t0 = time.time()
        for ev in events:
            if not running():
                break
            wait = ev["t"] - (time.time() - t0)
            if wait > 0:
                time.sleep(wait)
            apply_values((ev.get("snapshot") or ev.get("set") or {}).items())
            heartbeat("play", f"t={ev['t']:.1f}s")
        if not loop:
            break
    end_job("play", "riproduzione conclusa")
    print("riproduzione conclusa")


def cmd_auto(cfg_path: str) -> None:
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    start_job("auto")
    comp = get_composition()
    bpm = (comp.get("tempocontroller") or {}).get("tempo", {}).get("value") or 120.0
    beat = 60.0 / bpm
    t0 = time.time()
    last_pick: dict[int, int] = {}
    next_at = {("layer", i): 0.0 for i, _ in enumerate(cfg.get("layers", []))}
    next_at.update({("fx", i): 0.0 for i, _ in enumerate(cfg.get("effects", []))})
    fx_on: dict[int, bool] = {}

    while running():
        try:
            _giro_auto(cfg, beat, t0, next_at, last_pick, fx_on, bpm)
        except httpx.HTTPError as e:
            # Resolume riavviata, webserver riacceso, rete che singhiozza: il
            # pilota non deve morire per questo, aspetta e riprova al giro dopo
            heartbeat("auto", f"Resolume non risponde ({type(e).__name__}), riprovo")
            time.sleep(1.0)
            continue
        time.sleep(cfg.get("tick", 0.05))
    end_job("auto", "pilota automatico fermato")
    print("pilota automatico fermato")


def _giro_auto(cfg, beat, t0, next_at, last_pick, fx_on, bpm) -> None:
    """Un giro del pilota: cambi di clip scaduti, effetti da accendere, modulazioni."""
    beats = (time.time() - t0) / beat

    for i, lay in enumerate(cfg.get("layers", [])):
        if beats < next_at[("layer", i)]:
            continue
        next_at[("layer", i)] = beats + lay.get("beats", 16)
        choices = [c for c in lay["clips"] if c != last_pick.get(lay["layer"])]
        clip = random.choice(choices or lay["clips"])
        last_pick[lay["layer"]] = clip
        http.post(f"{BASE}/composition/layers/{lay['layer']}/clips/{clip}/connect")

    for i, fx in enumerate(cfg.get("effects", [])):
        if beats < next_at[("fx", i)]:
            continue
        on = not fx_on.get(i, False)
        fx_on[i] = on
        next_at[("fx", i)] = beats + fx.get("beats_on" if on else "beats_off", 16)
        body = {"video": {"effects": [{} for _ in range(fx["effect"] - 1)]
                          + [{"bypassed": {"value": not on}}]}}
        http.put(f"{BASE}/composition/layers/{fx['layer']}", json=body)

    mods = []
    for m in cfg.get("modulate", []):
        phase = (beats % m.get("beats", 8)) / m.get("beats", 8)
        if m.get("shape") == "ramp":
            k = phase
        elif m.get("shape") == "random":
            k = random.random()
        else:
            k = (1 - math.cos(phase * 2 * math.pi)) / 2
        mods.append((m["path"], m["min"] + k * (m["max"] - m["min"])))
    mods += giro_fx(cfg, beats)
    if mods:
        apply_values(mods)

    heartbeat("auto", f"battuta {int(beats)} a {bpm:g} bpm")


def cella_x(i: int, c: dict) -> float:
    """Dove va portato il blob di controllo perche' copra la cella i della striscia.

    span e offset sono la manopola di taratura: il Position X di Resolume non
    copre esattamente la larghezza della composizione su tutti i setup, e un
    proiettore fuori asse sposta ancora un po' le cose. Se il tracer "manca" una
    slice si aggiustano quelli, non il codice.
    """
    n = max(1, c.get("cells", 1))
    return ((i + 0.5) / n - 0.5) * 2 * c.get("span", 1.0) + c.get("offset", 0.0)


_fx_last: dict = {}


def giro_fx(cfg: dict, beats: float) -> list:
    """strobe, tracer e mix: il pezzo che si pilota dal vivo, sul layer di controllo.

    Why qui e non nelle slice: l'Advanced Output non e' nella REST API, quindi
    una slice non si accende dal vivo. Si accende la cella di composizione da cui
    quella slice pesca (vedi add_outlines in resolume_mapping): stesso risultato,
    e passa tutto per parametri normali.
    """
    mods = []

    st = cfg.get("strobe")
    if st and st.get("beats"):
        acceso = (beats % st["beats"]) / st["beats"] < st.get("duty", 0.5)
        mods.append((st["path"], st.get("on", 1.0) if acceso else st.get("off", 0.0)))

    tr = cfg.get("tracer")
    if tr and tr.get("beats"):
        ordine = tr.get("order") or list(range(tr.get("cells", 1)))
        mods.append((tr["path"], cella_x(ordine[int(beats / tr["beats"]) % len(ordine)], tr)))

    mx = cfg.get("mix")
    if mx and mx.get("beats"):
        # caotico ma calcolato: stesso seme, stessa sequenza tutte le sere
        passo = int(beats / mx["beats"])
        rnd = random.Random(f"{mx.get('seed', 0)}:{passo}")
        mods.append((mx["path"], cella_x(rnd.randrange(max(1, mx.get("cells", 1))), mx)))
        if mx.get("tilt_path"):
            mods.append((mx["tilt_path"], rnd.uniform(-1, 1) * mx.get("tilt", 0.25)))

    # il giro passa 20 volte al secondo: si spedisce solo cio' che e' cambiato,
    # altrimenti si martella Resolume con lo stesso valore
    mods = [(p, v) for p, v in mods if _fx_last.get(p) != v]
    _fx_last.update(mods)
    return mods


def _selftest() -> None:
    c = {"cells": 4, "span": 1.0}
    assert [round(cella_x(i, c), 3) for i in range(4)] == [-0.75, -0.25, 0.25, 0.75]
    assert cella_x(0, {"cells": 1}) == 0.0
    assert round(cella_x(3, {"cells": 4, "span": 0.5, "offset": 0.1}), 3) == 0.475
    cfg = {"strobe": {"path": "L/opacity", "beats": 1, "duty": 0.5},
           "tracer": {"path": "L/x", "beats": 1, "cells": 4, "order": [2, 0]}}
    _fx_last.clear()
    assert dict(giro_fx(cfg, 0.0)) == {"L/opacity": 1.0, "L/x": 0.25}
    assert giro_fx(cfg, 0.1) == [], "niente da rispedire se non e' cambiato nulla"
    assert dict(giro_fx(cfg, 0.6)) == {"L/opacity": 0.0}, "meta' battuta: strobe giu'"
    assert dict(giro_fx(cfg, 1.6)) == {"L/x": -0.75}, "cella successiva, strobe gia' giu'"
    assert dict(giro_fx(cfg, 2.0)) == {"L/opacity": 1.0, "L/x": 0.25}, "battuta nuova"
    _fx_last.clear()
    a = [giro_fx({"mix": {"path": "p", "beats": 4, "cells": 5, "seed": 7}}, t)
         for t in (0, 4, 8, 12)]
    _fx_last.clear()
    b = [giro_fx({"mix": {"path": "p", "beats": 4, "cells": 5, "seed": 7}}, t)
         for t in (0, 4, 8, 12)]
    assert a == b, "stesso seme deve dare la stessa sequenza"
    print("selftest ok")


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "selftest":
        _selftest()
        return
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, arg = sys.argv[1], sys.argv[2]
    if cmd == "snapshot":
        cmd_snapshot(arg)
    elif cmd == "restore":
        cmd_restore(arg)
    elif cmd == "record":
        cmd_record(arg)
    elif cmd == "play":
        cmd_play(arg, "--loop" in sys.argv)
    elif cmd == "auto":
        cmd_auto(arg)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
