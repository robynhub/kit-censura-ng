# Architettura

```text
config/kit.ini
   ↓ categorie ordinate + comandi helper
helpers/download/* → helpers/parse/* → validazione domini/IP
   ↓                                      ↓
ultima lista valida                 statistiche e hash
   ↓                                      ↓
whitelist → deduplicazione → aggregazione esatta
   ↓
generazione DNS + zone + manifest → symlink state/current
   ↓
helpers/deploy/* → validatori remoti → reload → eventi di applicazione
```

## Componenti

- `bin/kit-censura-ng`: avvio Bash indipendente dalla directory corrente.
- `bootstrap.sh`: controlli e inizializzazione; installazione PDF opzionale.
- `lib/kit/config.py`: INI e argv, senza interpretazione shell.
- `lib/kit/lists.py`: normalizzazione, validazione, whitelist e CIDR IPv4/IPv6.
- `lib/kit/pipeline.py`: lock, acquisizione, fallback e pubblicazione atomica.
- `lib/kit/dns.py`: renderer BIND/Unbound senza nomi di categoria.
- `lib/kit/audit.py`: log JSONL UTC con flush/fsync.
- `lib/kit/deploy.py`: applicazione e risultati per server.
- `helpers/download/`, `helpers/parse/`, `helpers/deploy/`: adattatori sostituibili.
- `categories/`: esempi di configurazione specifici e dati dell'adattatore IVASS.

Python evita parsing di INI/JSON/IP con `eval`, pipeline shell fragili e dipendenze
Perl. Bash rimane per i passaggi operativi dove rende il codice più leggibile.
Il nucleo usa la libreria standard di Python 3.8.10. `pypdf` serve soltanto a IVASS.

## Contratto di un helper

1. Un array JSON in configurazione indica eseguibile e argomenti.
2. Il download emette un elenco UTF-8 su stdout oppure scrive `{output}`.
3. Se il formato è diverso, un parser riceve `{input}` ed emette un record per riga.
4. Successo: codice 0. Errori, snapshot incompleti o formati inattesi: codice non zero.
5. L'helper non cambia `current`, non installa rotte e non invia riscontri di blocco.
6. Non inserire diagnostica in stdout: diventerebbe parte della lista. stderr non
   viene riversato nell'audit per evitare dati riservati e password di provider.

Il kit valida sintassi e soglie; non può riconoscere automaticamente uno snapshot
semanticamente incompleto ma formalmente valido. Configurare `min_entries` e
`max_drop_percent`, confrontare i conteggi e testare gli adattatori quando cambia
il sito dell'autorità. Gli helper web derivati dall'upstream mantengono le loro
regole specifiche, isolate dal core.

Un helper personalizzato può risiedere in una directory esterna al checkout e
comparire nell'INI. Non servono nuove dipendenze o modifiche al dispatcher per
aggiungere una categoria. `requires` e `python_modules` ne dichiarano i requisiti.

## Stati e consistenza

Ogni esecuzione usa un lock `flock` sullo stato. Crea una directory distinta in
`generations/`; `current` cambia con `os.replace` soltanto quando tutte le categorie
hanno dati utilizzabili e la generazione ha superato i controlli configurati.
La consistenza è atomica per lettori concorrenti; non è una transazione su più
host e non garantisce il recupero da qualsiasi guasto di disco/alimentazione.

Un aggiornamento fallito può riutilizzare il precedente snapshot **della stessa
categoria**, nei limiti d'età indicati. Se manca una prima acquisizione valida,
la generazione non viene pubblicata. I dati grezzi restano distinti dai dati
filtrati: `build` può applicare una nuova whitelist senza riscaricare le sorgenti.
Le generazioni fallite restano disponibili per diagnosi, senza essere correnti.

La priorità dei domini deriva dall'ordine delle sezioni. Gli IP totali raccolgono
tutte le categorie; le rotte applicabili raccolgono soltanto quelle con `routes=true`.
La nuova whitelist IP sottrae anche un prefisso interno a una rete bloccata.
L'aggregazione non amplia mai l'insieme degli indirizzi risultante.
