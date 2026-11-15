# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""L'Advanced Output descrive il palco fisico, e basta.

Una slice per superficie reale, che prende TUTTA la composizione a piena
risoluzione. Le forme (cerchi, cerchione, quello che sara') non stanno piu'
qui: stanno nella composizione, dove si muovono in tempo reale via API.

Why: nella 7.16 l'Advanced Output si cambia solo riscrivendo un preset e
ricaricandolo a mano dal menu - non esiste rotta REST, ne' scorciatoia
tastiera/MIDI/OSC (verificato: zero occorrenze in tutti i file di Shortcuts).
Quindi tutto cio' che deve cambiare durante lo show non puo' vivere qui.

  uv run --script output_superfici.py            una superficie: schermo intero
  uv run --script output_superfici.py --preset X scrive in un preset diverso
"""
import argparse
import json

import resolume_mapping as m


def costruisci(setup: dict) -> dict:
    sc = setup["screens"][0]
    W, H = sc["width"], sc["height"]
    CW, CH = setup["composition"]["width"], setup["composition"]["height"]
    return {
        "composition": setup["composition"],
        "screens": [{
            **{k: sc[k] for k in ("name", "device", "width", "height")},
            "slices": [{
                "name": "Palco",
                "source": "0:1",                      # la composizione intera
                "input": [[0, 0], [CW, 0], [CW, CH], [0, CH]],
                "output": [[0, 0], [W, 0], [W, H], [0, H]],
            }],
        }],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default=None)
    args = ap.parse_args()

    setup = m.read_setup()
    setup.pop("file", None)
    sc = setup["screens"][0]
    data = costruisci(setup)
    preset = args.preset or m.active_preset() or "chat"
    dest = m.write_preset(data, preset)
    m.refresh_editor(json.loads(json.dumps(data)))
    print(f"una superficie {sc['width']}x{sc['height']} <- composizione "
          f"{setup['composition']['width']}x{setup['composition']['height']}")
    print(f"preset '{preset}' scritto: {dest}")


main()
