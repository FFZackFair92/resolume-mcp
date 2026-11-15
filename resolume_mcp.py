# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2", "httpx>=0.27"]
# ///
"""MCP server per Resolume Arena/Avenue 7 (REST API).

Abilita il web server in Resolume: Preferences -> Webserver -> Enable (porta 8080).
Config: RESOLUME_URL (default http://127.0.0.1:8080)

Meccanica di scrittura: Resolume espone pochissime rotte. Tutto si scrive con
PUT /api/v1/composition passando un corpo parziale che rispecchia l'albero JSON;
gli array vanno riempiti con {} fino all'indice giusto. set_parameter fa questo.
"""
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
try:  # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("RESOLUME_URL", "http://127.0.0.1:8080").rstrip("/") + "/api/v1"
HERE = Path(__file__).resolve().parent
AUTO, JOB, STOP = HERE / "resolume_auto.py", HERE / "job.json", HERE / "stop.flag"
SCENES = HERE / "scenes"
sys.path.insert(0, str(HERE))
import resolume_mapping as mapping  # noqa: E402  (stesso cartella, niente deps)

mcp = FastMCP("resolume")
http = httpx.Client(timeout=10.0)
INDEXED = re.compile(r"^([^\[]+)\[(\d+)\]")


def call(method: str, path: str, json_body: Any = None) -> Any:
    r = http.request(method, BASE + path, json=json_body)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    if not r.content:
        return "ok"
    try:
        return r.json()
    except ValueError:
        return r.text


def _dentro(base: Path, nome: str, suffisso: str = "") -> Path:
    """Percorso di `nome` dentro `base`. Rifiuta nomi vuoti e percorsi che escono
    dalla cartella (es. '../x', percorsi assoluti): i nomi arrivano dal modello."""
    if not nome or not nome.strip():
        raise ValueError("nome vuoto")
    radice = base.resolve()
    p = (radice / f"{nome}{suffisso}").resolve()
    if radice != p.parent and radice not in p.parents:
        raise ValueError(f"'{nome}' esce dalla cartella {base.name}/: usa un nome semplice")
    return p


def pval(obj: Any, key: str, default=None):
    p = (obj or {}).get(key)
    return p.get("value", default) if isinstance(p, dict) else (p if p is not None else default)


def walk_params(obj: Any, path: str = ""):
    """Genera (path, param_dict) per ogni parametro nell'albero della composizione."""
    if isinstance(obj, dict):
        if "id" in obj and "value" in obj and not isinstance(obj.get("value"), (dict, list)):
            yield path, obj
            return
        for k, v in obj.items():
            if k in ("view", "thumbnail"):
                continue
            yield from walk_params(v, f"{path}/{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            name = pval(v, "name") if isinstance(v, dict) else None
            yield from walk_params(v, f"{path}[{i}]" + (f":{name}" if name else ""))


# ---------------------------------------------------------------- lettura

@mcp.tool()
def get_composition() -> dict:
    """Panoramica della composizione: layer, clip caricate e connesse, colonne, deck, BPM.
    Usalo sempre per primo per sapere cosa c'e' in Resolume."""
    c = call("GET", "/composition")
    layers = []
    for li, layer in enumerate(c.get("layers", []), start=1):
        clips = [{"col": ci, "name": pval(clip, "name"), "connected": pval(clip, "connected")}
                 for ci, clip in enumerate(layer.get("clips", []), start=1)
                 if pval(clip, "name")]
        layers.append({
            "layer": li,
            "name": pval(layer, "name"),
            "opacity": pval(layer.get("video") or {}, "opacity"),
            "bypassed": pval(layer, "bypassed"),
            "solo": pval(layer, "solo"),
            "effects": [pval(e, "name") for e in (layer.get("video") or {}).get("effects", [])],
            "clips": clips,
        })
    return {
        "name": pval(c, "name"),
        "master_opacity": pval(c.get("video") or {}, "opacity"),
        "bpm": pval(c.get("tempocontroller") or {}, "tempo"),
        "columns": [{"col": i, "name": pval(col, "name")}
                    for i, col in enumerate(c.get("columns", []), start=1)],
        "decks": [{"deck": i, "name": pval(d, "name"), "selected": pval(d, "selected")}
                  for i, d in enumerate(c.get("decks", []), start=1)],
        "layers": layers,
    }


@mcp.tool()
def find_parameters(query: str, limit: int = 30) -> list[dict]:
    """Cerca parametri nella composizione e restituisce il loro 'path'.
    Passa il path a set_parameter per cambiare QUALSIASI cosa: opacita', blend mode,
    parametri di ogni effetto, transform, transport delle clip.
    Query di esempio: 'opacity', 'Scale', 'layers[1]', 'Blend Mode', 'tempo'."""
    q = query.lower()
    out = []
    for path, p in walk_params(call("GET", "/composition")):
        if q not in path.lower():
            continue
        item = {"path": path, "value": p["value"], "type": p.get("valuetype")}
        for extra in ("min", "max", "options"):
            if extra in p:
                item[extra] = p[extra]
        out.append(item)
        if len(out) >= limit:
            break
    return out


@mcp.tool()
def list_effects() -> Any:
    """Elenca gli effetti video/audio installati in Resolume.
    Per aggiungerne uno usa add_effect con il nome mostrato qui; una volta aggiunto,
    ogni suo parametro e' pilotabile con find_parameters + set_parameter."""
    e = call("GET", "/effects")
    return {k: [x.get("name") for x in v] for k, v in e.items()}


# ---------------------------------------------------------------- scrittura

@mcp.tool()
def set_parameter(path: str, value: Any) -> str:
    """Imposta un parametro dato il suo path (da find_parameters).
    Esempi:
      set_parameter('layers[0]:Layer #/video/opacity', 0.5)
      set_parameter('layers[0]:Layer #/video/effects[0]:Transform/params/Scale', 150)
      set_parameter('tempocontroller/tempo', 128)
    value: numero, booleano, o la stringa esatta per i menu (vedi 'options')."""
    # il valore puo' arrivare come stringa dal client MCP: Resolume in quel caso
    # risponde 'value is not double', quindi si riconverte prima di spedire
    if isinstance(value, str):
        testo = value.strip()
        if testo.lower() in ("true", "false"):
            value = testo.lower() == "true"
        else:
            try:
                value = float(testo) if ("." in testo or "e" in testo.lower()) else int(testo)
            except ValueError:
                pass  # e' davvero una stringa: un'opzione di menu
    body: Any = {"value": value}
    for tok in reversed(path.split("/")):
        m = INDEXED.match(tok)
        if m:
            body = {m.group(1): [{} for _ in range(int(m.group(2)))] + [body]}
        else:
            body = {tok: body}
    call("PUT", "/composition", body)
    return f"{path} = {value}"


@mcp.tool()
def set_layer_opacity(layer: int, opacity: float) -> str:
    """Opacita' di un layer, da 0.0 a 1.0. Layer parte da 1."""
    call("PUT", f"/composition/layers/{layer}", {"video": {"opacity": {"value": opacity}}})
    return f"layer {layer} opacity = {opacity}"


@mcp.tool()
def set_master_opacity(opacity: float) -> str:
    """Opacita' master della composizione, da 0.0 a 1.0."""
    call("PUT", "/composition", {"video": {"opacity": {"value": opacity}}})
    return f"master opacity = {opacity}"


@mcp.tool()
def set_layer_state(layer: int, bypassed: bool | None = None,
                    solo: bool | None = None) -> str:
    """Attiva/disattiva bypass o solo su un layer. Layer parte da 1."""
    body = {k: {"value": v} for k, v in (("bypassed", bypassed), ("solo", solo))
            if v is not None}
    if not body:
        return "nessuna modifica"
    call("PUT", f"/composition/layers/{layer}", body)
    return f"layer {layer}: {body}"


@mcp.tool()
def set_effect_enabled(layer: int, effect: int, enabled: bool) -> str:
    """Accende o spegne un effetto gia' presente nella catena di un layer (bypass).
    'effect' e' la posizione nella catena, da 1 (vedi 'effects' in get_composition).
    La REST API non permette di aggiungere o togliere effetti: caricali prima
    nell'interfaccia di Resolume, poi accendili e spegnili da qui."""
    body = {"video": {"effects": [{} for _ in range(effect - 1)] + [{"bypassed": {"value": not enabled}}]}}
    call("PUT", f"/composition/layers/{layer}", body)
    return f"layer {layer} effetto {effect}: {'on' if enabled else 'off'}"


@mcp.tool()
def set_bpm(bpm: float) -> str:
    """Imposta il BPM della composizione."""
    call("PUT", "/composition", {"tempocontroller": {"tempo": {"value": bpm}}})
    return f"bpm = {bpm}"


# ---------------------------------------------------------------- trigger

@mcp.tool()
def trigger_clip(layer: int, column: int) -> str:
    """Lancia (connette) la clip nel layer e colonna dati. Indici a partire da 1."""
    call("POST", f"/composition/layers/{layer}/clips/{column}/connect")
    return f"clip layer {layer} colonna {column} connessa"


@mcp.tool()
def trigger_column(column: int) -> str:
    """Lancia un'intera colonna della composizione. Indice a partire da 1."""
    call("POST", f"/composition/columns/{column}/connect")
    return f"colonna {column} connessa"


@mcp.tool()
def clear_layer(layer: int) -> str:
    """Svuota (disconnette) un layer. Indice a partire da 1."""
    call("POST", f"/composition/layers/{layer}/clear")
    return f"layer {layer} svuotato"


@mcp.tool()
def clear_all() -> str:
    """Svuota tutti i layer della composizione."""
    n = len(call("GET", "/composition").get("layers", []))
    for i in range(1, n + 1):
        call("POST", f"/composition/layers/{i}/clear")
    return f"{n} layer svuotati"


@mcp.tool()
def select_deck(deck: int) -> str:
    """Seleziona un deck. Indice a partire da 1."""
    call("POST", f"/composition/decks/{deck}/select")
    return f"deck {deck} selezionato"



# ---------------------------------------------------------------- automazione

def _run(args: list[str], detach: bool) -> str:
    """Lancia resolume_auto.py. detach=True lo stacca: sopravvive alla chiusura di Claude."""
    cmd = [sys.executable, str(AUTO)] + args
    if not detach:
        # stdin=DEVNULL: su Windows il figlio altrimenti eredita la pipe stdio del
        # server MCP e resta appeso. timeout < 60s del bridge, cosi' l'errore arriva.
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45,
                           stdin=subprocess.DEVNULL, cwd=str(HERE))
        if r.returncode:
            raise RuntimeError((r.stderr or r.stdout)[:400])
        return (r.stdout or "ok").strip()
    # staccato vuol dire senza console: senza questi due file un errore muore muto
    # e resta solo un job.json che smette di battere
    log = (HERE / f"job_{args[0]}.log").open("w", encoding="utf-8")
    err = (HERE / f"job_{args[0]}.err").open("w", encoding="utf-8")
    if os.name == "nt":  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(cmd, cwd=str(HERE), stdout=log, stderr=err, stdin=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x00000200)
    else:
        subprocess.Popen(cmd, cwd=str(HERE), stdout=log, stderr=err, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    time.sleep(1.5)
    return job_status()


@mcp.tool()
def job_start(mode: str, file: str) -> str:
    """Avvia un processo autonomo che continua a girare anche a Claude chiuso.
    mode 'record': registra in un file .jsonl tutto quello che cambia in Resolume.
    mode 'play':   riproduce una registrazione fatta con 'record'.
    mode 'auto':   pilota automatico generativo, guidato da un file .json di config.
    'file' e' il nome del file dentro la cartella dello script (es. 'set.jsonl').
    Fermalo con job_stop, controllalo con job_status."""
    if mode not in ("record", "play", "auto"):
        raise ValueError("mode deve essere record, play o auto")
    st = job_status()
    if "in corso" in st:
        raise RuntimeError(f"c'e' gia' un job attivo, fermalo prima: {st}")
    return _run([mode, str(_dentro(HERE, file))], detach=True)


@mcp.tool()
def job_stop() -> str:
    """Ferma in modo pulito il job in corso (record, play o auto)."""
    STOP.write_text("stop", encoding="utf-8")
    time.sleep(1.5)
    return job_status()


@mcp.tool()
def job_status() -> str:
    """Dice se c'e' un job attivo e cosa sta facendo."""
    if not JOB.exists():
        return "nessun job mai avviato"
    try:
        j = json.loads(JOB.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        time.sleep(0.3)  # letto mentre il job lo riscriveva
        j = json.loads(JOB.read_text(encoding="utf-8"))
    age = time.time() - j.get("last_tick", 0)
    stato = "in corso" if age < 5 and not STOP.exists() else "fermo"
    return f"{j['mode']}: {stato} — {j.get('note','')} (ultimo segnale {age:.0f}s fa)"


@mcp.tool()
def mapping_get() -> str:
    """Legge la mappatura del palco attiva (Advanced Output): schermi, device di
    uscita e le slice con i loro 4 angoli di ingresso e di uscita.
    Non passa dalla REST API: l'Advanced Output della 7.16 vive solo su disco.
    Se e' attivo un preset, e' quello lo stato vero e viene letto quello."""
    data = mapping.read_setup()
    data["preset_attivo"] = mapping.active_preset()
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool()
def mapping_apply(mapping_json: str, preset: str = "") -> str:
    """Scrive la mappatura in un preset dell'Advanced Output.

    'mapping_json' e' quello che produce l'editor visuale (il tasto Copia), cioe'
    {"mapping": {"screens": [{"name": ..., "slices": [{"name","source","input","output"}]}]}}.
    Senza 'preset' scrive dentro il preset gia' attivo, che e' la strada sicura:
    Resolume quel nome lo conosce gia' e basta ricaricarlo dal menu."""
    data = json.loads(mapping_json)
    data = data.get("mapping", data)
    attivo = mapping.active_preset()
    preset = preset or attivo or "chat"
    dest = mapping.write_preset(data, preset)
    n = sum(len(s["slices"]) for s in data["screens"])
    nota = "" if preset == attivo else "\nAttenzione: e' un preset nuovo, potrebbe non comparire nel menu finche' Resolume non rilegge la cartella."
    return (f"preset '{preset}' scritto ({n} slice): {dest}\n"
            f"Ricaricalo da Resolume: Output -> Advanced -> menu preset -> {preset}{nota}")


@mcp.tool()
def mapping_presets() -> str:
    """Elenca i preset di Advanced Output disponibili."""
    mapping.PRESETS.mkdir(parents=True, exist_ok=True)
    return json.dumps(sorted(p.stem for p in mapping.PRESETS.glob("*.xml")))


@mcp.tool()
def mapping_editor() -> str:
    """Ricuce dentro l'editor visuale (stage_mapper.html) la mappatura attuale,
    cosi' che riaprendolo parta da quello che c'e' davvero in Resolume."""
    return f"editor aggiornato: {mapping.refresh_editor()}"


@mcp.tool()
def output_displays() -> str:
    """Elenca le uscite video di Windows con la chiave che usa l'Advanced Output.
    Serve per sapere su quale display mandare la proiezione: il proiettore e'
    quello non primario. 'device_key' e' l'identita' con cui Resolume riconosce
    l'uscita, non va inventata a mano."""
    import displays
    return json.dumps(displays.list_displays(), indent=2, ensure_ascii=False)


@mcp.tool()
def output_assign(display: str, screen: str = "", preset: str = "") -> str:
    """Manda uno screen dell'Advanced Output su un'uscita fisica (il proiettore).

    'display' accetta il nome Resolume ("Display 2"), il device Windows
    ("\\\\.\\DISPLAY2"), il modello del monitor o l'indice ("2").
    Sostituisce il device dello screen e riscala le slice sulla nuova
    risoluzione mantenendo le proporzioni (centrando se il rapporto cambia),
    quindi la mappatura del palco resta valida.
    Senza 'screen' agisce sull'unico screen del preset; senza 'preset' su quello attivo."""
    esito = mapping.assign_display(display, screen=screen or None, preset=preset or None)
    avviso = ("\nAttenzione: idHash sconosciuto per questo device (Resolume non l'ha "
              "mai scritto qui). Se non aggancia l'uscita, assegnala una volta a mano "
              "nell'Advanced Output e risalva il preset." if esito["idHash"] == "0" else "")
    return (json.dumps(esito, indent=2, ensure_ascii=False)
            + f"\n\nRicarica il preset in Resolume: Output -> Advanced -> preset "
              f"-> {esito['preset']}{avviso}")


@mcp.tool()
def scene_save(name: str) -> str:
    """Fotografa lo stato attuale della composizione come scena richiamabile."""
    SCENES.mkdir(exist_ok=True)
    return _run(["snapshot", str(_dentro(SCENES, name, ".json"))], detach=False)


@mcp.tool()
def scene_recall(name: str) -> str:
    """Rimette la composizione in una scena salvata con scene_save."""
    return _run(["restore", str(_dentro(SCENES, name, ".json"))], detach=False)


@mcp.tool()
def scene_list() -> list[str]:
    """Elenca le scene salvate."""
    return sorted(p.stem for p in SCENES.glob("*.json")) if SCENES.exists() else []


# ------------------------------------------------------------- effetti slice
#
# Le slice non sono nella REST API: dal vivo non si toccano. Ma quello che una
# slice mostra si', perche' e' un pezzo di composizione. Quindi:
#   slice_outline  scrive UNA VOLTA la geometria dei contorni nel preset, e fa
#                  pescare il contorno della slice i dalla cella i di una
#                  striscia di controllo in cima alla composizione;
#   gli altri tre  pilotano dal vivo un "layer di controllo" che passa sopra
#                  quella striscia, in battute, e i contorni lo seguono.
# Niente e' legato a questa mappatura: quante celle ci sono lo dice il preset.

FX = HERE / "slice_fx.json"


def _fx_paths(layer: int, needle: str) -> str:
    """Il path piu' corto del layer che contiene 'needle'. Vuoto se non c'e'."""
    pre, q = f"layers[{layer - 1}]", needle.lower()
    trovati = [p for p, _ in walk_params(call("GET", "/composition"))
               if p.startswith(pre) and q in p.lower()]
    return min(trovati, key=len) if trovati else ""


def _fx_cells() -> tuple[int, list[int]]:
    """Quante celle ha la striscia, e l'ordine delle slice da sinistra a destra."""
    base = mapping.base_slices(mapping.read_setup())
    da_sx = sorted(range(len(base)),
                   key=lambda i: sum(p[0] for p in base[i]["output"]) / len(base[i]["output"]))
    return len(base), da_sx


def _fx_save(sezione: str, cfg: dict | None) -> str:
    """Aggiorna slice_fx.json e fa ripartire il pilota con la nuova config."""
    data = json.loads(FX.read_text(encoding="utf-8")) if FX.exists() else {}
    data.pop(sezione, None)
    if cfg:
        data[sezione] = cfg
    data["tick"] = 0.05
    FX.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    if "in corso" in job_status():
        job_stop()
    attivi = [k for k in ("strobe", "tracer", "mix") if data.get(k)]
    if not attivi:
        return f"{sezione}: spento. Nessun effetto slice attivo, pilota fermo."
    return f"{_run(['auto', str(FX)], detach=True)}\nattivi: {', '.join(attivi)}"


def _fx_pos(layer: int, param: str) -> str:
    p = _fx_paths(layer, f"params/{param}")
    if not p:
        raise RuntimeError(
            f"sul layer {layer} non c'e' nessun parametro '{param}'. Serve un Transform "
            f"nella sua catena: aggiungilo a mano in Resolume (la REST API non puo' "
            f"aggiungere effetti) e rilancia. Con find_parameters vedi cosa c'e'.")
    return p


@mcp.tool()
def slice_outline(width: float = 6, strip_y: float = 0, strip_h: float = 8) -> str:
    """Circonda OGNI slice della mappatura con un contorno di 4 slice sottili.

    Il contorno della slice i pesca dalla cella i di una striscia larga quanto la
    composizione (alta 'strip_h' px, a quota 'strip_y'): accendi la cella e si
    accende quel contorno, senza piu' toccare la geometria. E' quello che rende
    controllabili dal vivo slice_tracer, slice_strobe e slice_mix.
    width in pixel di uscita; width=0 toglie tutti i contorni.
    Riscrive il preset attivo: dopo va RICARICATO a mano da Resolume
    (Output -> Advanced -> menu preset)."""
    data = mapping.read_setup()
    n = mapping.add_outlines(data, width=width, strip_y=strip_y, strip_h=strip_h)
    nome = mapping.active_preset() or "chat"
    dest = mapping.write_preset(data, nome)
    celle, _ = _fx_cells()
    if width <= 0:
        return f"contorni tolti: {dest}\nRicarica il preset '{nome}' in Resolume."
    largh = (data.get("composition") or {}).get("width", 1280) / max(1, celle)
    return (f"{n} slice di contorno da {width}px su {celle} slice: {dest}\n"
            f"striscia di controllo: {celle} celle da {largh:.0f}x{strip_h:.0f}px "
            f"a y={strip_y:.0f}\nRicarica il preset '{nome}' in Resolume: "
            f"Output -> Advanced -> menu preset.\n"
            f"Poi metti una clip bianca su un layer di controllo con un Transform, "
            f"e usa slice_tracer / slice_strobe / slice_mix su quel layer.")


@mcp.tool()
def slice_strobe(layer: int, beats: float = 0.5, duty: float = 0.4,
                 on: float = 1.0, off: float = 0.0) -> str:
    """Strobo a tempo sull'opacita' di un layer, agganciato al BPM di Resolume.

    'beats' e' la durata di un lampo completo (0.25 = sedicesimi, 1 = un quarto);
    'duty' quanta parte resta acceso (0.1 flash secco, 0.5 onda quadra).
    Puntato sul layer di controllo fa lampeggiare i contorni; puntato su un layer
    qualsiasi fa lampeggiare quello. beats=0 lo spegne."""
    if beats <= 0:
        return _fx_save("strobe", None)
    return _fx_save("strobe", {"path": _fx_paths(layer, "/video/opacity")
                               or f"layers[{layer - 1}]/video/opacity",
                               "beats": beats, "duty": duty, "on": on, "off": off})


@mcp.tool()
def slice_tracer(layer: int, beats: float = 1, order: str = "seq",
                 span: float = 1.0, offset: float = 0.0,
                 param: str = "Position X", seed: int = 0) -> str:
    """Fa camminare l'accensione da una slice all'altra, una ogni 'beats' battute.

    Sposta il Position X del Transform del layer di controllo di cella in cella:
    il blob che ci sta sopra illumina un contorno alla volta.
    order: 'seq' (ordine della mappatura), 'pos' (da sinistra a destra sul palco),
    'random' (permutazione fissa, mai due volte la stessa di fila), oppure una
    lista tua tipo '0,2,4,1,3'.
    span/offset sono la taratura: se il tracer manca le slice, ritoccali.
    beats=0 lo spegne."""
    if beats <= 0:
        return _fx_save("tracer", None)
    celle, da_sx = _fx_cells()
    order = order.strip()
    if order[:1].isdigit():
        ordine = [int(x) % celle for x in order.replace(" ", "").split(",")]
    elif order == "pos":
        ordine = da_sx
    elif order == "random":
        ordine = random.Random(seed).sample(range(celle), celle)
    else:
        ordine = list(range(celle))
    return _fx_save("tracer", {"path": _fx_pos(layer, param), "beats": beats,
                               "cells": celle, "order": ordine,
                               "span": span, "offset": offset})


@mcp.tool()
def slice_mix(layer: int, beats: float = 8, tilt: float = 0.25, seed: int = 0,
              span: float = 1.0, offset: float = 0.0,
              param: str = "Position X", tilt_param: str = "Rotate Z") -> str:
    """Transizione caotica ma calcolata: ogni 'beats' salta a una slice a caso e
    inclina la sorgente.

    Caotica perche' il salto e' casuale, calcolata perche' lo stesso 'seed' rifa
    la stessa identica sequenza: la provi a casa e la ritrovi uguale sul palco.
    'tilt' e' quanta rotazione (in unita' del parametro, 0 = nessuna).
    Cambiare seed = un'altra sequenza, sempre ripetibile. beats=0 lo spegne."""
    if beats <= 0:
        return _fx_save("mix", None)
    celle, _ = _fx_cells()
    return _fx_save("mix", {"path": _fx_pos(layer, param), "beats": beats,
                            "cells": celle, "seed": seed, "tilt": tilt,
                            "tilt_path": _fx_paths(layer, f"params/{tilt_param}"),
                            "span": span, "offset": offset})


@mcp.tool()
def slice_fx_status() -> str:
    """Cosa stanno facendo strobe, tracer e mix, e su cosa sono agganciati."""
    if not FX.exists():
        return "nessun effetto slice mai configurato"
    return f"{FX.read_text(encoding='utf-8')}\n{job_status()}"


# ---------------------------------------------------------------- ponte OBS (Spout)

SPOUT_SLOTS, SPOUT_NAME_LEN = 10, 256


def _spout_senders() -> list[str]:
    """Nomi dei sender Spout attivi, letti dalla memoria condivisa di Spout.

    Spout pubblica i nomi in una mappa Windows chiamata 'SpoutSenderNames':
    SPOUT_SLOTS slot da SPOUT_NAME_LEN byte, stringhe terminate da zero.
    Su una macchina senza Spout la mappa non esiste e torna vuota.
    """
    import mmap
    try:
        m = mmap.mmap(-1, SPOUT_SLOTS * SPOUT_NAME_LEN, "SpoutSenderNames")
    except OSError:
        return []
    with m:
        raw = m[:]
    out = []
    for i in range(SPOUT_SLOTS):
        n = raw[i * SPOUT_NAME_LEN:(i + 1) * SPOUT_NAME_LEN].split(b"\0", 1)[0]
        if n:
            out.append(n.decode("utf-8", "replace"))
    return out


@mcp.tool()
def spout_senders() -> list[str]:
    """Quali applicazioni stanno trasmettendo via Spout adesso (OBS, Unity, TouchDesigner...).
    Lista vuota = nessuno trasmette: in Resolume il pannello Sources non avra' niente da mostrare."""
    return _spout_senders()


@mcp.tool()
def obs_bridge(layer: int = 0, sender: str = "", connect: bool = True) -> str:
    """Verifica il ponte OBS -> Resolume via Spout e connette la clip sul layer.

    Controlla che OBS stia trasmettendo, trova la clip Spout gia' trascinata nella
    composizione e la fa partire. Se qualcosa manca dice esattamente cosa fare.
    layer=0 cerca su tutti i layer. sender vuoto = il primo sender trovato.
    connect=False si limita a riferire, senza toccare niente."""
    senders = _spout_senders()
    if not senders:
        return ("Nessun sender Spout attivo. In OBS: Tools -> Spout2 Output settings -> "
                "Enable Spout output (oppure aggiungi un 'Spout2 Filter' sulla singola sorgente). "
                "Se la voce non c'e', OBS va riavviato dopo l'installazione del plugin.")
    target = sender or senders[0]
    hits = []
    for li, lay in enumerate(call("GET", "/composition").get("layers", []), start=1):
        if layer and li != layer:
            continue
        for ci, clip in enumerate(lay.get("clips", []), start=1):
            name = pval(clip, "name") or ""
            if target.lower() in name.lower() or "spout" in name.lower():
                hits.append((li, ci, name, pval(clip, "connected")))
    if not hits:
        dove = f" sul layer {layer}" if layer else ""
        return (f"Sender attivi: {', '.join(senders)}. Nessuna clip Spout{dove}: nel pannello "
                f"Sources di Resolume trascina '{target}' in uno slot di clip, poi richiamami.")
    li, ci, name, stato = hits[0]
    altre = f" (altre {len(hits) - 1} clip Spout in composizione)" if len(hits) > 1 else ""
    if not connect:
        return f"Clip '{name}' su layer {li} colonna {ci}, stato '{stato}'. Sender attivi: {', '.join(senders)}.{altre}"
    trigger_clip(li, ci)
    return f"Ponte attivo: '{name}' connessa su layer {li} colonna {ci}, sender '{target}'.{altre}"


# ---------------------------------------------------------------- struttura composizione
# Rotte REST di Resolume 7 (Arena/Avenue) per creare, duplicare e caricare.
# Le rotte che accettano un URI (media, source://, effect://) vogliono il corpo
# come text/plain, con i segmenti del nome percent-encoded (spazi e parentesi
# danno 400 se non codificati).

from urllib.parse import quote as _quote, unquote as _unquote  # noqa: E402
import socket  # noqa: E402
import struct  # noqa: E402

_URI_PREFIXES = ("source:///", "effect:///", "file:///")
OSC_HOST = os.environ.get("RESOLUME_OSC_HOST", "127.0.0.1")
OSC_PORT = int(os.environ.get("RESOLUME_OSC_PORT", "7000"))


def call_text(method: str, path: str, text: str) -> Any:
    r = http.request(method, BASE + path, content=text.encode("utf-8"),
                     headers={"content-type": "text/plain"})
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    if not r.content:
        return "ok"
    try:
        return r.json()
    except ValueError:
        return r.text


def _encode_uri(uri: str) -> str:
    for prefix in _URI_PREFIXES[:2]:
        if uri.lower().startswith(prefix):
            segs = uri[len(prefix):].split("/")
            return prefix + "/".join(_quote(_unquote(x), safe="") for x in segs)
    return uri


def _media_uri(path_or_uri: str) -> str:
    """Percorso Windows/POSIX -> file:///...; source:// ed effect:// passano codificati."""
    v = path_or_uri.strip().strip('"')
    low = v.lower()
    if low.startswith(_URI_PREFIXES):
        return _encode_uri(v) if not low.startswith("file:///") else v
    v = v.replace("\\", "/")
    if not v.startswith("/"):
        v = "/" + v  # C:/... -> /C:/...
    return "file://" + _quote(v, safe="/:")


def _effect_base(layer: int = 0, column: int = 0) -> str:
    if layer and column:
        return f"/composition/layers/{layer}/clips/{column}"
    if layer:
        return f"/composition/layers/{layer}"
    return "/composition"


def _confirm(what: str, confirm: bool) -> str | None:
    if confirm:
        return None
    return f"CONFERMA RICHIESTA: {what}. Richiama con confirm=True per procedere."


@mcp.tool()
def get_product_info() -> Any:
    """Nome e versione di Resolume (Arena/Avenue). Controllo rapido che il web server risponda."""
    return call("GET", "/product")


@mcp.tool()
def list_sources() -> Any:
    """Elenca le sorgenti disponibili (generatori, capture, Spout/NDI).
    Caricane una con open_clip passando 'source:///video/<nome mostrato>'."""
    return call("GET", "/sources")


@mcp.tool()
def add_layer() -> Any:
    """Aggiunge un layer vuoto in cima alla composizione."""
    return call("POST", "/composition/layers/add")


@mcp.tool()
def add_column() -> Any:
    """Aggiunge una colonna in fondo alla composizione."""
    return call("POST", "/composition/columns/add")


@mcp.tool()
def add_deck() -> Any:
    """Aggiunge un deck nuovo."""
    return call("POST", "/composition/decks/add")


@mcp.tool()
def add_group() -> Any:
    """Aggiunge un gruppo di layer."""
    return call("POST", "/composition/layergroups/add")


@mcp.tool()
def duplicate(kind: str, index: int) -> Any:
    """Duplica un layer, una colonna o un deck.
    kind: 'layer' | 'column' | 'deck'. index parte da 1."""
    route = {"layer": "layers", "column": "columns", "deck": "decks"}.get(kind.lower())
    if not route:
        raise ValueError("kind deve essere layer, column o deck")
    return call("POST", f"/composition/{route}/{index}/duplicate")


@mcp.tool()
def close_deck(deck: int, confirm: bool = False) -> Any:
    """Chiude (rimuove) un deck dalla composizione. Distruttivo: serve confirm=True."""
    if msg := _confirm(f"chiude il deck {deck}", confirm):
        return msg
    return call("POST", f"/composition/decks/{deck}/close")


@mcp.tool()
def open_clip(layer: int, column: int, media: str) -> Any:
    """Carica un media o una sorgente in uno slot clip (sostituisce quello che c'e').
    media: percorso file ('C:\\\\Video\\\\loop.mov'), URI file:///, oppure
    'source:///video/<nome>' (vedi list_sources). Layer e colonna partono da 1."""
    return call_text("POST", f"/composition/layers/{layer}/clips/{column}/open", _media_uri(media))


@mcp.tool()
def clear_clip(layer: int, column: int, confirm: bool = False) -> Any:
    """Svuota uno slot clip (toglie il media). Distruttivo: serve confirm=True."""
    if msg := _confirm(f"svuota la clip layer {layer} colonna {column}", confirm):
        return msg
    return call("POST", f"/composition/layers/{layer}/clips/{column}/clear")


@mcp.tool()
def select_clip(layer: int, column: int) -> Any:
    """Seleziona una clip senza lanciarla (per vederne i parametri nel pannello)."""
    return call("POST", f"/composition/layers/{layer}/clips/{column}/select")


@mcp.tool()
def select_layer(layer: int) -> Any:
    """Seleziona un layer."""
    return call("POST", f"/composition/layers/{layer}/select")


@mcp.tool()
def set_clip_speed(layer: int, column: int, speed: float) -> str:
    """Velocita' di riproduzione di una clip (1.0 = normale, 0.5 = meta', 2 = doppia)."""
    path = f"/composition/layers/{layer}/clips/{column}"
    try:
        call("PUT", path, {"transport": {"controls": {"speed": {"value": speed}}}})
    except RuntimeError:
        call("PUT", path, {"transport": {"speed": {"value": speed}}})
    return f"clip {layer}/{column} speed = {speed}"


@mcp.tool()
def set_clip_position(layer: int, column: int, position: float) -> str:
    """Sposta la testina di una clip. position nelle unita' del transport della clip
    (vedi find_parameters('transport/position') per min/max)."""
    call("PUT", f"/composition/layers/{layer}/clips/{column}",
         {"transport": {"position": {"value": position}}})
    return f"clip {layer}/{column} position = {position}"


@mcp.tool()
def add_effect(effect: str, layer: int = 0, column: int = 0, kind: str = "video") -> Any:
    """Aggiunge un effetto in coda alla catena.
    effect: nome come in list_effects (es. 'Blur', 'Hue Rotate') o URI 'effect:///video/Blur'.
    Senza layer: sulla composizione; con layer: su quel layer; con layer+column: su quella clip.
    kind: 'video' | 'audio'."""
    kind = kind.lower()
    if kind not in ("video", "audio"):
        raise ValueError("kind deve essere video o audio")
    uri = effect if effect.lower().startswith("effect:///") else f"effect:///{kind}/{effect}"
    return call_text("POST", f"{_effect_base(layer, column)}/effects/{kind}/add", _encode_uri(uri))


@mcp.tool()
def remove_effect(effect: int, layer: int = 0, column: int = 0, kind: str = "video",
                  confirm: bool = False) -> Any:
    """Rimuove l'effetto numero 'effect' (parte da 1) dalla catena di composizione,
    layer o clip. Distruttivo: serve confirm=True."""
    if msg := _confirm(f"rimuove l'effetto {effect} ({kind})", confirm):
        return msg
    return call("DELETE", f"{_effect_base(layer, column)}/effects/{kind.lower()}/{effect}")


@mcp.tool()
def rename_effect(effect: int, name: str, layer: int = 0, column: int = 0,
                  kind: str = "video") -> Any:
    """Cambia il nome visualizzato di un effetto nella catena (effect parte da 1)."""
    return call("POST", f"{_effect_base(layer, column)}/effects/{kind.lower()}/{effect}/set-display-name",
                {"displayName": name})


@mcp.tool()
def disconnect_all(confirm: bool = False) -> Any:
    """Ferma tutte le clip della composizione (l'uscita va a nero). Serve confirm=True."""
    if msg := _confirm("ferma TUTTE le clip", confirm):
        return msg
    return call("POST", "/composition/disconnect-all")


@mcp.tool()
def composition_file(action: str, path: str = "", confirm: bool = False) -> Any:
    """Gestione file della composizione.
    action: 'save' (salva; con path = salva con nome) | 'open' (apre path .avc) | 'new'.
    'open' e 'new' sostituiscono la composizione attuale: serve confirm=True.
    Nota: alcune versioni di Arena non hanno queste rotte (404) -> usa File nel programma."""
    action = action.lower()
    if action not in ("save", "open", "new"):
        raise ValueError("action deve essere save, open o new")
    if action in ("open", "new") and (msg := _confirm(f"{action} sostituisce la composizione attuale", confirm)):
        return msg
    if action == "open" and not path:
        raise ValueError("serve path del file .avc")
    route = f"/composition/{action}"
    return call_text("POST", route, _media_uri(path)) if path else call("POST", route)


@mcp.tool()
def update_clip_thumbnail(layer: int, column: int) -> Any:
    """Rigenera la miniatura di una clip."""
    return call("POST", f"/composition/layers/{layer}/clips/{column}/thumbnail/update")


def _osc_pad(b: bytes) -> bytes:
    return b + b"\0" * (4 - len(b) % 4)


def _osc_message(address: str, values: list) -> bytes:
    tags, payload = ",", b""
    for v in values:
        if isinstance(v, bool):
            tags += "T" if v else "F"
        elif isinstance(v, int):
            tags += "i"; payload += struct.pack(">i", v)
        elif isinstance(v, float):
            tags += "f"; payload += struct.pack(">f", v)
        else:
            tags += "s"; payload += _osc_pad(str(v).encode())
    return _osc_pad(address.encode()) + _osc_pad(tags.encode()) + payload


@mcp.tool()
def osc_send(address: str, values: list | None = None) -> str:
    """Manda un messaggio OSC a Resolume (Preferences -> OSC -> OSC Input attivo, porta 7000).
    Utile per cio' che la REST API non espone. I trigger OSC scattano sul passaggio 0->1:
    per ripetere manda prima 0 e poi 1. Config: RESOLUME_OSC_HOST / RESOLUME_OSC_PORT.
    Esempio: osc_send('/composition/layers/1/clips/2/connect', [1])"""
    msg = _osc_message(address, list(values or []))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(msg, (OSC_HOST, OSC_PORT))
    return f"OSC {address} {values or []} -> {OSC_HOST}:{OSC_PORT}"


@mcp.tool()
def show_check() -> dict:
    """Controllo pre-show: segnala master a zero, layer in bypass o a opacita' zero,
    slot con nome ma senza media, BPM, numero di clip collegate. Non cambia niente."""
    c = call("GET", "/composition")
    problems, connected = [], 0
    master = pval(c.get("video") or {}, "opacity")
    if master is not None and master <= 0:
        problems.append("master opacity a 0")
    for li, layer in enumerate(c.get("layers", []), start=1):
        name = pval(layer, "name")
        if pval(layer, "bypassed"):
            problems.append(f"layer {li} ({name}) in bypass")
        op = pval(layer.get("video") or {}, "opacity")
        if op is not None and op <= 0:
            problems.append(f"layer {li} ({name}) a opacita' 0")
        for ci, clip in enumerate(layer.get("clips", []), start=1):
            conn = pval(clip, "connected")
            if conn in (True, "Connected", "connected"):
                connected += 1
            if pval(clip, "name") and not (clip.get("video") or clip.get("audio")):
                problems.append(f"clip {li}/{ci} ({pval(clip, 'name')}) senza media")
    return {
        "ok": not problems,
        "problemi": problems,
        "clip_collegate": connected,
        "layer": len(c.get("layers", [])),
        "colonne": len(c.get("columns", [])),
        "bpm": pval(c.get("tempocontroller") or {}, "tempo"),
    }


# ---------------------------------------------------------------- passepartout

@mcp.tool()
def api_request(method: str, path: str, body: dict | None = None) -> Any:
    """Chiamata grezza alla REST API di Resolume, per tutto quello che gli altri tool
    non coprono. path e' relativo a /api/v1, es. '/composition/layers/1'.
    method: GET, POST, PUT o DELETE."""
    return call(method.upper(), path if path.startswith("/") else "/" + path, body)


if __name__ == "__main__":
    mcp.run()
