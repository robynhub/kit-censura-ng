# Migrazione dal kit originale

Riferimento analizzato: commit `dfc87432fff166dfd4a077b08848634989918e8b` di
[rfc1036/kit-censura](https://github.com/rfc1036/kit-censura).
La versione NG conserva finalità, categorie disponibili, acquisizione a helper,
generazione DNS e blackholing. Non esiste una garanzia di output byte-per-byte:
la tabella indica le differenze, comprese le correzioni di comportamento.

## Mappatura

| Prima | Ora |
| --- | --- |
| `LISTS` | Sezioni `[category:...]` abilitate, nel medesimo ordine |
| `UPDATE_LISTS` | `update=true/false` per categoria |
| `FILE_*`, helper specifici | `download`/`parser` e argomenti configurati |
| `db.*` modificati a mano | `bind_a`, `bind_aaaa`, `bind_wildcard` e `[dns]` |
| `case` in build-unbound-config | `unbound_redirect`, `unbound_mode` |
| `SERVERS`, `CONFDIR`, `CONFFILE` | `[upload:bind]`, `remote_root`, `main_config` e `[dns]` |
| `WHITELIST_*` | `whitelist_domains`, `whitelist_ips` |
| `ROUTES_LISTS` | `routes=true` per categoria, ora effettivamente rispettato |
| `AGGREGATE_PREFIX`, `AGGREGATION_MAXLEN` | `aggregate`, `min_prefix_v4` e `min_prefix_v6` |
| `BLACKHOLE_NEXTHOP` | `nexthop_v4`/`nexthop_v6` |
| `censorship-cron` | `kit-censura-ng run` |
| Cron PSCAIIP | `kit-censura-ng --category pscaiip run` dopo un primo update completo |
| `censorship-summary` | `kit-censura-ng summary` |
| Riscontri email | Hook dopo applicazione; esempio SMTP già incluso |

## Risposte DNS iniziali

| Categoria | BIND apice | BIND wildcard | Unbound legacy |
| --- | --- | --- | --- |
| manuale | 0.0.0.0 | 0.0.0.0 | A 0.0.0.0 |
| aams | 217.175.53.72 | CNAME sito-inibito-giochi.adm.gov.it. | CNAME stesso nome |
| tabacchi | 217.175.53.228 | CNAME sito-inibito-tabacchi.adm.gov.it. | CNAME stesso nome |
| agcom | 0.0.0.0 | 0.0.0.0 | local-zone static |
| consob | 0.0.0.0 | 0.0.0.0 | local-zone static |
| cncpo | 212.25.179.125 | 212.25.179.125 | A 212.25.179.125 |
| pscaiip | 0.0.0.0 | 0.0.0.0 | local-zone static |
| ivass | 85.159.194.59 | CNAME warning.ivass.it. | CNAME stesso nome |

Sono valori del progetto originale, **non una verifica attuale dei recapiti delle
autorità**. Rimangono tutti configurabili. Sono rimossi record A duplicati e
normalizzati i CNAME assoluti: nei vecchi file alcuni nomi mancavano del punto
finale e sarebbero stati interpretati come relativi alla zona.

## Correzioni intenzionali

- Errori di download, parsing, validazione e upload producono codici non zero;
  non vengono registrati come applicazioni riuscite.
- Il primo avvio non produce liste vuote per sorgenti obbligatorie mancanti.
- Duplicati DNS tra categorie hanno precedenza deterministica anche in Unbound.
- Whitelist IP interne a CIDR sono sottratte; prima venivano escluse solo reti
  interamente coperte dalla whitelist.
- Un'eccezione DNS figlia di un padre bloccato causa errore: il vecchio filtro
  poteva sembrare applicarla senza renderla efficace in BIND.
- Rotte limitate a tabella/protocollo del kit; non vengono cancellate tutte le
  rotte che mostrano `lo`. Le rotte non sono una transazione atomica.
- Il client Piracy Shield è esterno: `before_download` può aggiornarlo; gli
  indirizzi SNAT specifici di una vecchia installazione non vengono riapplicati.
- PEC: acquisizione in sola lettura, senza archiviazione/cancellazione globale
  della mailbox. Nessuna dichiarazione di blocco inviata durante il download.
  Un hook SMTP configurabile può notificare dopo il successo dell'applicazione.
  L'archiviazione dei messaggi resta una politica del gestore della mailbox.
- IVASS: TLS verificato, un'unica dipendenza PDF, snapshot TLD locale IANA;
  un errore di pagina/PDF rifiuta il download completo anziché pubblicare un
  sottoinsieme. Le euristiche di estrazione vanno confrontate con campioni reali.
- Nessun invio automatico di email di errore preconfigurato: cron/monitoraggio
  leggono codici di uscita e log; hook personalizzati gestiscono le notifiche.

## Procedura

1. Conservare config, liste valide e output dell'installazione precedente.
2. Installare NG separatamente e tradurre le impostazioni usando la tabella.
3. Per il primo confronto usare copie delle liste già normalizzate come sorgenti
   `local.sh`; impostare il parser solo per i file ancora in formato CSV originale.
4. Eseguire `update`, confrontare domini, IP, redirect e conteggi con il vecchio kit.
5. Provare gli helper pubblici e riservati nel proprio ambiente; impostare soglie.
6. Predisporre include DNS e directory di rilascio, poi `--dry-run apply`.
7. Abilitare l'applicazione e verificare risposte DNS/rotte prima di sostituire cron.

Per includere le vecchie liste `lista.<nome>-ip`, indicare entrambi i percorsi
in `local.sh`; non esiste più una convenzione nascosta sul suffisso del file.
Le liste riservate non devono entrare nel repository Git.
