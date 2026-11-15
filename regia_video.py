# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "obsws-python"]
# ///
"""Regia dei video social: OBS registra la finestra Advanced Output di Resolume
mentre questo script suona una sequenza di comandi sulla REST API.

  uv run --script regia_video.py setup          scena OBS + sorgente finestra
  uv run --script regia_video.py v1|v2|v3       registra quel video

Ogni comando viene annotato con il suo istante in riprese/<video>.json, cosi'
in montaggio i sottotitoli cadono esattamente quando il comando e' partito.
"""
import json
import random
import sys
import time
from pathlib import Path

import httpx
import obsws_python as obs

import resolume_auto as ra

HERE = Path(__file__).resolve().parent
OUT = HERE / "riprese"
OUT.mkdir(exist_ok=True)
BASE = ra.BASE
BPM = 145.0
BEAT = 60.0 / BPM
SCENA, SORGENTE = "MCP REC", "Schermo MCP"
LAYERS = {1: "EYES", 2: "geometric truss", 3: "spiral", 4: "HEAD", 5: "big geometric", 6: "Layer #", 7: "BACKWALL"}
PWD = json.loads((Path.home() / "AppData/Roaming/obs-studio/plugin_config/obs-websocket/config.json").read_text())["server_password"]


def ws():
    return obs.ReqClient(host="localhost", port=4455, password=PWD, timeout=10)


def lp(n, what):
    return f"layers[{n - 1}]:{LAYERS[n]}/{what}"


def setv(pairs):
    ra.apply_values(pairs)


def bypass_only(keep):
    setv([(lp(n, "bypassed"), n not in keep) for n in (1, 2, 3, 4, 5, 7)])


def column(c):
    httpx.post(f"{BASE}/composition/columns/{c}/connect", timeout=5)


def master(v):
    setv([("video/opacity", v)])


class Take:
    def __init__(self, name):
        self.name, self.log, self.c = name, [], ws()

    def __enter__(self):
        self.c.set_current_program_scene(SCENA)
        self.c.start_record()
        for _ in range(50):
            if self.c.get_record_status().output_active:
                break
            time.sleep(0.05)
        self.t0 = time.time()
        return self

    def mark(self, label, **extra):
        self.log.append({"t": round(time.time() - self.t0, 3), "label": label, **extra})

    def wait_beats(self, b):
        time.sleep(b * BEAT)

    def __exit__(self, *exc):
        time.sleep(0.5)
        path = self.c.stop_record().output_path
        (OUT / f"{self.name}.json").write_text(json.dumps({"file": path, "bpm": BPM, "events": self.log}, indent=1), encoding="utf-8")
        print("registrato:", path)
        return False


def setup():
    c = ws()
    scenes = [s["sceneName"] for s in c.get_scene_list().scenes]
    if SCENA not in scenes:
        c.create_scene(SCENA)
    # l'Advanced Output e' una finestra figlia di Arena: la cattura finestra non la
    # elenca. Si cattura lo schermo intero con la finestra massimizzata e si ritaglia dopo.
    items = [i["sourceName"] for i in c.get_scene_item_list(SCENA).scene_items]
    if SORGENTE in items:
        c.remove_input(SORGENTE)
        time.sleep(0.5)
    c.create_input(SCENA, SORGENTE, "monitor_capture", {"capture_cursor": False}, True)
    scelta = "schermo principale"
    sid = c.get_scene_item_id(SCENA, SORGENTE).scene_item_id
    c.set_scene_item_transform(SCENA, sid, {"boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsWidth": 1920.0,
                                             "boundsHeight": 1080.0, "positionX": 0.0, "positionY": 0.0,
                                             "boundsAlignment": 0, "alignment": 5})
    c.set_current_program_scene(SCENA)
    print("finestra:", scelta)


def v1():
    """Controllo della mappatura: una superficie alla volta, poi tutto acceso."""
    column(2)  # in colonna 1 il layer dell'americana e' vuoto
    bypass_only([])
    master(1.0)
    time.sleep(1.0)
    with Take("v1") as t:
        t.mark("buio")
        t.wait_beats(8)
        for n, nome in [(2, "americana"), (1, "occhi"), (5, "rombi"), (4, "teste"), (3, "spirali")]:
            bypass_only([n])
            t.mark("superficie", nome=nome)
            t.wait_beats(4)
        bypass_only([1, 2, 3, 4, 5])
        t.mark("tutte")
        t.wait_beats(8)
        bypass_only([1, 2, 3, 4, 5, 7])
        t.mark("sfondo")
        t.wait_beats(8)


def v2():
    """Una frase, 14 valori: opacita' 70% e scala 120% su 7 layer, poi il richiamo del look."""
    column(1)
    bypass_only([1, 2, 3, 4, 5, 7])
    master(1.0)
    time.sleep(0.5)
    ra.cmd_snapshot(str(HERE / "scenes" / "BASE_V2.json"))
    with Take("v2") as t:
        t.mark("prima")
        t.wait_beats(8)
        t.mark("prompt")
        k = 0
        for n in LAYERS:
            setv([(lp(n, "video/opacity"), 0.7)])
            k += 1
            t.mark("valore", n=k)
        for n in LAYERS:
            setv([(lp(n, "video/effects[0]:Transform/params/Scale"), 120)])
            k += 1
            t.mark("valore", n=k)
        t.mark("fatto")
        t.wait_beats(10)
        t.mark("richiamo")
        ra.cmd_restore(str(HERE / "scenes" / "BASE_V2.json"))
        column(1)
        bypass_only([1, 2, 3, 4, 5, 7])
        t.mark("richiamato")
        t.wait_beats(8)


def v3():
    """Lo show: chase, strobo, mix con seme, sfumata."""
    column(1)
    bypass_only([1, 2, 3, 4, 5, 7])
    master(1.0)
    time.sleep(0.5)
    ordine = [2, 1, 5, 4, 3]
    with Take("v3") as t:
        t.mark("intro")
        t.wait_beats(8)
        t.mark("tracer")
        for i in range(16):
            bypass_only([ordine[i % len(ordine)]])
            t.wait_beats(1)
        t.mark("strobo")
        bypass_only([1, 2, 3, 4, 5, 7])
        column(2)
        for i in range(32):
            master(1.0 if i % 2 == 0 else 0.0)
            t.wait_beats(0.5)
        master(1.0)
        t.mark("mix")
        column(3)
        rnd = random.Random("7")
        for i in range(16):
            bypass_only(rnd.sample([1, 2, 3, 4, 5, 7], rnd.randint(2, 4)))
            if i == 8:
                column(4)
            t.wait_beats(1)
        bypass_only([1, 2, 3, 4, 5, 7])
        t.mark("drop")
        t.wait_beats(8)
        t.mark("sfumata")
        for i in range(17):
            master(1.0 - i / 16)
            t.wait_beats(0.25)
        t.wait_beats(4)
    master(1.0)


if __name__ == "__main__":
    {"setup": setup, "v1": v1, "v2": v2, "v3": v3}[sys.argv[1]]()
