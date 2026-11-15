# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""I display di Windows, visti come li vede l'Advanced Output di Resolume.

Resolume identifica un'uscita fisica con la chiave di registro dell'adapter
video, es. \\Registry\\Machine\\System\\CurrentControlSet\\Control\\Video\\{GUID}\\0001.
E' esattamente il DeviceKey che restituisce EnumDisplayDevices, quindi si puo'
ricavare senza chiedere niente a Resolume.

  python displays.py list                  elenca i display attivi
  python displays.py modes \\\\.\\DISPLAY2     le risoluzioni accettate
  python displays.py set \\\\.\\DISPLAY2 1024 768
"""
import ctypes
import json
import sys
from ctypes import wintypes

CCHDEVICENAME = 32
CCHFORMNAME = 32
ENUM_CURRENT_SETTINGS = -1
ATTACHED_TO_DESKTOP = 0x1
PRIMARY_DEVICE = 0x4
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
CDS_UPDATEREGISTRY = 0x01


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * CCHDEVICENAME),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128)]


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * CCHDEVICENAME),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("dmPositionX", ctypes.c_long),
                ("dmPositionY", ctypes.c_long),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short),
                ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short),
                ("dmFormName", wintypes.WCHAR * CCHFORMNAME),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD),
                ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD),
                ("dmMediaType", wintypes.DWORD),
                ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD),
                ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD),
                ("dmPanningHeight", wintypes.DWORD)]


_user32 = ctypes.windll.user32


def _settings(device: str, mode: int = ENUM_CURRENT_SETTINGS) -> DEVMODEW | None:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not _user32.EnumDisplaySettingsW(device, mode, ctypes.byref(dm)):
        return None
    return dm


def _adapters():
    i = 0
    while True:
        d = DISPLAY_DEVICEW()
        d.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not _user32.EnumDisplayDevicesW(None, i, ctypes.byref(d), 0):
            return
        yield d
        i += 1


def _monitor_name(device: str) -> str:
    m = DISPLAY_DEVICEW()
    m.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    if _user32.EnumDisplayDevicesW(device, 0, ctypes.byref(m), 0):
        return m.DeviceString
    return ""


def list_displays(solo_attivi: bool = True) -> list[dict]:
    """Un dizionario per display, con la chiave di registro che vuole Resolume."""
    out = []
    for d in _adapters():
        attivo = bool(d.StateFlags & ATTACHED_TO_DESKTOP)
        if solo_attivi and not attivo:
            continue
        dm = _settings(d.DeviceName)
        out.append({
            # Resolume numera i display da 1 nell'ordine di Windows
            "name": f"Display {len(out) + 1}",
            "device": d.DeviceName,
            "adapter": d.DeviceString,
            "monitor": _monitor_name(d.DeviceName),
            "device_key": d.DeviceKey,
            "width": dm.dmPelsWidth if dm else None,
            "height": dm.dmPelsHeight if dm else None,
            "x": dm.dmPositionX if dm else None,
            "y": dm.dmPositionY if dm else None,
            "refresh": dm.dmDisplayFrequency if dm else None,
            "primary": bool(d.StateFlags & PRIMARY_DEVICE),
            "active": attivo,
        })
    return out


def modes(device: str) -> list[tuple[int, int]]:
    """Le risoluzioni che il driver dichiara per quel display, senza duplicati."""
    viste, out, i = set(), [], 0
    while True:
        dm = _settings(device, i)
        if dm is None:
            return out
        coppia = (dm.dmPelsWidth, dm.dmPelsHeight)
        if coppia not in viste:
            viste.add(coppia)
            out.append(coppia)
        i += 1


def set_mode(device: str, width: int, height: int) -> int:
    """Cambia la risoluzione del display. 0 = fatto (DISP_CHANGE_SUCCESSFUL)."""
    dm = _settings(device)
    if dm is None:
        raise ValueError(f"display sconosciuto: {device}")
    dm.dmPelsWidth, dm.dmPelsHeight = width, height
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
    return _user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None,
                                            CDS_UPDATEREGISTRY, None)


def find(ref: str) -> dict:
    """Trova un display per nome Resolume, device Windows, modello o indice."""
    schermi = list_displays()
    ref = str(ref).strip()
    if ref.isdigit():
        i = int(ref)
        if 1 <= i <= len(schermi):
            return schermi[i - 1]
    basso = ref.lower()
    for s in schermi:
        if basso in (s["name"].lower(), s["device"].lower(), s["monitor"].lower()):
            return s
    for s in schermi:
        if basso and basso in s["monitor"].lower():
            return s
    raise ValueError(f"nessun display corrisponde a '{ref}'; "
                     f"disponibili: {[s['name'] + ' ' + s['monitor'] for s in schermi]}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "list":
        print(json.dumps(list_displays(), indent=2, ensure_ascii=False))
    elif cmd == "modes":
        print(json.dumps([f"{w}x{h}" for w, h in modes(find(argv[1])["device"])],
                         ensure_ascii=False))
    elif cmd == "set":
        s = find(argv[1])
        esito = set_mode(s["device"], int(argv[2]), int(argv[3]))
        print(f"{s['device']} -> {argv[2]}x{argv[3]}: "
              + ("ok" if esito == 0 else f"rifiutato (codice {esito})"))
    else:
        print(f"comando sconosciuto: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
