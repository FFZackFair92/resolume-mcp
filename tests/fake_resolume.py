"""Finto Resolume per i test offline: sostituisce httpx con un client che risponde come la REST API v1
(GET/PUT parziali con array riempiti di {}, POST di qualche azione). Non sostituisce una prova dal vivo."""
import copy
import json
import sys
import types

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")


def P(v, **kw):
    return {"id": id(kw) % 100000, "value": v, **kw}


def clip(name, connected=False):
    return {"name": P(name), "connected": P("Connected" if connected else "Empty"), "video": {} if name else None,
            "transport": {"position": P(0.0, min=0.0, max=10.0),
                          "controls": {"playdirection": P(">", options=["<", "||", ">"]),
                                       "playmode": P("Loop", options=["Loop", "Bounce", "Random", "Play Once", "Play Once & Hold"]),
                                       "speed": P(1.0)}}}


def layer(name):
    return {"name": P(name), "bypassed": P(False), "solo": P(False),
            "crossfadergroup": P("None", options=["None", "A", "B"]),
            "video": {"opacity": P(1.0), "mixer": {"Blend Mode": P("Alpha", options=["Alpha", "Add", "Screen", "Multiply"])},
                      "effects": [{"name": P("Transform"), "bypassed": P(False), "params": {"Scale": P(100.0)}}]},
            "audio": {"volume": P(0.0)},
            "transition": {"duration": P(0.0), "blend_mode": P("Alpha", options=["Alpha", "Wipe Ellipse"])},
            "clips": [clip("loop.mov", True), clip("")]}


STATE = {
    "name": P("Finta"), "video": {"opacity": P(1.0)},
    "tempocontroller": {"tempo": P(120.0), "tempo_tap": P(False), "resync": P(False), "tempo_push": P(False), "tempo_pull": P(False)},
    "crossfader": {"phase": P(0.0, min=-1, max=1)},
    "columns": [{"name": P("Col 1")}], "decks": [{"name": P("Deck 1"), "selected": P(True)}],
    "layers": [layer("Layer 1"), layer("Layer 2")],
}
LOG = []
TAPS = []


def merge(dst, src):
    if isinstance(src, dict):
        for k, v in src.items():
            if k == "value" and isinstance(dst, dict):
                if k in dst and dst.get("options") and v not in dst["options"]:
                    raise ValueError("invalid option")
                if k in dst and dst[k] is False and v is True and isinstance(dst.get("id"), int):
                    TAPS.append(id(dst))
                dst[k] = v
            elif isinstance(v, (dict, list)) and k in dst:
                merge(dst[k], v)
            else:
                dst[k] = v
    elif isinstance(src, list):
        for i, v in enumerate(src):
            if v:
                merge(dst[i], v)


class Resp:
    def __init__(self, code, body=b"", ctype="application/json"):
        self.status_code, self.content = code, body if isinstance(body, bytes) else json.dumps(body).encode()
        self.text = self.content.decode("latin1")

    def json(self):
        return json.loads(self.content)


def route(method, path, body):
    LOG.append((method, path))
    parts = [p for p in path.split("/") if p][2:]  # dopo api/v1
    if parts == ["product"]:
        return Resp(200, {"name": "Arena", "major": 7, "minor": 26})
    if parts[:1] != ["composition"]:
        return Resp(404, b"not found")
    node = STATE
    rest = parts[1:]
    try:
        while rest and rest[0] in ("layers", "clips") and len(rest) > 1 and rest[1].isdigit():
            node = node[rest[0]][int(rest[1]) - 1]
            rest = rest[2:]
    except IndexError:
        return Resp(404, b"no such index")
    if rest == ["thumbnail"] and method == "GET":
        return Resp(200, PNG, "image/png")
    if rest:
        return Resp(200, b"")
    if method == "GET":
        return Resp(200, copy.deepcopy(node))
    if method == "PUT":
        try:
            merge(node, body)
        except ValueError as e:
            return Resp(412, str(e).encode())
        return Resp(204, b"")
    return Resp(405, b"")


class Client:
    def __init__(self, timeout=None):
        pass

    def request(self, method, url, json=None, content=None, headers=None):
        path = url.split("://", 1)[-1]
        path = path[path.index("/"):]
        return route(method, path, json)


def install():
    sys.modules["httpx"] = types.SimpleNamespace(Client=Client)
