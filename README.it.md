# DisplayMonitor

Un **monitor di sistema leggero e indipendente per il display USB TURZX / Turing 3,5" IPS** (320×480, USB‑C, «TURZX 3.5 IPS USB Secondary Display»),
per **Windows 10/11**. Sostituisce `UsbMonitor.exe` del produttore con un piccolo programma Python che:

* mostra una **pagina di riepilogo** (CPU, GPU, RAM, dischi, scheda madre, rete) e **altre 7 pagine** da scegliere dall'icona nella tray,
* legge i sensori di CPU / GPU / scheda madre / dischi con [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor),
* parla direttamente con la porta seriale USB del display: **nessun software del produttore, nessun driver da installare su Windows 10/11**,
* invia solo i pixel cambiati (il display accetta ~165 KB/s: un frame intero richiede ~1,8 s),
* **parte da solo all'accesso**, si riconnette dopo sospensione o scollegamento del cavo, e **recupera lo schermo nero** in cui il firmware cade dopo una chiusura brusca.

> Progetto non affiliato a TURZX, Turing, ASUS, Intel o LibreHardwareMonitor. Uso a proprio rischio.
> Provato su **un solo** esemplare: USB `1A86:5722`, seriale `USB35INCHIPSV2` (firmware V2, protocollo «Rev A»), Windows 11, Python 3.12.

![Tutte le pagine](docs/img/all_pages.png)

*(gli screenshot usano dati inventati: `python -m displaymonitor --demo`)*

## Pagine

Panoramica (sempre visibile) · CPU · GPU · Scheda madre · Dischi · Memoria · Rete · Sistema. Tutte hanno lo stesso schema:
un anello a sinistra e fino a tre schede a destra. Un solo linguaggio di colori per **tutte** le temperature (°C) e percentuali (%):
**bianco sotto 50, verde fino a 60, poi giallo → arancione → rosso fino a 100** (soglie modificabili).
Le pagine sono semplici file YAML (`config/pages.yaml`). Se la CPU/GPU/RAM/dischi si scaldano troppo la pagina relativa compare da sola.

## Installazione

Serve Windows 10/11, **diritti di amministratore** (per i sensori di CPU e scheda madre), Python 3.12 e, per temperatura/clock/potenza della CPU e per la scheda madre, il driver **PawnIO**.

```powershell
git clone https://github.com/DanaVivaldi/turzx-displaymonitor.git
cd turzx-displaymonitor
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1      # venv + dipendenze + LibreHardwareMonitor (con verifica hash) + PawnIO (chiede)
.\.venv\Scripts\python.exe -m displaymonitor                    # prova a mano (PowerShell da amministratore)
.\scripts\install_autostart.ps1                                 # avvio automatico all'accesso (task pianificato)
```

Se lo schermo è montato al contrario: `display.rotate: 3` in `config/config.yaml`.

## Uso

* **Icona nella tray**: *Mostra pagina* (resta finché non torni al riepilogo), *Torna al riepilogo*, *Rotazione automatica*, *Luminosità*, *Esci*.
* **Riga di comando** (parla con l'istanza in esecuzione): `python -m displaymonitor --send quit` (chiusura pulita: usala sempre al posto di terminare il processo),
  `--send page:gpu`, `home`, `next`, `prev`, `rotate`, `brightness:150`.
* `--preview` (anteprima PNG con i sensori reali), `--dump-sensors`, `--demo` (dati inventati), `--debug`.
* Log: `logs/displaymonitor.log`.

## Risoluzione problemi

| Sintomo | Soluzione |
|---|---|
| Temperature CPU / scheda madre `--` | avvia da amministratore e installa PawnIO (`winget install namazso.PawnIO`) |
| Schermo **nero** dopo che il programma è stato terminato | riavvia il programma: riconosce la chiusura anomala (`logs/running.flag`) e svuota il bitmap rimasto a metà (~13 s). Anche staccare il cavo funziona |
| Immagine capovolta | `display.rotate: 3` |
| «display not found» nel log | in Gestione dispositivi cerca `Dispositivo seriale USB (COMx)` con VID 1A86 PID 5722; chiudi `UsbMonitor.exe` (un solo programma può usare la porta) |
| Adattatore di rete sbagliato | imposta `network.interface` |

Documentazione tecnica (in inglese): [docs/CONFIGURATION.md](docs/CONFIGURATION.md), [docs/PROTOCOL.md](docs/PROTOCOL.md), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
Licenza MIT (vedi [LICENSE](LICENSE)); crediti in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

English: [README.md](README.md)
