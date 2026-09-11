# Riferimento configurazione

INI UTF-8, senza interpolazione, `source`, `eval` o espansione shell. I commenti
occupano una riga propria; i valori non vanno racchiusi tra virgolette, salvo
le stringhe dentro gli array JSON. `[DEFAULT]` non è supportato. Le sezioni
sconosciute sono errori; le chiavi aggiuntive nelle sezioni sono consentite
per i parametri degli helper. Un nome categoria contiene lettere, numeri,
trattino e underscore e comincia con lettera o numero.

## `[kit]`

| Chiave | Default | Significato |
| --- | --- | --- |
| `state_dir` | `state` | Generazioni e lock |
| `log_file` | `state/audit.jsonl` | Log JSONL persistente |
| `whitelist_domains`, `whitelist_ips` | vuoto | Percorsi opzionali; se configurati devono esistere |
| `on_failure` | `keep` | `keep`: ultima lista valida, uscita 2; `abort`: nessuna pubblicazione |
| `helper_timeout` | `300` | Secondi massimi per processo helper |
| `max_source_bytes` | `104857600` | Dimensione massima accettata dopo acquisizione |
| `debug` | `false` | Eventi aggiuntivi per inizio/fine helper, senza argv |

La dimensione viene controllata dopo il download: usare anche quote filesystem
per imporre un limite allo spazio temporaneo. I timeout terminano il gruppo di
processi dell'helper. `state_dir` deve essere dedicata a una sola installazione
logica; tutte le invocazioni condividono il lock. Non usare un filesystem remoto
che non supporti correttamente flock e sostituzioni atomiche di symlink.

## `[category:NOME]`

| Chiave | Default | Significato |
| --- | --- | --- |
| `enabled` | `true` | Include la categoria |
| `update` | `true` | Scarica; `false` mantiene uno snapshot già acquisito |
| `download` | obbligatorio | Array JSON argv dell'helper |
| `before_download` | vuoto | Comando opzionale prima dell'acquisizione, es. aggiornamento client esterno |
| `parser` | vuoto | Array JSON argv di un parser di formato |
| `timeout` | `helper_timeout` | Timeout del download |
| `encoding` | `utf-8-sig` | Codifica dell'output del parser/helper |
| `min_entries` | `1` | Minimo domini + prefissi unici validi, prima dei filtri |
| `max_drop_percent` | `100` | Calo massimo accettato rispetto allo snapshot precedente |
| `max_age_seconds` | `0` | Età massima del dato in cache; 0 disabilita |
| `invalid_policy` | `fail` | `fail` rifiuta la lista; `skip` scarta e conta record invalidi |
| `url_policy` | `host` | `host` estrae host anche da URL con path; `reject` rifiuta path; `ignore` li conta e scarta |
| `remove_subdomains` | `false` | Elimina figli già coperti da un padre della stessa categoria |
| `routes` | `false` | Contribuisce a `routes.txt`; indipendente dall'elenco IP totale |
| `bind_a`, `bind_aaaa` | vuoto | Indirizzi apice della zona, separati da spazi |
| `bind_wildcard` | vuoto | Un IPv4, IPv6 o CNAME per `*`; dominio normalizzato come nome assoluto |
| `unbound_mode` | `legacy` | `legacy`, `redirect`, `static`, `always_nxdomain`, `refuse` |
| `unbound_redirect` | vuoto | Risposta A, AAAA o CNAME |
| `requires` | vuoto | Eseguibili richiesti dall'helper, separati da spazi |
| `python_modules` | vuoto | Moduli opzionali verificati da `doctor` |

L'ordine delle sezioni decide chi vince per un dominio identico in più liste.
L'eliminazione dei sottodomini si applica soltanto entro una categoria per non
perdere risposte specifiche di altre categorie. I conteggi per lista possono
quindi sommare a un valore maggiore del totale DNS unico.

`legacy` Unbound riproduce il kit: solo `local-data` quando esiste un redirect,
oppure `local-zone static` quando manca. Non implica redirect wildcard per tutti
i figli. `redirect` richiede una risposta IP e applica la zona redirect anche
ai figli; non accetta CNAME. BIND genera sempre una zona autoritativa: l'apice
non può contenere CNAME insieme a SOA/NS; configurare A/AAAA per l'apice.

Non bloccare un padre se una whitelist vuole consentire un figlio: BIND
intercetterebbe anche quel figlio. Il kit rileva e rifiuta il conflitto. Non
elimina silenziosamente il padre, perché sbloccherebbe altri nomi.

## Placeholder dei comandi

`{root}`, `{base}`, `{config}`, `{category}`, `{python}`, `{output}` nel download;
`{input}` in più nel parser; `{generation}` per validatori e hook. La sostituzione
avviene su singoli argomenti, senza reinterpretare spazi o metacaratteri.
Gli helper scrivono i dati su stdout oppure nel file `{output}`. Il parser scrive
le righe normalizzate su stdout. `before_download` deve terminare con codice 0.

Esempio di aggiornamento del client PSCAIIP senza modificare il kit:

```ini
before_download = ["docker", "compose", "--project-directory", "/opt/piracy-shield-agent-main", "exec", "-T", "app", "bash", "-c", "php application psc:run && php application psc:process-queue"]
requires = docker
timeout = 300
```

In questo esempio la shell è scelta esplicitamente dall'operatore per il comando
dentro il container. La configurazione è attendibile quanto gli eseguibili che
indica. Il kit non esegue né configura il NAT specifico della vecchia installazione.

## `[dns]`

`bind_zone_directory` è il percorso remoto assoluto dei file zona.
`ttl=300`, `serial=1`, `soa_ns=ns.localhost.`, `soa_mailbox=root.localhost.`,
`zone_ns=ns.localhost.`, `refresh=2419200`, `retry=2419200`, `expire=2419200`.
`bind_check` e `unbound_check` sono comandi opzionali di validazione locale.
`serial` va incrementato nella configurazione quando necessario per trasferimenti
verso secondari: il kit distribuisce direttamente ai server indicati, non gestisce
automaticamente i seriali delle zone secondarie.

## `[routes]`

`enabled=false`, `aggregate=true`, `min_prefix_v4=25`, `min_prefix_v6=0`,
`table=254`, `protocol=186`, `nexthop_v4` e `nexthop_v6` (vuoti per vere rotte
`blackhole`), `timeout=300`. I limiti di prefisso impediscono solo nuove fusioni
più ampie; una rete già ampia nella sorgente resta ampia. Non vengono aggiunti IP
per completare un aggregato. Una whitelist interna a una rete viene sottratta,
anche se genera più prefissi. Tabella e protocollo devono essere riservati al kit.

## `[upload:bind]` e `[upload:unbound]`

`enabled=false`, `servers` (destinazioni SSH separate da spazi), `remote_root`,
`main_config`, `ssh_port=22`, `connect_timeout=10`, `timeout=180`. I server sono
nomi/alias SSH oppure `utente@hostname`; usare un alias SSH per indirizzi IPv6,
ProxyJump e IdentityFile. L'upload usa sempre chiavi host verificate e BatchMode.

## `[hooks]`

`after_apply` è un array JSON argv eseguito dopo il successo di tutte le
applicazioni abilitate. Riceve anche `KIT_GENERATION` e `KIT_RUN_ID` nell'ambiente.
Un hook può inviare una notifica o archiviare evidenze; deve essere idempotente
perché un nuovo `apply` riesegue l'applicazione. Non viene eseguito in dry-run o
quando non sono configurate destinazioni. Un errore nell'hook rende l'esecuzione
fallita ma non annulla un'applicazione DNS già riuscita.
