# Resolume MCP

Server MCP che pilota Resolume Arena/Avenue 7.8+ tramite la sua REST API.

## 1. Abilita il web server in Resolume

Resolume → **Preferences → Web Server** → attiva.
Porta di default **8080**, indirizzo `0.0.0.0`.
Verifica aprendo <http://127.0.0.1:8080> nel browser.

## 2. Installa Python + uv

Se non hai `uv` (consigliato: gestisce da solo le dipendenze), da PowerShell:

```powershell
winget install --id=astral-sh.uv -e
```

## 3. Registra il server MCP

Aggiungi questo blocco alla config MCP (Claude Desktop → Settings → Developer →
Edit Config, file `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "resolume": {
      "command": "uv",
      "args": ["run", "--script", "C:\\percorso\\resolume-mcp\\resolume_mcp.py"],
      "env": { "RESOLUME_URL": "http://127.0.0.1:8080" }
    }
  }
}
```

Senza `uv`, installa le dipendenze a mano e usa python:

```powershell
pip install "mcp>=1.2,<2" httpx
```

```json
{
  "mcpServers": {
    "resolume": {
      "command": "python",
      "args": ["C:\\percorso\\resolume-mcp\\resolume_mcp.py"],
      "env": { "RESOLUME_URL": "http://127.0.0.1:8080" }
    }
  }
}
```

Al posto di `C:\\percorso\\resolume-mcp` metti la cartella dove hai clonato la repo.

Riavvia Claude. Se Resolume gira su un'altra macchina, cambia `RESOLUME_URL`
con il suo IP (es. `http://192.168.1.50:8080`).

## Tool disponibili

**Lettura**
- `get_composition` — layer, clip, colonne, deck, BPM, opacità, effetti per layer
- `find_parameters(query)` — cerca qualsiasi parametro e restituisce il suo `path`
- `list_effects` — effetti video/audio installati

**Scrittura**
- `set_parameter(path, value)` — il tool universale: cambia qualsiasi parametro
- `set_layer_opacity(layer, opacity)` · `set_master_opacity(opacity)`
- `set_layer_state(layer, bypassed, solo)` · `set_bpm(bpm)`
- `set_effect_enabled(layer, effect, enabled)` — accende/spegne un effetto in catena

**Trigger**
- `trigger_clip(layer, column)` · `trigger_column(column)`
- `clear_layer(layer)` · `clear_all()` · `select_deck(deck)`

**Automazione** (dettagli più sotto)
- `scene_save(name)` · `scene_recall(name)` · `scene_list()`
- `job_start(mode, file)` · `job_stop()` · `job_status()` — mode: `record`, `play`, `auto`

**Uscita e mappatura** (Advanced Output, dettagli più sotto)
- `mapping_get()` · `mapping_presets()` · `mapping_apply(json, preset)` · `mapping_editor()`
- `output_displays()` — le uscite video di Windows con la chiave che usa Resolume
- `output_assign(display, screen, preset)` — manda uno screen sul proiettore

**Effetti sulle slice** (dettagli più sotto)
- `slice_outline(width)` — mette un contorno attorno a ogni slice della mappatura
- `slice_tracer(layer, beats, order)` — l'accensione cammina di slice in slice
- `slice_strobe(layer, beats, duty)` — strobo a tempo
- `slice_mix(layer, beats, tilt, seed)` — transizione caotica ma ripetibile
- `slice_fx_status()` — cosa sta girando

**Ponte OBS (Spout)**
- `spout_senders()` — chi sta trasmettendo via Spout in questo momento
- `obs_bridge(layer, sender, connect)` — verifica il ponte e connette la clip OBS sul layer

**Struttura della composizione** (aggiunti a novembre 2026, confrontando con
[drohi-r/resolume-mcp](https://github.com/drohi-r/resolume-mcp) e l'MCP ufficiale di Resolume 7.26)
- `get_product_info()` · `list_sources()` — versione di Resolume, sorgenti disponibili
- `add_layer()` · `add_column()` · `add_deck()` · `add_group()`
- `duplicate(kind, index)` — duplica layer, colonna o deck · `close_deck(deck, confirm)`
- `open_clip(layer, column, media)` — carica un file o una `source:///` in uno slot
- `clear_clip(layer, column, confirm)` · `select_clip` · `select_layer`
- `set_clip_speed(layer, column, speed)` · `set_clip_position(layer, column, position)`
- `add_effect(effect, layer, column, kind)` · `remove_effect(effect, …, confirm)` · `rename_effect`
- `disconnect_all(confirm)` · `composition_file(save|open|new, path, confirm)`
- `update_clip_thumbnail(layer, column)`
- `show_check()` — controllo pre-show: master a 0, layer in bypass, slot senza media

Gli strumenti distruttivi (`close_deck`, `clear_clip`, `remove_effect`, `disconnect_all`,
`composition_file open/new`) senza `confirm=True` restituiscono solo una richiesta di conferma.

**Escape hatch**
- `api_request(method, path, body)` — chiamata REST grezza
- `osc_send(address, values)` — messaggio OSC (Preferences → OSC → OSC Input, porta 7000;
  `RESOLUME_OSC_HOST` / `RESOLUME_OSC_PORT`)

Gli indici di layer, colonne, clip e deck partono da **1**, come nell'interfaccia.

## Come si controlla "qualsiasi cosa"

Il flusso è sempre lo stesso:

1. `find_parameters("Scale")` → `layers[0]:Layer #/video/effects[0]:Transform/params/Scale`
2. `set_parameter(quel_path, 150)`

Funziona per opacità, blend mode, transform, transport delle clip e ogni knob di
ogni effetto già presente nella catena.

## Nota tecnica: come avviene la scrittura

La REST API di Resolume espone pochissime rotte. In particolare **non esiste**
`PUT /parameter/by-id/{id}`, e nemmeno rotte per i singoli parametri: tutto si
scrive con un solo `PUT /api/v1/composition` passando un corpo **parziale** che
rispecchia l'albero JSON, con gli array riempiti di `{}` fino all'indice giusto.

```
set_parameter("layers[2]:Layer #/video/opacity", 0.5)
  → PUT /composition  {"layers": [{}, {}, {"video": {"opacity": {"value": 0.5}}}]}
```

`set_parameter` costruisce questo corpo da solo a partire dal path.

## Automazione: scene, registrazione, pilota automatico

Il file `resolume_auto.py` è un motore autonomo: gira come processo separato sul PC
e **continua a lavorare anche a Claude chiuso**. Lo avvii e lo fermi dalla chat con
i tool `job_start` / `job_stop` / `job_status`, oppure a mano da PowerShell.

### Scene
`scene_save("nome")` fotografa opacità, blend mode, bypass, ogni parametro di ogni
effetto e le clip attive. `scene_recall("nome")` rimette tutto com'era, in un colpo
solo: un unico PUT più i trigger delle clip. I layer che nella scena non avevano
clip attive vengono svuotati, così non resta acceso quello che gira adesso.
Le scene stanno in `scenes/`.

### Registrare le mosse
`job_start("record", "set.jsonl")` legge la composizione 4 volte al secondo e scrive
su file solo ciò che cambia, con il timestamp. Registra clip lanciate, fader mossi,
parametri di effetti, bypass — qualunque cosa tu faccia, che sia da mouse, MIDI o
tastiera. `job_stop()` chiude.

Il file è un JSONL leggibile:

```
{"t": 0.0,   "snapshot": { ...stato iniziale... }}
{"t": 12.4,  "set": {"layers[0]:Layer #/clips[2]:Cyberspace/connected": "Connected"}}
{"t": 18.9,  "set": {"layers[1]:Layer #/video/opacity": 0.4}}
```

### Riprodurre
`job_start("play", "set.jsonl")` rifà tutto con la stessa temporizzazione.
Per mandarlo in loop infinito, da PowerShell:
`python resolume_auto.py play set.jsonl --loop`

### Pilota automatico
`job_start("auto", "auto_set.json")` genera il set da solo, in sync con il BPM della
composizione (letto da Resolume all'avvio). Vedi `auto_set.json`, già tarato sul tuo
SET FACTORY:

- `layers` — ogni quante battute cambiare clip su quel layer, pescando a caso dalla
  lista senza mai ripetere quella appena uscita
- `effects` — accende e spegne un effetto della catena a intervalli di battute
- `modulate` — muove un parametro nel tempo: `sine` (oscilla), `ramp` (sale e
  riparte), `random`. `beats` è la durata di un ciclo completo

I `path` di `modulate` sono quelli che restituisce `find_parameters`.

**Le liste `clips` sono indici di colonna del deck selezionato**, e vanno tenute
corte quanto il deck: se punti a una colonna vuota il layer va in nero. Per questo
`auto_set.json` è tarato sul deck *SET* e `auto_generators.json` sul deck
*Generators* (5 / 4 / 3 clip).

Un job staccato non ha console: stdout e stderr finiscono in `job_<mode>.log` e
`job_<mode>.err` dentro la cartella dello script. Se `job_status` dice "fermo"
poco dopo l'avvio, l'errore è lì.

### Un solo job alla volta
`job_start` rifiuta di partire se ce n'è già uno attivo. Lo stato vive in `job.json`
(scritto ogni tick dal job) e lo stop è pulito, via `stop.flag`: niente processi
ammazzati a metà.

## Registrare il video in uscita

**Non si può via REST API**, in nessuna versione che risponda su questa build: non
esistono rotte `/recording`, `/recorder`, e la composizione non espone parametri di
registrazione. Il registratore di Resolume va fatto partire a mano dalla sua
interfaccia, oppure si cattura l'uscita con OBS (via NDI o Syphon/Spout).
Quello che invece si registra e si riproduce fedelmente è **il set come sequenza di
azioni**, con `record` e `play`.

## Mandare l'uscita sul proiettore

L'Advanced Output della 7.16 non è nella REST API: vive su disco, in
`Documents\Resolume Arena\Presets\Advanced Output\<preset>.xml`. Lo screen di un
preset disegnato in fase di studio è quasi sempre **virtuale** — comodo per
tracciare la mappatura, ma non esce da nessuna parte.

Per proiettare davvero servono tre cose:

1. **Windows in Estendi**, non in Duplica (`Win+P`). In Duplica c'è un solo
   monitor logico e Resolume non vede il proiettore come uscita separata.
2. **Il proiettore alla sua risoluzione nativa**, altrimenti c'è un riscalamento
   in più che ammorbidisce il mapping:
   `python displays.py list` per vederle, `python displays.py set "Display 2" 1024 768`
   per cambiarla.
3. **Lo screen puntato sul display fisico**: `output_assign("Display 2")`.

`output_assign` sostituisce l'`OutputDevice` dello screen e **riscala tutte le
slice** sulla nuova risoluzione mantenendo le proporzioni (se il rapporto cambia
centra e lascia i bordi neri), quindi la mappatura del palco resta valida. Tocca
`OutputRect`, la griglia del warper, l'omografia e i contorni delle maschere;
l'`InputRect` resta dov'è, perché è spazio composizione e non spazio schermo.

Dopo averlo lanciato **il preset va ricaricato da Resolume** (Output → Advanced →
menu dei preset), perché Resolume tiene lo screen setup in memoria e non rilegge
il file da sola.

### Nota su `idHash`

Ogni `OutputDevice` porta un `deviceId` (la chiave di registro dell'adapter, la
stessa che restituisce `EnumDisplayDevices`) e un `idHash` a 64 bit. Il
`deviceId` si ricava; l'`idHash` no — non è FNV-1/1a, murmur64, djb2, sdbm né il
`hashCode64` di JUCE. Quindi non lo si inventa: `known_id_hashes()` lo ripesca
dai file che ha scritto Resolume (le preferenze, i preset, il backup). Se quel
device non è mai passato di lì l'hash resta `0`; in quel caso assegna l'uscita a
mano una volta nell'Advanced Output e risalva il preset, così l'hash entra in
circolo e da lì in poi `output_assign` lo riusa.

## Effetti sulle slice: contorni, tracer, strobo, mix

Le slice non sono nella REST API, quindi **dal vivo non si toccano**. Ma quello
che una slice *mostra* sì: è un pezzo di composizione. Da lì il giro:

```
slice_outline  →  geometria, UNA VOLTA, nel preset
                  il contorno della slice i pesca dalla cella i di una striscia
                  larga quanto la composizione, alta 8px, in cima
tracer/strobe/mix → dal vivo, in battute, su un "layer di controllo" che passa
                  sopra quella striscia: i contorni lo seguono
```

Niente è legato a una mappatura in particolare: quante celle servono lo dice il
preset che trova. Cambia palco, cambiano le slice, i comandi restano gli stessi.

### Preparare (una volta per palco)

1. `slice_outline(width=6)` — scrive i contorni nel preset attivo.
2. **Ricarica il preset** da Resolume: Output → Advanced → menu preset.
3. In Resolume: un layer di controllo sopra gli altri, con una clip bianca
   (o un generatore Solid Color) e un **Transform** nella catena — il Transform
   va aggiunto a mano, la REST API non può farlo.
4. Rimpicciolisci il blob con lo Scale del Transform finché copre una cella sola.

`slice_outline(width=0)` toglie tutto (e serve sempre una ricarica del preset).

### Suonare

```
slice_strobe(layer=4, beats=0.25, duty=0.2)   flash secco sui sedicesimi
slice_tracer(layer=4, beats=1, order="pos")   una slice per quarto, da sx a dx
slice_mix(layer=4, beats=8, tilt=0.3, seed=7) salta a caso ogni 2 battute + inclina
slice_strobe(layer=4, beats=0)                spegne solo lo strobo
```

I tre si sommano: girano tutti dentro lo stesso job `auto`, che riparte da solo
a ogni comando. `job_stop()` li ferma tutti, `slice_fx_status()` dice cosa c'è.
`beats` è sempre in **battute del BPM di Resolume**, letto all'avvio del job.

**Caotico ma calcolato**: `slice_mix` è pseudo-casuale con un seme. Stesso `seed`
= stessa identica sequenza di salti, tutte le sere. Cambi seed, cambia il set.

### Taratura

`span` e `offset` sono le manopole: il `Position X` del Transform non copre
esattamente la larghezza della composizione su tutti i setup. Se il tracer
"manca" le slice — parte prima, o non arriva all'ultima — ritocca quelli, non il
codice. Anche `strip_y` di `slice_outline` è una manopola: la striscia di
controllo resta visibile dentro le slice normali (8px su 720, circa l'1%), quindi
mettila dove il tuo contenuto è scuro.

Lo strobo puntato su un layer qualsiasi funziona anche senza contorni: fa
lampeggiare quel layer e basta.

## Ponte con OBS via Spout

OBS manda il suo video a Resolume sulla GPU, senza compressione e senza passare dalla
rete. Serve il plugin **Spout2 for OBS** (gia' installato in
`C:\\ProgramData\\obs-studio\\plugins\\win-spout`); l'input Spout di Resolume e' sempre attivo.

Giro completo:

1. In OBS: `Tools -> Spout2 Output settings -> Enable Spout output`. Per mandare una
   singola sorgente invece di tutto il Program (e per avere l'alpha), usa il filtro
   `Spout2 Filter` sulla sorgente: ogni filtro e' un sender con un nome suo.
2. `spout_senders()` dice se OBS sta effettivamente trasmettendo.
3. In Resolume, pannello **Sources -> Spout**, trascina il sender in uno slot di clip
   del layer che gli dedichi. Questo passaggio e' manuale: la REST API non permette di
   caricare sorgenti negli slot.
4. `obs_bridge(layer=3)` trova quella clip e la connette. Senza argomenti cerca su tutti
   i layer e prende il primo sender disponibile.
5. Gli effetti mettili **sul layer**, non sulla clip: restano al loro posto anche se
   cambi sorgente, ed e' li' che li piloti con `set_parameter` e gli `slice_*`.

Risoluzione e fps di OBS vanno allineati alla composizione, e le due applicazioni devono
girare sulla stessa GPU. Se attivi anche l'uscita Spout di Resolume, non riprenderla in
OBS nella scena che stai gia' mandando qui: e' un loop infinito.

Dettagli e troubleshooting in `docs/ponte-obs-resolume.md`.

## Limiti noti (Arena 7.16)

- **Aggiungere o togliere effetti non è possibile via REST API.** Le rotte
  `/composition/.../effects/video/{i}` esistono ma rispondono 405 a GET, PUT e POST,
  e il `DELETE` va in timeout senza cancellare nulla — verificato sia sul Transform
  di serie sia su un effetto aggiunto a mano.
  **In pratica:** carica in Resolume gli effetti che ti servono, poi accendili e
  spegnili da qui con `set_effect_enabled`, e regola ogni loro parametro con
  `find_parameters` + `set_parameter`. Per un live è anche più comodo: nessuna
  ricostruzione della catena a runtime.
- Attenzione: un PUT con un effetto nuovo dentro l'array **non lo aggiunge**, si
  limita a rinominare quello già presente in quella posizione. Il merge non crea
  oggetti.
- Non esistono rotte per "disconnect all", "next/previous column" né per il
  tap tempo: `clear_all` è implementato svuotando i layer uno a uno.
- Resolume **7.26** ha aggiunto add/remove/reorder degli effetti alla REST API e
  include un MCP server ufficiale. `add_effect`, `remove_effect` e `rename_effect`
  usano queste rotte: su versioni precedenti rispondono con errore (405/404).
- `composition_file` (save/open/new) dipende dalla versione: su alcune build
  (es. 7.23) la rotta non esiste e va usato il menu File.

## Mappa dei file

**Server** (devono restare in radice, la config di Claude punta qui)
- `resolume_mcp.py` — il server MCP · `resolume_auto.py` — motore dei job (scene, record, play, auto) · `resolume_mapping.py` — Advanced Output, preset, editor `stage_mapper.html`
- `calibra.py`, `displays.py`, `webcam.py` — calibrazione con webcam e uscite video
- `check_mcp.py` — carica il server e stampa i tool (lo usa anche la CI)
- `scenes/`, `presets/`, `auto_set.json`, `auto_generators.json`, `slice_fx.json`, `preset_template.xml` — dati usati dal server

**Strumenti a riga di comando**
- `regia_video.py` + `riprese/` — regia dei video social con OBS
- `check_mapping.py`, `dump_mask.py`, `dump_tag.py`, `diagnosi_webcam.py` — verifiche e diagnostica

**Esperimenti** (prove su set specifici, non fanno parte del server)
- `cupo.py`, `cerchione.py`, `mappa_cerchi.py`, `output_superfici.py`, `stage_broken.py`, `prova_ritmo.py`, `prova_visibile.py`, `autoplay.py`

**Documenti** — `docs/ponte-obs-resolume.md` (ponte OBS) e `docs/materiale/` (anteprime)

## Licenza

MIT, vedi [LICENSE](LICENSE).
