# Installazione

## Prerequisiti

| Funzione | Requisiti |
| --- | --- |
| Nucleo, liste locali, parser CNCPO, download web/PEC | Bash >= 3.2, Python >= 3.8.10 con SSL e libreria standard |
| Helper HTTP generico | curl con CA valide |
| IVASS PDF | pypdf 5.9.0, unico pacchetto Python opzionale |
| Allegati PEC cifrati | GnuPG, chiave privata e gpg-agent configurati |
| Distribuzione DNS | SSH, rsync, chiavi host già verificate, accesso non interattivo |
| Server BIND | Linux, Bash, rsync, named-checkconf, named-checkzone, rndc |
| Server Unbound | Linux, Bash, rsync, unbound-checkconf, unbound-control |
| Rotte locali | Linux, iproute2, privilegi CAP_NET_ADMIN/root |
| Test estesi | BIND/Unbound per i test nativi; ShellCheck per Bash |

Su Debian/Ubuntu, un amministratore può installare i prerequisiti necessari:

```bash
sudo apt-get update
sudo apt-get install bash python3 ca-certificates curl openssh-client rsync
# Soltanto se servono le relative funzioni:
sudo apt-get install python3-venv gnupg iproute2 bind9-utils unbound
```

Il bootstrap non esegue questi comandi come root e non modifica il sistema.
`--check` verifica il nucleo e, se presente, la configurazione locale.
`--init` crea solo i file locali mancanti. `--install-ivass` chiede conferma
prima di creare `.venv` e scaricare la dipendenza da PyPI; senza terminale
interattivo non installa nulla.

## Installazione locale

```bash
git clone https://github.com/robynhub/kit-censura-ng.git
cd kit-censura-ng
./bootstrap.sh --init
./bootstrap.sh --check
```

Modificare `config/kit.ini`: attivare categorie, indicare sorgenti e scegliere
le risposte DNS. Le liste manuali e le whitelist sono dati locali separati,
referenziati dall'INI. Non cambiare `*.example` o gli script distribuiti per
personalizzare il kit.

```bash
bin/kit-censura-ng update
bin/kit-censura-ng summary
bin/kit-censura-ng --dry-run apply
```

Per una configurazione esterna:

```bash
/path/kit-censura-ng/bin/kit-censura-ng -c /etc/kit-censura-ng/kit.ini doctor
```

Tutti i percorsi relativi sono relativi all'INI, anche se il comando parte da
cron o da un'altra directory. `{root}` identifica il codice installato, `{base}`
la directory dell'INI. `KIT_CONFIG` cambia il percorso predefinito; `KIT_PYTHON`
seleziona l'interprete. Se presente, `.venv/bin/python3` viene usato automaticamente.

## Credenziali PEC

Integrare le opzioni di `categories/pec.ini.example` nella configurazione
principale. Le password arrivano da variabili d'ambiente indicate in
`imap_password_env`; non metterle nella riga di comando. Predisporre ambiente,
CA e GnuPG per lo stesso utente che eseguirà il kit. L'importazione delle chiavi
si effettua una volta con GnuPG; le passphrase sono gestite da gpg-agent.

Il fetcher usa IMAPS verificato e una mailbox in sola lettura. Seleziona l'ultimo
UID con mittente e allegato corrispondenti, anche dentro una busta PEC MIME.
Non verifica la firma S/MIME del gestore: il controllo del mittente non equivale
a una verifica crittografica della provenienza. L'integrazione richiede una
mailbox attendibile e una prova con i messaggi reali del proprio gestore.
Non cancella, archivia o risponde ai messaggi automaticamente.

## Configurazione dei server DNS

Prima di abilitare upload, predisporre una directory dedicata scrivibile
dall'account SSH. L'account deve poter eseguire i validatori e il reload. I file
generati sono pubblicati con permessi 644, le directory con 755; configurare
l'accesso alle directory superiori in modo che il demone DNS possa leggerli.
Non usare lo stesso `remote_root` per due backend diversi sullo stesso server.

Dopo la prima generazione/distribuzione, includere nel BIND principale:

```text
include "/etc/bind/censura/current/named.conf";
```

Oppure nel file principale di Unbound:

```text
include: "/etc/unbound/censura/current/unbound.conf"
```

Per il primo avvio si può predisporre un rilascio vuoto e il symlink `current`
prima di aggiungere l'include. L'upload poi sostituisce il symlink; non modifica
il file principale DNS. Per BIND, `bind_zone_directory` deve coincidere con
`remote_root/current/zones`. Chroot, AppArmor e SELinux devono consentire
accesso a questi percorsi. Il controllo remoto verifica il file principale
indicato in `main_config`, non soltanto il frammento generato.

Solo dopo aver verificato gli output, abilitare `[upload:bind]` o
`[upload:unbound]` e lanciare `apply`. Nessun upload è abilitato nell'esempio.
