# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python>=4.10", "numpy>=1.26"]
# ///
"""La webcam come occhio sul palco.

  uv run --script webcam.py elenca              quali camere ci sono e che risoluzione
  uv run --script webcam.py scatta palco.jpg    una foto, da usare come sfondo dell'editor

Perche' non ffmpeg: su questa macchina non c'e', e uv installa opencv da solo
grazie all'header PEP 723. Perche' si scartano i primi fotogrammi: la webcam
apre sempre sottoesposta e mette qualche decimo a tarare esposizione e fuoco.
"""
import sys
import time
from pathlib import Path

import cv2


BACKEND = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "auto": cv2.CAP_ANY}


def apri(indice: int, backend: str = "dshow"):
    """DSHOW apre in fretta, MSMF a volte e' l'unico che espone davvero il
    sensore su questi portatili: si prova l'uno e si ripiega sull'altro."""
    for nome in ([backend] + [b for b in ("msmf", "dshow", "auto") if b != backend]):
        cap = cv2.VideoCapture(indice, BACKEND[nome])
        if cap.isOpened():
            return cap          # niente attributi appiccicati: cv2 non li accetta
        cap.release()
    return None


def elenca(massimo: int = 4) -> None:
    for i in range(massimo):
        cap = apri(i)
        if cap is None:
            print(f"{i}: niente")
            continue
        ok, frame = cap.read()
        if ok:
            h, w = frame.shape[:2]
            print(f"{i}: {w}x{h}  media luce {frame.mean():.0f}/255")
        else:
            print(f"{i}: si apre ma non da' fotogrammi")
        cap.release()


def scatta(dest: Path, indice: int = 0, scaldata: int = 20,
           larghezza: int = 1280, altezza: int = 720) -> Path:
    cap = apri(indice)
    if cap is None:
        raise SystemExit(f"la camera {indice} non si apre "
                         f"(occupata da un'altra app? prova 'elenca')")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, larghezza)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, altezza)
    frame = None
    for _ in range(scaldata):
        ok, f = cap.read()
        if ok:
            frame = f
        time.sleep(0.03)
    cap.release()
    if frame is None:
        raise SystemExit(f"la camera {indice} non ha dato nessun fotogramma")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    h, w = frame.shape[:2]
    print(f"{dest} — {w}x{h}, media luce {frame.mean():.0f}/255")
    if frame.mean() < 12:
        print("ATTENZIONE: quasi nera. Copriotturatore chiuso, o la camera "
              "e' quella a infrarossi, o serve piu' scaldata.")
    return dest


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("elenca", "scatta", "mirino"):
        print(__doc__)
        return 1
    if argv[0] == "elenca":
        elenca()
        return 0
    dest = Path(argv[1]) if len(argv) > 1 else Path("palco.jpg")
    indice = int(argv[2]) if len(argv) > 2 else 0
    if argv[0] == "mirino":
        mirino(dest, indice)
    else:
        scatta(dest, indice)
    return 0


def mirino(dest: Path, indice: int = 0) -> None:
    """Finestra dal vivo per puntare la camera sul palco.

    Why: da chat non posso vedere l'inquadratura mentre la sposti, e uno scatto
    per tentativo e' un giro lentissimo. Con la finestra aperta la punti tu e
    salvi quando ti piace.

    S salva, INVIO salva ed esce, ESC o Q esce senza salvare.
    """
    cap = apri(indice)
    if cap is None:
        raise SystemExit(f"la camera {indice} non si apre")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    nome = "mirino - S salva, INVIO salva ed esce, ESC esce"
    cv2.namedWindow(nome, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(nome, 960, 540)
    salvati = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        vista = frame.copy()
        cv2.putText(vista, f"luce {frame.mean():.0f}/255   salvati {salvati}",
                    (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
        cv2.putText(vista, f"luce {frame.mean():.0f}/255   salvati {salvati}",
                    (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
        cv2.imshow(nome, vista)
        t = cv2.waitKey(30) & 0xFF
        if t in (ord("s"), ord("S"), 13):
            cv2.imwrite(str(dest), frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
            salvati += 1
            print(f"salvato {dest} (luce {frame.mean():.0f}/255)", flush=True)
            if t == 13:
                break
        elif t in (27, ord("q"), ord("Q")):
            break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
