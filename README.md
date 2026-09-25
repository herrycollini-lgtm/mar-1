# Bagno Marè — sito e prenotazioni

Sito in italiano, responsive, basato sulle foto e sulla palette fornite. Include la pagina pubblica, il modulo prenotazioni e un’area riservata per la gestione.

## Avvio in locale

Serve Python 3.9 o superiore. Nel terminale PowerShell, dalla cartella del progetto, imposta le credenziali e avvia il server:

```powershell
$env:MARE_ADMIN_USER = "gestore"
$env:MARE_ADMIN_PASSWORD = "inserisci-una-password-di-almeno-12-caratteri"
py -3 server.py
```

Apri `http://127.0.0.1:8000` per il sito e `http://127.0.0.1:8000/admin.html` per l’area gestione. Le credenziali sono configurate con variabili d’ambiente e non sono salvate nei file del sito.

## Prenotazioni e disponibilità

- Le prenotazioni vengono salvate nel database SQLite `data/mare.sqlite3`.
- L’admin può configurare gli orari generali di pranzo e cena, la capienza per ciascun orario e il limite totale per una data.
- Per una singola data può impostare capienze diverse per ogni orario; lasciando il campo vuoto si usa la capienza standard.
- Le prenotazioni includono data, servizio, orario, persone e note, come richiesto. Gli eventuali parametri UTM vengono conservati e mostrati nell’area gestione.
- Le fasce orarie non sono precompilate: vanno inserite dalla gestione quando sono disponibili gli orari ufficiali del Bagno Marè.

## Menu online

La pagina pubblica presenta colazione, pranzo e cena, aperitivo e carta dei vini. I PDF originali sono conservati in `assets/menus/`; la carta dei vini di 31 pagine si apre in un riquadro espandibile e resta scaricabile. Il PDF allergeni è disponibile tramite download e non viene riportato per esteso nel sito.

## Uso dell'area gestione

1. Apri `/admin.html` e accedi con le credenziali configurate sul server.
2. Seleziona la data da controllare. Il riepilogo mostra prenotazioni non annullate, coperti e capienze.
3. Usa il filtro per consultare richieste ricevute, confermate o annullate. L'esportazione CSV segue il filtro selezionato; la stampa produce il prospetto della data.
4. Per modificare una richiesta, cambia il suo stato. L'annullamento richiede una conferma e libera i coperti.
5. Nella capienza per data, un totale giornaliero vuoto significa nessun limite; lascia vuota una capienza per orario per usare il valore standard. Per cambiare una fascia in modo generale, usa la sezione Fasce di servizio.

Le prenotazioni inviate dal sito partono nello stato `ricevuta`: il gestore deve controllarle e aggiornarne lo stato. Il modulo attuale non raccoglie recapiti e non invia email o SMS, quindi il gestore non può ricontattare automaticamente chi ha inviato la richiesta. Questa regola operativa va concordata con l'attività prima di pubblicare.

## Backup

Il database è `data/mare.sqlite3`. Crea un backup coerente anche mentre il server è in esecuzione con:

```powershell
py -3 backup_db.py
```

Per impostare una cartella privata diversa, configura `MARE_BACKUP_DIR` prima di avviare il comando. Il percorso predefinito è `backups/`, escluso dal controllo versione. Conserva le copie con accesso ristretto e definisci una regola di conservazione; su hosting va predisposto anche un backup automatico.

Per ripristinare, arresta il server, conserva una copia del database corrente, sostituisci il file nel percorso `MARE_DB_PATH` con la copia scelta e riavvia il servizio. Verifica poi nell'area gestione che prenotazioni e disponibilità siano presenti.

## Prima della pubblicazione

Questa è una base funzionante per la revisione locale, non ancora una pubblicazione pronta per Internet. Prima della consegna all'attività occorre concordare come il cliente riceverà la conferma: il modulo attuale non raccoglie recapiti e non invia notifiche. Vanno inoltre aggiunti i dati ufficiali ancora mancanti (contatti, indirizzo e orari), verificati con il gestore i menu 2026 e i diritti delle immagini, completata l'informativa privacy con il titolare e controllato il sito su dispositivi reali.

Per la pubblicazione vanno scelti dominio e hosting con Python e database persistente, attivato HTTPS, predisposti backup automatici e ripristino e configurata l'immagine Open Graph con un URL assoluto del dominio definitivo. Il server incluso è pensato per sviluppo locale; non va esposto direttamente a Internet.

La cartella `data` contiene prenotazioni e va esclusa dal controllo versione e dai backup pubblici. Le credenziali admin vanno impostate nell’ambiente del server e non condivise nel codice.
