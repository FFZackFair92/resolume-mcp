"""Test offline dei tool 1.3 contro il finto Resolume (nessun Resolume necessario).
    python tests/test_offline.py"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import fake_resolume as F  # noqa: E402

F.install()
ao = Path(tempfile.mkdtemp()) / "AdvancedOutput.xml"
ao.write_text('<ScreenSetup><screens><Screen name="Proiettore"><Slice name="Palco"/><Slice name="Ledwall"/></Screen></screens></ScreenSetup>')
os.environ["RESOLUME_ADVANCED_OUTPUT"] = str(ao)
import resolume_mcp as m  # noqa: E402

m.AO_BACKUPS = Path(tempfile.mkdtemp()) / "output_backups"
ok = 0


def check(name, cond, info=""):
    global ok
    assert cond, f"{name}: {info}"
    ok += 1
    print("  ok  ", name)


def fails(needle, fn, *a, **k):
    try:
        fn(*a, **k)
    except Exception as e:
        assert needle.lower() in str(e).lower(), (needle, str(e))
        return True
    raise AssertionError(f"mancava l'errore: {needle}")


r = m.open_resolume()
check("open_resolume se gia' aperto", r["already_running"] and r["product"]["name"] == "Arena", r)
r = m.set_parameter("layers[0]:Layer 1/video/opacity", 0.4, verify=True)
check("set_parameter verify", r["value_before"] == 1.0 and r["value_after"] == 0.4 and r["verified"], r)
check("set_parameter senza verify", m.set_parameter("layers[0]:Layer 1/video/opacity", 1.0).endswith("= 1.0"))
r = m.watch_parameters("opacity", seconds=0.6, interval=0.1)
check("watch_parameters", r["watched"] >= 3 and r["samples"] >= 3 and not r["changed"], r)
r = m.tempo("set", bpm=128)
check("tempo set", r["bpm"] == 128.0, r)
F.TAPS.clear()
r = m.tempo("tap", bpm=240, taps=3)
check("tempo tap batte 3 volte", len(F.TAPS) == 3, F.TAPS)
check("tempo resync", m.tempo("resync")["action"] == "resync")
fails("action", m.tempo, "boh")
r = m.crossfader(phase=0.5, layer=2, side="b")
check("crossfader", r["phase"] == 0.5 and r["layers"][1]["side"] == "B", r)
fails("side", m.crossfader, layer=1, side="C")
r = m.clip_transport(1, 1, direction="backward", play_mode="bounce", speed=0.5)
check("clip_transport", r["direction"] == "<" and r["play_mode"] == "Bounce" and r["speed"] == 0.5, r)
r = m.clip_transport(1, 1, direction="pause", play_mode="once", restart=True)
check("clip_transport pausa e restart", r["direction"] == "||" and r["play_mode"] == "Play Once" and r["position"] == 0.0, r)
fails("non valido", m.clip_transport, 1, 1, direction="laterale")
r = m.layer_summary(1)
check("layer_summary", r["blend_mode"] == "Alpha" and r["effects"][0]["params"]["Scale"] == 100.0 and r["clips"][0]["name"] == "loop.mov", r)
r = m.layer_settings(1, name="Visual", blend_mode="add", volume=-6, transition_duration=1.5, transition_blend="wipe ellipse")
check("layer_settings", r["name"] == "Visual" and r["blend_mode"] == "Add" and r["volume"] == -6.0
      and r["transition"] == {"duration": 1.5, "blend": "Wipe Ellipse"}, r)
fails("blend_mode non valido", m.layer_settings, 1, blend_mode="Plasma")
img = m.clip_thumbnail(1, 1)
check("clip_thumbnail", img.data[:4] == b"\x89PNG")
fails("non disponibile", m.clip_thumbnail, 9, 9)
r = m.advanced_output()
check("advanced_output status", r["screens"][0]["name"] == "Proiettore" and r["screens"][0]["items"] == 2, r)
r = m.advanced_output("backup", "prima")
check("advanced_output backup", r["backup"] == "prima" and Path(r["file"]).is_file(), r)
ao.write_text('<ScreenSetup><screens><Screen name="Proiettore"><Slice name="Palco"/></Screen><Screen name="Led"/></screens></ScreenSetup>')
r = m.advanced_output("diff", "prima")
check("advanced_output diff", not r["identical"] and r["screens_added"] == ["Led"] and r["slices_removed"] == ["Ledwall"], r)
r = m.advanced_output("restore", "prima")
check("advanced_output restore chiede conferma", r.get("needs_confirm"))
r = m.advanced_output("restore", "prima", confirm=True)
check("advanced_output restore", "Ledwall" in ao.read_text() and any("prima-del-restore" in b for b in m.advanced_output("list")["backups"]), r)
fails("esce dalla cartella", m.advanced_output, "backup", "../fuori")
fails("non trovato", m.advanced_output, "diff", "manca")

names = sorted(t.name for t in asyncio.run(m.mcp.list_tools()))
check(f"{len(names)} tool registrati", len(names) == 65, len(names))
print(f"\n{ok} ok")
