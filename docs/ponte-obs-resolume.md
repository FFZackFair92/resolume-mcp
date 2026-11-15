# Ponte OBS → Resolume Arena via Spout

PC: desktop-b5l2o9h · OBS Studio 32.2.2 · Resolume Arena 7.16.0

---

## 0. Cosa ho già fatto io

OBS non aveva nessun plugin Spout. Ho installato il **Spout2 Plugin for OBS v1.12.0** (Off-World-Live), versione portable, senza toccare Program Files e senza installer:

```
C:\ProgramData\obs-studio\plugins\win-spout\
   bin\64bit\  win-spout.dll, Spout.dll, SpoutDX.dll, SpoutLibrary.dll
   data\locale\ en-US.ini, es-ES.ini, pt-BR.ini, zh-CN.ini
```

È il percorso plugin raccomandato da OBS: sopravvive agli aggiornamenti di OBS e si disinstalla cancellando quella cartella.

Lato Resolume non serve installare nulla: **l'input Spout è sempre attivo** in Arena.

---

## 1. OBS — accendere l'uscita Spout

1. **Chiudi e riapri OBS** (se era aperto): il plugin viene caricato solo all'avvio.
2. Menu **Tools → Spout2 Output settings** (se la voce non c'è, vedi Troubleshooting).
3. Spunta **Enable Spout output** e lascia il sender name di default (`OBS`), oppure dagli un nome parlante tipo `OBS-PROGRAM`.
4. Opzionale: **Automatically start Spout output** così parte da solo a ogni avvio di OBS.

Da questo momento OBS trasmette il suo **Program** su Spout, in tempo reale, senza compressione.

### Variante: mandare una sola sorgente invece di tutto il Program

Se ti serve solo la webcam, o solo un browser source, senza overlay e senza il resto della scena:

- click destro sulla sorgente in OBS → **Filters** → `+` → **Spout2 Filter**
- dai al filtro un sender name diverso (es. `OBS-CAM`)

Ogni filtro è un sender Spout indipendente: puoi averne più d'uno e in Resolume finiscono su layer diversi. Questa è anche l'unica via se ti serve **l'alpha** (trasparenza): il Program di OBS non ha canale alfa, il filtro sulla singola sorgente sì.

### Impostazioni OBS da allineare

In **Settings → Video**:

- **Output (Scaled) Resolution** = risoluzione della composizione Resolume (es. 1920×1080). Se non coincidono, Resolume riscala e perdi nitidezza.
- **FPS** = 60 se Resolume gira a 60. Un mismatch (30 vs 60) si vede come micro-scatti.

Spout passa la texture sulla GPU: OBS e Resolume devono girare **sulla stessa GPU**. Su un portatile con grafica ibrida forza entrambi sulla scheda dedicata (Impostazioni Windows → Schermo → Grafica).

---

## 2. Resolume — la sorgente su un layer

1. Apri **Resolume Arena** (con OBS già in trasmissione).
2. Pannello **Sources** (in basso a sinistra, accanto a Files / Effects / Compositions).
3. Cerca il gruppo **Spout**: trovi un'entrata col nome del sender (`OBS` o `OBS-CAM`).
4. **Trascinala in uno slot di clip** del layer che vuoi usare. Consiglio: tienici un layer dedicato e rinominalo `OBS` (doppio click sul nome del layer).
5. Fai click sulla clip per attivarla. Vedi il flusso di OBS nel preview.

Se la voce Spout non compare: OBS non sta trasmettendo (torna al punto 1.3) oppure Resolume era aperto **prima** che OBS iniziasse — in quel caso basta aspettare qualche secondo, la lista si aggiorna da sola.

---

## 3. Effettare a piacimento

Due posti dove mettere gli effetti, e la differenza conta:

- **sulla clip** — l'effetto vive con quella clip; se cambi sorgente lo perdi;
- **sul layer** (tab Effects mentre il layer è selezionato) — l'effetto resta lì qualunque cosa passi sul layer. **Per un ponte live è questo il posto giusto**: la catena di effetti diventa il tuo "canale OBS" stabile.

Catena di partenza che funziona bene su una sorgente live:

| Effetto | A cosa serve |
|---|---|
| **Transform** | scala/posiziona il feed dentro il frame |
| **Crop** | taglia bordi o barre nere |
| **Levels / Hue Rotate** | correzione colore veloce |
| **Luma Key** o **Chroma Key** | toglie sfondo (green screen in OBS) |
| **Feedback / Trails** | scia, ottimo con BPM sync |
| **Strobe / Glitch** | accenti a tempo |

Ogni parametro è automatizzabile: click destro sulla manopola → **Shortcuts** per MIDI/tastiera, oppure aggancialo al BPM col menu dei modulatori.

Una volta che il layer è in piedi, posso pilotartelo io da qui: opacità, blend mode, parametri degli effetti, trigger di clip e colonne, BPM. Dimmi cosa vuoi muovere.

---

## 4. Verifica del ponte

1. In OBS metti una sorgente riconoscibile (es. un testo con l'ora).
2. In Resolume attiva la clip Spout: devi vedere lo stesso contenuto con ritardo impercettibile (1–2 frame).
3. Cambia scena in OBS: Resolume segue subito.
4. Alza/abbassa l'opacità del layer in Resolume: OBS non deve essere influenzato (il flusso è a senso unico).

---

## 5. Trappole e troubleshooting

**"Spout2 Output settings" non appare nel menu Tools**
→ OBS non ha caricato il plugin. Controlla in **Help → Log Files → View Current Log** e cerca `win-spout`. Se il log dice che il modulo non si carica, prova a copiare le stesse DLL anche in `C:\Program Files\obs-studio\obs-plugins\64bit\` e i locale in `C:\Program Files\obs-studio\data\obs-plugins\win-spout\` (serve conferma UAC).

**Immagine nera in Resolume**
→ GPU diverse tra le due app, oppure OBS è in "Studio Mode" senza nulla in Program. Verifica anche che la scena OBS non sia vuota.

**Feedback loop**
→ Se in futuro attivi anche l'**output** Spout di Resolume (Output → Spout) e lo riprendi in OBS nella scena che stai già mandando a Resolume, ottieni un loop infinito. Se ti serve il ritorno, usa una **scena OBS separata** che non contenga il sender di Resolume.

**Consumo GPU**
→ Spout è leggero ma due app video sulla stessa scheda sono due app video. Se cali di fps, abbassa l'FPS di OBS a 30 o riduci la risoluzione del sender.

**Multipli sender**
→ Puoi avere Program + più filtri Spout contemporaneamente. Ognuno è una riga separata nel pannello Sources di Resolume e può stare su un layer diverso.

---

## Fonti

- [Spout2 Plugin for OBS — release 1.12.0](https://github.com/Off-World-Live/obs-spout2-plugin/releases/tag/1.12.0)
- [Off-World-Live — obs-spout2-plugin README](https://github.com/Off-World-Live/obs-spout2-plugin/blob/master/README.md)
- [Resolume — Syphon e Spout](https://resolume.com/support/en/syphonspout)
