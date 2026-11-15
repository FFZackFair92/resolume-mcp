# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Mappatura del palco per Resolume Arena 7.16.

L'Advanced Output NON e' nella REST API di questa versione: vive su disco.
  stato attuale : Documents\\Resolume Arena\\Preferences\\AdvancedOutput.xml
  preset        : Documents\\Resolume Arena\\Presets\\Advanced Output\\<nome>.xml

Due formati diversi, verificato il 2026-08-25:
  preferenze -> root <ScreenSetup>, serializzazione compatta
  preset     -> root <XmlState name="..."> che avvolge uno <ScreenSetup> completo,
                con blocchi di parametri (opacita', soft edge, warper) molto piu' ricchi.

Per questo un preset non si genera da zero ma si ricalca su un preset salvato da
Resolume (preset_template.xml): si sostituisce solo la geometria delle slice e si
lascia stare tutto il resto, che non sapremmo inventare.

Comandi:
  python resolume_mapping.py export [file.json]   legge la mappatura attuale
  python resolume_mapping.py apply  file.json [nome]   scrive un preset
  python resolume_mapping.py template <file.xml>  adotta un preset come stampo
  python resolume_mapping.py editor               ricuce lo stato nell'editor
  python resolume_mapping.py presets              elenca i preset esistenti
  python resolume_mapping.py output "Display 2"   manda lo screen su un'uscita fisica
Attenzione all'ordine dentro <layers>: una Mask taglia TUTTO quello che le sta
sotto nella lista. Cinque maschere separate si intersecano e lascia passare un
cerchio solo: per aprire piu' finestre serve UNA maschera con piu' Contour.
"""
import copy
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = Path.home() / "Documents" / "Resolume Arena"
PREFS = DOCS / "Preferences" / "AdvancedOutput.xml"
PRESETS = DOCS / "Presets" / "Advanced Output"
TEMPLATE = HERE / "preset_template.xml"
EDITOR = HERE / "stage_mapper.html"

# un quad e' sempre [in alto a sx, in alto a dx, in basso a dx, in basso a sx]
CORNERS = 4


# ------------------------------------------------------------------ lettura

def _screensetup(root):
    """Sia le preferenze che i preset contengono uno ScreenSetup, a profondita' diverse."""
    return root if root.tag == "ScreenSetup" else root.find(".//ScreenSetup")


def _quad(el) -> list[list[float]]:
    return [[float(v.get("x")), float(v.get("y"))] for v in el.findall("v")]


def _param(params_el, name: str, default=None):
    if params_el is None:
        return default
    for p in params_el:
        if p.get("name") == name:
            return p.get("value", default)
    return default


def active_preset() -> str | None:
    """Il nome del preset attivo, se lo screen setup ne sta usando uno.

    Quando si carica un preset, Resolume svuota AdvancedOutput.xml e ci lascia
    solo <ScreenSetup presetFile="NOME"/>: da quel momento lo stato vero e' il
    file del preset. Verificato il 2026-08-25.
    """
    if not PREFS.exists():
        return None
    root = ET.parse(PREFS).getroot()
    name = _screensetup(root).get("presetFile")
    return name or None


def read_setup(path: Path | None = None) -> dict:
    """Legge lo screen setup attivo (o il file indicato) e lo riduce a JSON."""
    if path is None:
        preset = active_preset()
        path = PRESETS / f"{preset}.xml" if preset else PREFS
    ss = _screensetup(ET.parse(path).getroot())
    tex = ss.find("CurrentCompositionTextureSize")
    out = {
        "file": str(path),
        "composition": {"width": int(float(tex.get("width"))),
                        "height": int(float(tex.get("height")))} if tex is not None else None,
        "screens": [],
    }
    for screen in ss.findall("./screens/Screen"):
        dev = screen.find("./OutputDevice/")
        slices = []
        for sl in (screen.find("layers") if screen.find("layers") is not None else []):
            voce = {
                "name": _param(sl.find("./Params[@name='Common']"), "Name", sl.tag),
                "source": _param(sl.find("./Params[@name='Input']"), "Input Source", "0:1"),
                "input": _quad(sl.find("InputRect")),
                "output": _quad(sl.find("OutputRect")),
            }
            if sl.tag == "Mask":
                voce["kind"] = "mask"
                # una maschera puo' avere piu' contorni: vanno riletti tutti,
                # altrimenti il giro scrivi/rileggi ne perde per strada
                voce["shapes"] = [_quad(c.find("points"))
                                  for c in sl.findall("./ShapeObject/Shape/Contour")]
                voce["invert"] = _param(sl.find("./Params[@name='Output']"), "Invert") == "1"
            slices.append(voce)
        # un device fisico porta width/height come attributi, uno virtuale li ha
        # come parametri: vanno letti in entrambi i modi
        misure = {}
        if dev is not None:
            for k in ("width", "height"):
                v = dev.get(k) or _param(dev.find("./Params[@name='Params']"), k.capitalize())
                misure[k] = int(float(v)) if v else None
        out["screens"].append({
            "name": screen.get("name"),
            "device": dev.get("name") if dev is not None else None,
            "device_type": dev.tag if dev is not None else None,
            "width": misure.get("width"),
            "height": misure.get("height"),
            "slices": slices,
        })
    return out


# ------------------------------------------------------------------ scrittura

def _bezier(quad: list[list[float]]) -> list[tuple[float, float]]:
    """I 16 punti di controllo del warper: bilineare sul quad, cioe' nessuna
    deformazione oltre a quella gia' descritta dai 4 angoli."""
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = quad  # TL, TR, BR, BL
    pts = []
    for i in range(4):
        v = i / 3.0
        lx, ly = ax + (dx - ax) * v, ay + (dy - ay) * v   # bordo TL->BL
        rx, ry = bx + (cx - bx) * v, by + (cy - by) * v   # bordo TR->BR
        for j in range(4):
            u = j / 3.0
            pts.append((lx + (rx - lx) * u, ly + (ry - ly) * u))
    return pts


def _bbox_quad(points) -> list[list[float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _setquad(el, points) -> None:
    for v in el.findall("v"):
        el.remove(v)
    for x, y in points:
        ET.SubElement(el, "v", {"x": repr(float(x)), "y": repr(float(y))})


def _setparam(params_el, name: str, value: str) -> None:
    for p in params_el:
        if p.get("name") == name:
            p.set("value", value)
            return
    raise ValueError(f"parametro '{name}' assente nello stampo")


def _fill(el, sl: dict, uid: int):
    """Riempie la geometria di una Slice clonata dallo stampo."""
    name = sl.get("name") or "Slice"
    inp = [[float(a), float(b)] for a, b in sl["input"]]
    outp = [[float(a), float(b)] for a, b in sl["output"]]
    if len(inp) != len(outp):
        raise ValueError(f"slice '{name}': input e output hanno un numero di punti diverso "
                         f"({len(inp)} contro {len(outp)}); il punto i dell'ingresso "
                         f"finisce sul punto i dell'uscita, quindi devono corrispondere")
    if len(outp) < 3:
        raise ValueError(f"slice '{name}': servono almeno 3 punti")

    el.set("uniqueId", str(uid))
    _setparam(el.find("./Params[@name='Common']"), "Name", name)
    _setparam(el.find("./Params[@name='Input']"), "Input Source", sl.get("source") or "0:1")

    for tag, quad in (("InputRect", inp), ("OutputRect", outp)):
        rect = el.find(tag)
        rect.set("orientation", "0")
        _setquad(rect, quad)
    # il warper lavora su una griglia 4x4: per un poligono si appoggia al suo
    # rettangolo contenitore, che e' l'unica cosa sensata da dargli
    quad = outp if len(outp) == CORNERS else _bbox_quad(outp)
    _setquad(el.find(".//BezierWarper/vertices"), _bezier(quad))
    _setquad(el.find(".//Homography/src"), quad)
    _setquad(el.find(".//Homography/dst"), quad)
    return el


KAPPA = 0.5522847498307933  # quanto lungo dev'essere il controllo bezier per fare un cerchio


def cerchio_bezier(cx: float, cy: float, r: float) -> list[list[float]]:
    """I 12 punti di un contorno circolare, nel formato delle maschere di Resolume:
    per ognuno dei 4 quadranti un'ancora e i due controlli che portano al successivo.
    Ricavato leggendo una maschera tonda fatta a mano nell'Advanced Output."""
    k = KAPPA * r
    anc = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]      # alto, dx, basso, sx
    ctrl = [((cx + k, cy - r), (cx + r, cy - k)),
            ((cx + r, cy + k), (cx + k, cy + r)),
            ((cx - k, cy + r), (cx - r, cy + k)),
            ((cx - r, cy - k), (cx - k, cy - r))]
    punti = []
    for a, (c1, c2) in zip(anc, ctrl):
        punti += [list(a), list(c1), list(c2)]
    return punti


def _mask_el(el, mk: dict, uid: int):
    """Riempie una Mask clonata dallo stampo."""
    name = mk.get("name") or "Mask"
    # una maschera puo' avere piu' contorni: e' l'unico modo per aprire piu'
    # finestre con una sola maschera, visto che ogni maschera taglia tutto
    # quello che sta sotto di lei nella lista
    if "circles" in mk:
        contorni = [cerchio_bezier(*c) for c in mk["circles"]]
    elif "shapes" in mk:
        contorni = mk["shapes"]
    else:
        contorni = [mk.get("shape") or cerchio_bezier(*mk["circle"])]
    quad = _bbox_quad([p for c in contorni for p in c])

    el.set("uniqueId", str(uid))
    _setparam(el.find("./Params[@name='Common']"), "Name", name)
    if "invert" in mk:
        _setparam(el.find("./Params[@name='Output']"), "Invert", "1" if mk["invert"] else "0")

    # l'ingresso di una maschera e' sempre il quadrato normalizzato -0.5..0.5
    _setquad(el.find("InputRect"), [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]])
    _setquad(el.find("OutputRect"), quad)
    _setquad(el.find("./ShapeObject/Rect"), quad)
    shape = el.find("./ShapeObject/Shape")
    proto = copy.deepcopy(shape.find("Contour"))
    for c in list(shape):
        shape.remove(c)
    for forma in contorni:
        c = copy.deepcopy(proto)
        c.set("closed", "1")
        _setquad(c.find("points"), forma)
        c.find("segments").text = "C" * (len(forma) // 3)
        shape.append(c)
    return el


def build(data: dict, name: str, template: Path = TEMPLATE) -> ET.ElementTree:
    """Ricalca lo stampo sostituendo solo le slice.

    Why: schermo, device di uscita (con un deviceId di registro che non possiamo
    conoscere), soft edging e i blocchi di parametri per slice sono roba di
    Resolume. Generarli a mano sarebbe indovinare; clonarli e' esatto.
    """
    if not template.exists():
        raise FileNotFoundError(
            f"manca lo stampo {template}: salva un preset qualsiasi dall'Advanced "
            f"Output di Resolume e passalo a 'template'")
    tree = ET.parse(template)
    root = tree.getroot()
    if root.tag == "XmlState":
        root.set("name", name)
    ss = _screensetup(root)

    screens = ss.findall("./screens/Screen")
    wanted = {s["name"]: s for s in data["screens"]}
    if len(screens) == 1 and len(wanted) == 1 and screens[0].get("name") not in wanted:
        wanted = {screens[0].get("name"): next(iter(wanted.values()))}

    uid = int(time.time() * 1000)
    touched = 0
    for screen in screens:
        spec = wanted.get(screen.get("name"))
        if spec is None:
            continue
        layers = screen.find("layers")
        proto = {t: layers.find(t) for t in ("Slice", "Mask")}
        if proto["Slice"] is None:
            raise ValueError(f"lo stampo non ha slice sotto '{screen.get('name')}'")
        proto = {t: copy.deepcopy(e) for t, e in proto.items() if e is not None}
        for child in list(layers):
            layers.remove(child)
        for sl in spec["slices"]:
            tipo = "Mask" if sl.get("kind") == "mask" else "Slice"
            if tipo not in proto:
                raise ValueError(
                    "lo stampo non contiene nessuna Mask da cui copiare: creane una a "
                    "mano nell'Advanced Output, risalva il preset e rifai 'template'")
            fill = _mask_el if tipo == "Mask" else _fill
            layers.append(fill(copy.deepcopy(proto[tipo]), sl, uid))
            uid += 1
        touched += 1
    if not touched:
        raise ValueError(f"nessuno screen dello stampo corrisponde a {list(wanted)}")
    return tree


def write_preset(data: dict, name: str) -> Path:
    PRESETS.mkdir(parents=True, exist_ok=True)
    dest = PRESETS / f"{name}.xml"
    tree = build(data, name)
    ET.indent(tree, space="\t")
    tree.write(dest, encoding="utf-8", xml_declaration=True)
    # copia di servizio: Resolume ripulisce la sua cartella dei preset quando ne
    # salva uno suo, e si porta via anche i nostri file
    (HERE / "presets").mkdir(exist_ok=True)
    tree.write(HERE / "presets" / f"{name}.xml", encoding="utf-8", xml_declaration=True)
    return dest


def refresh_editor(setup: dict | None = None, sfondo: Path | None = None) -> Path:
    """Rimette nell'editor HTML la mappatura attuale.

    Why: l'editor gira in chat, isolato dalla rete locale, quindi non puo'
    leggersi da solo lo stato di Resolume: glielo si cuce dentro prima di aprirlo.
    """
    data = setup or read_setup()
    data.pop("file", None)
    line = "const SETUP = " + json.dumps(data, ensure_ascii=False) + ";"
    text = EDITOR.read_text(encoding="utf-8")
    text, n = re.subn(r"^const SETUP = .*;$", lambda m: line, text, count=1, flags=re.M)
    if not n:
        raise ValueError(f"riga 'const SETUP' non trovata in {EDITOR}")

    if sfondo is not None:
        # la foto va cucita dentro come data URI: la pagina gira in chat, isolata,
        # e non puo' andarsi a prendere un file dal disco
        import base64
        tipo = "jpeg" if sfondo.suffix.lower() in (".jpg", ".jpeg") else "png"
        dati = base64.b64encode(sfondo.read_bytes()).decode("ascii")
        riga = f'const SFONDO = "data:image/{tipo};base64,{dati}";'
        text, k = re.subn(r"^const SFONDO = .*;.*$", lambda m: riga, text, count=1, flags=re.M)
        if not k:
            raise ValueError(f"riga 'const SFONDO' non trovata in {EDITOR}")

    EDITOR.write_text(text, encoding="utf-8")
    return EDITOR


# ------------------------------------------------------------- uscita fisica

def known_id_hashes() -> dict[str, str]:
    """deviceId -> idHash, raccolti dai file che ha scritto Resolume.

    Why: l'idHash non e' un hash che sappiamo ricalcolare (provati fnv-1/1a,
    murmur64, djb2, sdbm, il hashCode64 di JUCE: nessuno torna). Ma Resolume lo
    scrive ogni volta che salva, quindi lo si pesca da un suo file invece di
    inventarlo. Se il device non l'ha mai visto restera' "0" e Resolume si
    riallineera' da sola sul deviceId, che e' l'identita' vera.
    """
    fonti = [PREFS, HERE / "AdvancedOutput.backup.xml", TEMPLATE,
             *PRESETS.glob("*.xml"), *(HERE / "presets").glob("*.xml")]
    trovati: dict[str, str] = {}
    for f in fonti:
        try:
            root = ET.parse(f).getroot()
        except (OSError, ET.ParseError):
            continue
        for el in root.iter():
            if el.tag.startswith("OutputDevice") and el.get("deviceId"):
                trovati.setdefault(el.get("deviceId"), el.get("idHash", "0"))
    return trovati


def _scale_pts(el, s: float, ox: float, oy: float) -> None:
    for v in el.findall("v"):
        v.set("x", repr(float(v.get("x")) * s + ox))
        v.set("y", repr(float(v.get("y")) * s + oy))


def _rescale_screen(screen, s: float, ox: float, oy: float) -> int:
    """Porta nello spazio del nuovo device tutto cio' che vive in coordinate di
    uscita: quad di uscita, griglia del warper, omografia, maschere.
    L'InputRect resta dov'e': quello e' spazio composizione, non spazio schermo.
    """
    layers = screen.find("layers")
    if layers is None:
        return 0
    n = 0
    for sl in layers:
        for tag in ("OutputRect", "./ShapeObject/Rect", ".//BezierWarper/vertices"):
            el = sl.find(tag)
            if el is not None:
                _scale_pts(el, s, ox, oy)
        src, dst = sl.find(".//Homography/src"), sl.find(".//Homography/dst")
        if dst is not None:
            # se src e dst coincidono l'omografia e' l'identita' e va tenuta tale,
            # quindi si scalano tutte e due; se sono diverse src e' spazio di
            # ingresso e non va toccata
            if src is not None and _quad(src) == _quad(dst):
                _scale_pts(src, s, ox, oy)
            _scale_pts(dst, s, ox, oy)
        for c in sl.findall("./ShapeObject/Shape/Contour"):
            _scale_pts(c.find("points"), s, ox, oy)
        n += 1
    return n


def _device_size(dev) -> tuple[int, int]:
    misure = []
    for k in ("width", "height"):
        v = dev.get(k) or _param(dev.find("./Params[@name='Params']"), k.capitalize())
        misure.append(int(float(v)))
    return misure[0], misure[1]


def assign_display(display, screen: str | None = None, preset: str | None = None,
                   stretch: bool = False) -> dict:
    """Punta uno screen dell'Advanced Output su un'uscita fisica e ci riadatta le slice.

    Il preset nasce quasi sempre su uno schermo virtuale (comodo per disegnare la
    mappatura), che pero' non esce da nessuna parte. Qui quel device viene
    sostituito con il display vero e la geometria viene riscalata di conseguenza,
    per default mantenendo le proporzioni e centrando (con 'stretch' invece si
    riempie tutto, deformando).
    """
    import displays as win  # roba di Windows: importata qui, non serve al resto

    target = win.find(display)
    preset = preset or active_preset()
    if not preset:
        raise ValueError("nessun preset attivo nell'Advanced Output: caricane uno "
                         "da Resolume (Output -> Advanced) e riprova")
    path = PRESETS / f"{preset}.xml"
    if not path.exists():
        raise FileNotFoundError(f"il preset attivo '{preset}' non e' su disco: {path}")

    tree = ET.parse(path)
    ss = _screensetup(tree.getroot())
    schermi = ss.findall("./screens/Screen")
    if screen:
        scelti = [s for s in schermi if s.get("name") == screen]
        if not scelti:
            raise ValueError(f"nessuno screen '{screen}' nel preset "
                             f"(ci sono: {[s.get('name') for s in schermi]})")
        el = scelti[0]
    elif len(schermi) == 1:
        el = schermi[0]
    else:
        raise ValueError(f"il preset ha piu' screen, dimmi quale: "
                         f"{[s.get('name') for s in schermi]}")

    dev = el.find("OutputDevice")
    vecchio = dev.find("*")
    vw, vh = _device_size(vecchio)
    nw, nh = int(target["width"]), int(target["height"])

    if stretch:
        raise NotImplementedError("lo stretch non uniforme deforma il mapping; "
                                  "se serve davvero, va fatto slice per slice")
    s = min(nw / vw, nh / vh)
    ox, oy = (nw - vw * s) / 2, (nh - vh * s) / 2
    n = _rescale_screen(el, s, ox, oy)

    nuovo = ET.Element("OutputDeviceDisplay", {
        "name": target["name"],
        "deviceId": target["device_key"],
        "idHash": known_id_hashes().get(target["device_key"], "0"),
        "fullscreen": "1",
        "width": str(nw),
        "height": str(nh),
    })
    dev.clear()
    dev.append(nuovo)

    ET.indent(tree, space="\t")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    (HERE / "presets").mkdir(exist_ok=True)
    tree.write(HERE / "presets" / f"{preset}.xml", encoding="utf-8", xml_declaration=True)

    return {
        "preset": preset,
        "file": str(path),
        "screen": el.get("name"),
        "da": f"{vecchio.tag} {vw}x{vh}",
        "a": f"{target['name']} ({target['monitor']}) {nw}x{nh} su {target['device']}",
        "scala": round(s, 4),
        "bordi": {"x": round(ox, 1), "y": round(oy, 1)},
        "slice": n,
        "idHash": nuovo.get("idHash"),
    }


# --------------------------------------------------------- contorni (outline)

OUT_MARK = "~out"   # marca le slice generate: si riconoscono per rifarle o toglierle


def base_slices(data: dict) -> list[dict]:
    """Le slice vere: niente maschere, niente contorni generati da noi."""
    return [s for scr in data["screens"] for s in scr["slices"]
            if s.get("kind") != "mask" and OUT_MARK not in (s.get("name") or "")]


def strip_cells(n: int, comp: dict, y: float, h: float) -> list[list[list[float]]]:
    """La striscia di controllo: n celle affiancate nello spazio composizione.

    Why: una slice non e' pilotabile dal vivo (l'Advanced Output non e' nella REST
    API). Ma quello che una slice *mostra* si', perche' e' un pezzo di
    composizione. Quindi il contorno della slice i punta sulla cella i: accendi
    la cella e si accende il contorno, e la geometria non la tocchi piu'.
    """
    w = comp["width"] / max(1, n)
    return [[[i * w, y], [(i + 1) * w, y], [(i + 1) * w, y + h], [i * w, y + h]]
            for i in range(n)]


def _shrink(quad: list[list[float]], width: float) -> list[list[float]]:
    """Il quad rimpicciolito verso il suo centro, di circa 'width' pixel per lato."""
    cx = sum(p[0] for p in quad) / len(quad)
    cy = sum(p[1] for p in quad) / len(quad)
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    lato = min(max(xs) - min(xs), max(ys) - min(ys))
    if lato <= 2 * width:
        raise ValueError(f"contorno da {width}px troppo spesso per una slice di {lato:.0f}px")
    k = 1 - 2 * width / lato
    return [[cx + (x - cx) * k, cy + (y - cy) * k] for x, y in quad]


def add_outlines(data: dict, width: float = 6, strip_y: float = 0,
                 strip_h: float = 8) -> int:
    """Circonda ogni slice con 4 slice sottili che pescano dalla striscia di controllo.

    width <= 0 toglie i contorni e basta. Non dipende da quante slice ci sono ne'
    da come si chiamano: legge la mappatura che trova e ci si adatta.
    """
    comp = data.get("composition") or {"width": 1280, "height": 720}
    celle = strip_cells(len(base_slices(data)), comp, strip_y, strip_h)
    fatte, i = 0, 0
    for screen in data["screens"]:
        vive = [s for s in screen["slices"] if OUT_MARK not in (s.get("name") or "")]
        nuove = []
        for sl in vive:
            if sl.get("kind") == "mask":
                continue
            cella, i = celle[i], i + 1
            if width <= 0:
                continue
            fuori = [[float(x), float(y)] for x, y in sl["output"]]
            if len(fuori) != CORNERS:
                continue          # un contorno ha senso solo attorno a un quad
            dentro = _shrink(fuori, width)
            nuove += [{"name": f"{sl.get('name', 'Slice')} {OUT_MARK}{k}",
                       "source": sl.get("source") or "0:1",
                       "input": cella,
                       "output": [fuori[k], fuori[(k + 1) % CORNERS],
                                  dentro[(k + 1) % CORNERS], dentro[k]]}
                      for k in range(CORNERS)]
        # in cima alla lista: chi sta piu' in alto sta davanti, e nessuna Mask
        # piu' in basso puo' tagliare il contorno
        screen["slices"] = nuove + vive
        fatte += len(nuove)
    return fatte


def _selftest() -> None:
    finta = {"composition": {"width": 1280, "height": 720},
             "screens": [{"name": "S", "slices": [
                 {"name": "A", "source": "0:1",
                  "input": [[0, 0], [100, 0], [100, 100], [0, 100]],
                  "output": [[0, 0], [200, 0], [200, 200], [0, 200]]},
                 {"kind": "mask", "name": "M", "shapes": [[[0, 0], [1, 1], [2, 2]]]},
                 {"name": "B", "source": "0:1",
                  "input": [[0, 0], [100, 0], [100, 100], [0, 100]],
                  "output": [[300, 0], [400, 0], [400, 100], [300, 100]]}]}]}
    n = add_outlines(copy.deepcopy(finta), width=10)
    assert n == 8, n
    fatta = copy.deepcopy(finta)
    add_outlines(fatta, width=10)
    nomi = [s["name"] for s in fatta["screens"][0]["slices"]]
    assert nomi.index(f"A {OUT_MARK}0") < nomi.index("A"), "il contorno deve stare davanti"
    assert nomi.index(f"A {OUT_MARK}0") < nomi.index("M"), "e sopra la maschera, o la taglia"
    # rifarlo non deve accumulare, e width 0 deve pulire
    add_outlines(fatta, width=10)
    assert sum(OUT_MARK in s["name"] for s in fatta["screens"][0]["slices"]) == 8
    add_outlines(fatta, width=0)
    assert not any(OUT_MARK in s["name"] for s in fatta["screens"][0]["slices"])
    # il contorno della slice i deve pescare dalla cella i, non da un'altra
    fatta = copy.deepcopy(finta)
    add_outlines(fatta, width=10)
    celle = strip_cells(2, finta["composition"], 0, 8)
    per_nome = {s["name"]: s for s in fatta["screens"][0]["slices"]}
    assert per_nome[f"A {OUT_MARK}0"]["input"] == celle[0]
    assert per_nome[f"B {OUT_MARK}0"]["input"] == celle[1]
    print("selftest ok")


# ------------------------------------------------------------------ cli

def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "export":
        data = read_setup(Path(argv[1]) if len(argv) > 1 and argv[1].endswith(".xml") else None)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        dest = next((a for a in argv[1:] if a.endswith(".json")), None)
        if dest:
            Path(dest).write_text(text, encoding="utf-8")
            print(f"mappatura salvata in {dest}")
        else:
            print(text)
    elif cmd == "apply":
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        data = data.get("mapping", data)
        name = argv[2] if len(argv) > 2 else (data.get("preset") or active_preset() or "chat")
        dest = write_preset(data, name)
        n = sum(len(s["slices"]) for s in data["screens"])
        print(f"preset scritto: {dest} ({n} slice)")
    elif cmd == "template":
        src = Path(argv[1])
        TEMPLATE.write_bytes(src.read_bytes())
        print(f"stampo adottato da {src}")
    elif cmd == "editor":
        foto = next((Path(a) for a in argv[1:] if not a.startswith("-")), None)
        print(f"editor aggiornato: {refresh_editor(sfondo=foto)}"
              + (f" (con la foto {foto})" if foto else ""))
    elif cmd == "presets":
        PRESETS.mkdir(parents=True, exist_ok=True)
        print(json.dumps(sorted(p.stem for p in PRESETS.glob("*.xml")), ensure_ascii=False))
    elif cmd == "output":
        esito = assign_display(argv[1], screen=argv[2] if len(argv) > 2 else None)
        print(json.dumps(esito, indent=2, ensure_ascii=False))
    elif cmd == "outline":
        data = read_setup()
        n = add_outlines(data, width=float(argv[1]) if len(argv) > 1 else 6)
        nome = active_preset() or "chat"
        print(f"{n} slice di contorno -> {write_preset(data, nome)}")
    elif cmd == "selftest":
        _selftest()
    else:
        print(f"comando sconosciuto: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
