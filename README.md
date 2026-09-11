# kit-censura-ng

**Versione 2.0.0** — evoluzione modulare di [rfc1036/kit-censura](https://github.com/rfc1036/kit-censura).
Scarica, valida e combina liste di domini, IPv4 e IPv6; genera `named.conf`,
`unbound.conf`, zone BIND e liste di rotte. Le categorie e le personalizzazioni
si definiscono nella configurazione, senza modificare gli script distribuiti.

Il progetto mantiene la pipeline e le destinazioni DNS del kit originale,
correggendo i comportamenti descritti nella [guida di migrazione](docs/MIGRATION.md).
Non è una replica dei suoi errori: gli aggiornamenti incompleti non sostituiscono
una lista valida e i log distinguono generazione e applicazione.

## Avvio rapido

Requisiti: Bash >= 3.2 e Python >= **3.8.10**. Il nucleo usa solo la libreria standard.
Linux è richiesto per l'applicazione delle rotte e l'attivazione DNS remota.

```bash
git clone https://github.com/robynhub/kit-censura-ng.git
cd kit-censura-ng
./bootstrap.sh --init
# Personalizzare config/kit.ini e le liste locali indicate nella configurazione.
bin/kit-censura-ng doctor
bin/kit-censura-ng update
bin/kit-censura-ng summary
bin/kit-censura-ng --dry-run apply
```

L'esempio abilita soltanto una lista locale inizialmente vuota. Download pubblici,
PEC, upload e rotte si abilitano esplicitamente nel file di configurazione.
`bootstrap.sh --init` non sovrascrive i file locali. Per IVASS soltanto:
`./bootstrap.sh --install-ivass` crea un ambiente virtuale e installa `pypdf`,
**dopo una conferma interattiva**.

## Configurazione e categorie

```ini
[category:nuova-lista]
enabled = true
download = ["{root}/helpers/download/local.sh", "/srv/liste/nuova.txt"]
min_entries = 1
routes = false
bind_a = 0.0.0.0
bind_wildcard = 0.0.0.0
unbound_redirect = 0.0.0.0
```

Aggiungere o eliminare una sezione aggiunge o elimina una categoria. Il core non
conosce i nomi delle autorità. Gli helper sono in `helpers/download/` e
`helpers/parse/`; gli esempi specifici in `categories/`. Sono inclusi adattatori
per ADM giochi/tabacchi, AGCOM, CONSOB, IVASS, CNCPO, PEC e snapshot PSCAIIP.
Le sorgenti riservate richiedono gli accessi dell'operatore.

## Comandi

| Comando | Effetto |
| --- | --- |
| `doctor` | Verifica configurazione e prerequisiti dichiarati dagli helper |
| `update` | Scarica, valida e genera; non applica sui server |
| `build` | Rigenera dalle liste valide conservate, senza download |
| `apply` | Verifica gli hash e applica la generazione corrente |
| `run` | `update` seguito da `apply` |
| `summary` | Statistiche per lista e totali, anche nel log |
| `verify` | Verifica l'integrità della generazione corrente |

Opzioni: `-c /percorso/kit.ini`, `--debug`, `--dry-run`, `--category nome`
(ripetibile). `--dry-run` impedisce upload, rotte e hook; con `run` esegue comunque
download e generazione locali. `--category` limita i download, conservando le
altre categorie già presenti. Codici di uscita: **0** successo, **1** errore,
**2** generazione degradata con ultima lista valida riutilizzata.

## Output e tracciabilità

`state/current` punta atomicamente all'ultima generazione completa:

- `named.conf`, `unbound.conf`, `zones/db.<categoria>`;
- `lists/<categoria>` e `lists/<categoria>-ip`;
- `ip-fullist`, `cidr-fullist`, `routes.txt`;
- `manifest.json`: hash SHA-256, statistiche, stato e data di acquisizione;
- `domain-owners.json`: categoria vincente per ciascun dominio;
- `sources/` e `raw/`: materiale acquisito e snapshot normalizzati.

Il log JSONL contiene timestamp UTC, host, identificativo esecuzione, eventi,
errori e conteggi. `dns_applied` significa che il controllo remoto e il reload
hanno restituito successo; non certifica una risposta DNS vista da un utente.
Consultare [logging e verifiche operative](docs/OPERATIONS.md).

## Documentazione

- [Installazione e prerequisiti](docs/INSTALL.md)
- [Riferimento configurazione](docs/CONFIGURATION.md)
- [Architettura e contratto degli helper](docs/ARCHITECTURE.md)
- [Migrazione e differenze rispetto all'originale](docs/MIGRATION.md)
- [Upload, rotte, logging, rollback e manutenzione](docs/OPERATIONS.md)
- [Test e limiti di verifica](docs/TESTING.md)
- [Changelog](CHANGELOG.md) e [attribuzioni](NOTICE)

## Sviluppo e licenza

```bash
python3 -m unittest discover -s tests -v
```

La CI verifica anche Python 3.8.10, i validatori nativi BIND/Unbound su Linux,
rollback e ShellCheck. GNU GPL **2.0 o successiva**, come il progetto originale;
vedere [LICENSE](LICENSE) e [NOTICE](NOTICE).
