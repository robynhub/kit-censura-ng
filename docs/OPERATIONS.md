# Esercizio, upload e audit

## Pianificazione

Esempio cron (adattare percorso e utente):

```cron
17 * * * * /opt/kit-censura-ng/bin/kit-censura-ng -c /etc/kit-censura-ng/kit.ini run
*/5 * * * * /opt/kit-censura-ng/bin/kit-censura-ng -c /etc/kit-censura-ng/kit.ini --category pscaiip run
```

Il lock impedisce sovrapposizioni: un secondo processo esce con errore, non resta
in attesa. Pianificare gli intervalli in funzione della durata dei download.
Il primo avvio deve acquisire tutte le categorie abilitate. Il codice 2 va
monitorato: indica il ricorso a uno snapshot precedente, non piena freschezza.

## Upload e ripristino

SSH/rsync trasferiscono esclusivamente configurazioni DNS e zone. I file grezzi,
le password, le liste riservate e l'audit non vengono inviati. Ogni server riceve
un rilascio in `remote_root/releases/<id>`; l'attivazione remota:

1. Acquisisce un lock dedicato.
2. Valida ogni zona BIND oppure il frammento Unbound.
3. Sostituisce atomicamente `current`.
4. Valida la configurazione principale indicata nell'INI.
5. Esegue `rndc reconfig` oppure `unbound-control reload`.
6. In caso di errore ripristina il symlink precedente e tenta il suo reload.

I server sono indipendenti: un errore su uno non annulla i server già aggiornati.
Il log registra separatamente ciascun esito e l'esecuzione esce con 1.
Un successivo `apply` riprova tutti i server, anche con configurazioni uguali.
La ricarica usa Unbound completo, non lo script incrementale Perl originale.
Un guasto durante un reload può richiedere verifica manuale del demone; rollback
del file e rollback dello stato del servizio non sono la stessa cosa.

Per un rollback operativo scegliere una vecchia generazione, confrontarne il
manifest e ripristinarne il symlink `current` a processo fermo, poi validare e
ricaricare il demone. Non cancellare una generazione ancora referenziata.

## Rotte

La riconciliazione opera solo su `table`/`protocol`. Aggiunge i nuovi prefissi,
sostituisce quelli già posseduti e infine elimina gli obsoleti. Se trova una
rotta non posseduta con lo stesso prefisso, l'aggiunta fallisce invece di
sostituirla intenzionalmente. Non utilizzare lo stesso protocollo per altri servizi.
La tabella scelta deve essere effettivamente consultata dalle regole di routing.
Cambiare tabella/protocollo richiede rimuovere esplicitamente il vecchio insieme.

Le operazioni kernel sono sequenziali: in caso di errore possono restare modifiche
parziali. Non viene dichiarato successo; correggere il problema e ripetere `apply`.
Una next-hop deve essere raggiungibile e della famiglia corretta. Senza next-hop
si generano vere rotte `blackhole`. Prima della messa in produzione verificare
anche le policy di propagazione BGP/RTBH esterne al kit.

## Eventi e statistiche

Ogni riga dell'audit è un oggetto JSON con `time` UTC, `host`, `run_id`, `event`,
`level` e campi specifici. Scrittura con flush/fsync a ogni evento. Eventi principali:

- `source_validated`, `source_failed`, `source_unavailable`, `source_expired`;
- `list_statistics`: conteggi grezzi, filtrati, invalidi, duplicati e data/hash;
- `generation_published`: hash del manifest e totali unici;
- `upload_planned`, `routes_planned` in dry-run;
- `dns_applied`, `dns_apply_failed`, `routes_applied`, `routes_apply_failed`;
- `run_finished` con codice d'uscita, oppure `run_failed`.

`domains_raw` e `ips_raw` sono gli elementi validi unici consegnati dall'helper,
non il numero di righe HTML/PDF del provider. Gli helper originari possono già
deduplicare. `parsing.input`, `invalid`, `duplicates`, `ignored_urls` descrivono
il parsing del core. `ip_prefixes` e `cidrs` contano reti/indirizzi rappresentati,
non il numero di indirizzi espansi. I totali DNS contano domini, non righe di conf.

`dns_applied` attesta l'esito positivo dei comandi remoti, non misura la risposta
ricorsiva effettiva né la raggiungibilità da ogni cliente. Per un'evidenza operativa
aggiungere verifiche `dig` contro i resolver interessati e controlli `ip route`
con data, destinazione e generazione. Non inviare un riscontro di avvenuto blocco
basandosi unicamente su `source_validated` o `generation_published`.

SHA-256 e log locali aiutano a ricostruire gli eventi; **non sono una firma o una
marca temporale** e non impediscono alterazioni da parte di chi controlla il
server. Per conservazione verificabile inoltrare gli eventi a un sistema separato,
sincronizzare l'orologio e definire retention/accessi secondo le proprie esigenze.

## Debug, notifiche e manutenzione

`--debug` aggiunge eventi dei processi senza `bash -x`, password o argv completi.
Lo stderr degli helper non entra nel log formale. Per diagnosticare un helper,
eseguirne il comando configurato in un ambiente protetto, salvando separatamente
lo stderr; questo può contenere dati sensibili del provider.

L'esempio `categories/notification.ini.example` abilita il helper SMTP dopo
l'applicazione. Configurare destinatari, credenziali nell'ambiente, oggetto e corpo
nell'INI. Non viene eseguito in dry-run. Il successo SMTP indica accettazione dal
server, non lettura o consegna PEC certificata. L'hook viene ripetuto a ogni apply:
per evitare duplicati usare un hook idempotente basato sull'ID della generazione.

Configurazione e dati locali sono ignorati da Git. Aggiornare il codice con
`git pull --ff-only`, leggere il changelog, rieseguire bootstrap/doctor e i test.
Per congelare una lista già acquisita impostare `update=false`; per eliminarla
rimuovere o disabilitare la categoria e rigenerare.

Lo stato non viene ripulito automaticamente: contiene le evidenze di acquisizione,
anche dei tentativi falliti. Definire backup, quote e retention; eliminare vecchie
generazioni soltanto fuori dalle esecuzioni, escludendo quella corrente e quelle
utili al rollback. Per la rotazione log, rinominare il file tra esecuzioni oppure
usare una rotazione coerente con il file descriptor mantenuto aperto per la durata
del comando. Configurare `state_dir` e `log_file` su percorsi persistenti protetti.
