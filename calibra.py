# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python>=4.10", "numpy>=1.26"]
# ///
"""Calibrazione proiettore <-> webcam.

L'idea in una riga: si proietta una scacchiera, la webcam la fotografa, e da
dove finiscono i suoi angoli si ricava l'omografia che lega i pixel della
camera a quelli del proiettore. Da quel momento ogni punto che indichi sulla
FOTO del palco lo so tradurre in coordinate di proiezione, che e' esattamente
quello che serve per scrivere gli OutputRect delle slice.

  uv run --script calibra.py verifica              prova la matematica senza hardware
  uv run --script calibra.py pattern [file.png]    genera la scacchiera
  uv run --script calibra.py proietta [--schermo 1] la manda a schermo intero sul proiettore
  uv run --script calibra.py risolvi foto.jpg      trova gli angoli e salva l'omografia
  ... con --punti al posto della scacchiera: dischi bianchi su fondo nero, da usare
      quando si proietta su una superficie gia' dipinta (il rilevatore di scacchiere
      non aggancia se sotto c'e' un disegno contrastato)
  uv run --script calibra.py converti x,y x,y ...  da pixel-camera a pixel-proiettore

Why una scacchiera e non i quattro angoli dello schermo: gli angoli di un
rettangolo proiettato su un muro storto sono ambigui e spesso fuori inquadratura;
una griglia di 35 punti da' un fit sovradeterminato e un errore misurabile.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
CALIB = HERE / "calibrazione.json"
COLONNE, RIGHE = 7, 5          # angoli INTERNI della scacchiera
PCOL, PRIG = 4, 3              # dischi della griglia di punti


def crea_pattern(larghezza: int, altezza: int, colonne: int = COLONNE,
                 righe: int = RIGHE):
    """Scacchiera centrata, piu' i punti dei suoi angoli interni in pixel di
    proiettore. Il bordo bianco serve al rilevatore per staccare la griglia."""
    caselle_x, caselle_y = colonne + 1, righe + 1
    lato = int(min(larghezza / (caselle_x + 2), altezza / (caselle_y + 2)))
    ox = (larghezza - lato * caselle_x) // 2
    oy = (altezza - lato * caselle_y) // 2

    img = np.full((altezza, larghezza, 3), 255, np.uint8)
    for r in range(caselle_y):
        for c in range(caselle_x):
            if (r + c) % 2 == 0:
                y, x = oy + r * lato, ox + c * lato
                img[y:y + lato, x:x + lato] = 0

    # gli angoli interni, nello stesso ordine in cui li restituisce OpenCV:
    # riga per riga, da sinistra a destra
    punti = np.array([[ox + (c + 1) * lato, oy + (r + 1) * lato]
                      for r in range(righe) for c in range(colonne)], np.float32)
    return img, punti


def crea_punti(larghezza: int, altezza: int, colonne: int = PCOL, righe: int = PRIG):
    """Griglia di dischi bianchi su fondo NERO, piu' i loro centri in pixel di proiettore.

    Why non la scacchiera: su una superficie gia' dipinta e contrastata (un quadro,
    un fondale) findChessboardCorners non aggancia la griglia, perche' il disegno
    sotto rompe i bordi delle caselle. Il fondo nero invece spegne la superficie
    invece di illuminarla: i dischi restano l'unica cosa luminosa, e il soggetto
    resta riconoscibile nella stessa foto, cosi' un solo scatto basta.
    """
    img = np.zeros((altezza, larghezza, 3), np.uint8)
    mx, my = larghezza * 0.11, altezza * 0.11
    xs = np.linspace(mx, larghezza - mx, colonne)
    ys = np.linspace(my, altezza - my, righe)
    r = int(min((xs[1] - xs[0]) if colonne > 1 else 1e9,
                (ys[1] - ys[0]) if righe > 1 else 1e9) / 4.5)
    punti = []
    for y in ys:
        for x in xs:
            cv2.circle(img, (int(round(x)), int(round(y))), r, (255, 255, 255), -1)
            punti.append([x, y])
    return img, np.array(punti, np.float32)


def trova_punti(img, colonne: int = PCOL, righe: int = PRIG):
    """I centri dei dischi proiettati, nello stesso ordine di crea_punti.

    Si tengono i colonne*righe blob piu' luminosi di forma tonda, poi si
    ordinano per righe: la prospettiva di una proiezione frontale non e' mai
    tanto storta da mescolare l'ordine.
    """
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 9), 0)
    atteso = colonne * righe
    minarea = g.size * 2e-5
    for soglia in range(245, 90, -5):
        m = cv2.threshold(g, soglia, 255, cv2.THRESH_BINARY)[1]
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        buoni = []
        for c in cnts:
            a = cv2.contourArea(c)
            if a < minarea or a > g.size * 0.02:
                continue
            (_, _), rr = cv2.minEnclosingCircle(c)
            if a / (np.pi * rr * rr) < 0.55:      # quanto e' tondo
                continue
            buoni.append((a, c))
        if len(buoni) >= atteso:
            buoni = sorted(buoni, key=lambda t: -t[0])[:atteso]
            break
    else:
        return None
    # baricentro pesato sull'intensita': mezzo pixel in meno di errore
    centri = []
    for _, c in buoni:
        masc = np.zeros(g.shape, np.uint8)
        cv2.drawContours(masc, [c], -1, 255, -1)
        ys, xs = np.nonzero(masc)
        p = g[ys, xs].astype(np.float64)
        centri.append([float((xs * p).sum() / p.sum()), float((ys * p).sum() / p.sum())])
    centri = np.array(centri, np.float32)
    ordinati = []
    for riga in np.array_split(centri[np.argsort(centri[:, 1])], righe):
        ordinati.append(riga[np.argsort(riga[:, 0])])
    return np.vstack(ordinati)


def trova_angoli(img, colonne: int = COLONNE, righe: int = RIGHE):
    grigio = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    ok, ang = cv2.findChessboardCorners(
        grigio, (colonne, righe),
        cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not ok:
        return None
    # subpixel: senza questo l'errore di riproiezione resta sopra il pixel
    cv2.cornerSubPix(grigio, ang, (11, 11), (-1, -1),
                     (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
    return ang.reshape(-1, 2)


def omografia(cam: np.ndarray, proj: np.ndarray):
    """Da pixel-camera a pixel-proiettore. RANSAC perche' un angolo mal
    rilevato non deve trascinarsi dietro tutta la soluzione."""
    H, maschera = cv2.findHomography(cam, proj, cv2.RANSAC, 3.0)
    if H is None:
        raise SystemExit("omografia non calcolabile: angoli troppo pochi o degeneri")
    stimati = applica(H, cam)
    errori = np.linalg.norm(stimati - proj, axis=1)
    return H, {"punti": int(len(cam)), "usati": int(maschera.sum()),
               "errore_medio_px": round(float(errori.mean()), 3),
               "errore_massimo_px": round(float(errori.max()), 3)}


def applica(H, punti: np.ndarray) -> np.ndarray:
    p = np.hstack([np.asarray(punti, np.float64), np.ones((len(punti), 1))])
    q = (H @ p.T).T
    return q[:, :2] / q[:, 2:3]


def salva(H, misura: dict, dimensioni: dict) -> None:
    CALIB.write_text(json.dumps(
        {"H_camera_verso_proiettore": np.asarray(H).tolist(),
         "misura": misura, "dimensioni": dimensioni}, indent=2), encoding="utf-8")


def carica():
    if not CALIB.exists():
        raise SystemExit(f"manca {CALIB.name}: prima 'proietta' e poi 'risolvi foto.jpg'")
    d = json.loads(CALIB.read_text(encoding="utf-8"))
    return np.array(d["H_camera_verso_proiettore"], np.float64), d


def verifica() -> int:
    """Prova la catena senza proiettore ne' webcam: si deforma la scacchiera con
    un'omografia nota, la si fa ritrovare al rilevatore e si guarda se torna.

    Why: al festival non c'e' tempo di scoprire che la matematica era sbagliata.
    """
    W, H_ = 1920, 1080
    pattern, punti_proj = crea_pattern(W, H_)

    # una deformazione plausibile: proiettore storto rispetto al muro
    sorgente = np.float32([[0, 0], [W, 0], [W, H_], [0, H_]])
    destinazione = np.float32([[120, 60], [1180, 15], [1250, 690], [40, 715]])
    Hvera = cv2.getPerspectiveTransform(sorgente, destinazione)
    finta_foto = cv2.warpPerspective(pattern, Hvera, (1280, 720),
                                     borderValue=(255, 255, 255))

    angoli = trova_angoli(finta_foto)
    if angoli is None:
        print("FALLITO: la scacchiera non e' stata trovata nell'immagine deformata")
        return 1

    Hstimata, misura = omografia(angoli, punti_proj)
    print(json.dumps(misura, indent=2))

    # controllo indipendente: i quattro angoli dell'immagine di proiezione
    # devono tornare dove li avevo messi io
    ritorno = applica(np.linalg.inv(Hstimata), sorgente)
    scarto = float(np.abs(ritorno - destinazione).max())
    print(f"scarto sui 4 angoli noti: {scarto:.2f} px")

    ok = misura["errore_medio_px"] < 1.0 and scarto < 3.0
    print("OK" if ok else "DA GUARDARE")
    return 0 if ok else 1


def schermi():
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
    monitor = []

    def cb(h, hdc, lprc, lparam):
        r = lprc.contents
        monitor.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                               ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double)
    ctypes.windll.user32.EnumDisplayMonitors(0, 0, proto(cb), 0)
    return monitor


def raster(schermo: int = 1) -> tuple[int, int]:
    """Le dimensioni VERE del display, in pixel di segnale.

    Why non EnumDisplayMonitors: importare cv2 fissa la consapevolezza DPI del
    processo, quindi la SetProcessDPIAware di schermi() arriva tardi e i
    rettangoli dei monitor tornano in unita' logiche. Su un secondo schermo con
    scala diversa dal primario sballano: il 2026-08-25 un proiettore 1024x768
    veniva riportato come 1536x1152, e con quei numeri l'omografia esce scalata
    di 1.5. EnumDisplaySettings (displays.py) da' sempre pixel fisici.
    """
    import displays
    veri = displays.list_displays()
    if schermo >= len(veri):
        raise SystemExit(f"schermo {schermo} inesistente: ne vedo {len(veri)}. "
                         f"Collega il proiettore ed estendi il desktop.")
    s = veri[schermo]
    return int(s["width"]), int(s["height"])


def proietta(schermo: int = 1, punti: bool = False) -> None:
    """Manda la scacchiera a schermo intero sul monitor scelto (1 = il secondo,
    cioe' di norma il proiettore). Un tasto qualsiasi chiude.

    Why non passare da Resolume: in 7.16 non si possono caricare file nelle clip
    via API, quindi la scacchiera non potrebbe entrare nel set senza lavoro a
    mano. Proiettarla direttamente e' piu' semplice ed e' anche piu' corretto:
    si calibra l'uscita fisica, non la composizione.
    """
    import ctypes.wintypes  # noqa: F401  (serve a schermi())
    mon = schermi()
    if schermo >= len(mon):
        raise SystemExit(f"schermo {schermo} inesistente: ne vedo {len(mon)}. "
                         f"Collega il proiettore ed estendi il desktop.")
    x, y = mon[schermo][:2]          # posizione: nello spazio logico del processo
    w, h = raster(schermo)           # dimensioni: pixel veri del segnale
    pattern, _ = (crea_punti if punti else crea_pattern)(w, h)
    nome = "calibrazione"
    cv2.namedWindow(nome, cv2.WINDOW_NORMAL)
    cv2.moveWindow(nome, x, y)
    cv2.setWindowProperty(nome, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    # senza questo l'uscita a schermo intero di Resolume resta sopra e sul
    # proiettore non si vede niente (verificato il 2026-08-25)
    try:
        cv2.setWindowProperty(nome, cv2.WND_PROP_TOPMOST, 1)
    except AttributeError:
        pass
    cv2.imshow(nome, pattern)
    cv2.waitKey(200)                 # un giro di message loop, se no il rect e' ancora quello vecchio
    print(f"scacchiera su schermo {schermo} ({w}x{h}) - finestra in "
          f"{cv2.getWindowImageRect(nome)} - scatta la foto, poi un tasto per chiudere",
          flush=True)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def risolvi(foto: Path, schermo: int = 1, punti: bool = False) -> int:
    import ctypes.wintypes  # noqa: F401
    img = cv2.imread(str(foto))
    if img is None:
        raise SystemExit(f"non riesco a leggere {foto}")
    w, h = raster(schermo)
    _, punti_proj = (crea_punti if punti else crea_pattern)(w, h)

    angoli = (trova_punti if punti else trova_angoli)(img)
    if angoli is None:
        print("pattern non trovato. Controlla che sia tutto dentro l'inquadratura, "
              "a fuoco, e che non ci siano altre luci accese piu' forti dei dischi."
              if punti else
              "scacchiera non trovata. Controlla che sia tutta dentro "
              "l'inquadratura, a fuoco, e senza riflessi che spezzano le caselle.")
        return 1
    H, misura = omografia(angoli, punti_proj)
    salva(H, misura, {"camera": [int(img.shape[1]), int(img.shape[0])],
                      "proiettore": [w, h]})
    print(json.dumps(misura, indent=2))
    print(f"omografia salvata in {CALIB.name}")
    return 0


def converti(coppie: list[str]) -> None:
    H, _ = carica()
    punti = np.array([[float(v) for v in c.split(",")] for c in coppie], np.float64)
    fuori = applica(H, punti)
    print(json.dumps([[round(x, 1), round(y, 1)] for x, y in fuori]))


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    resto = [a for a in argv[1:] if not a.startswith("--")]
    schermo = 1
    punti = "--punti" in argv
    for a in argv[1:]:
        if a.startswith("--schermo"):
            schermo = int(a.split("=")[-1]) if "=" in a else 1

    if cmd == "verifica":
        return verifica()
    if cmd == "pattern":
        dest = Path(resto[0]) if resto else HERE / "pattern.png"
        img, _ = crea_pattern(1920, 1080)
        cv2.imwrite(str(dest), img)
        print(f"{dest} — 1920x1080, {COLONNE}x{RIGHE} angoli interni")
        return 0
    if cmd == "proietta":
        proietta(schermo, punti)
        return 0
    if cmd == "risolvi":
        if not resto:
            raise SystemExit("serve la foto: risolvi palco.jpg")
        return risolvi(Path(resto[0]), schermo, punti)
    if cmd == "converti":
        converti(resto)
        return 0
    print(f"comando sconosciuto: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
