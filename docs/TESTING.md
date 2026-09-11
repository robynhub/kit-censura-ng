# Test

```bash
python3 -m unittest discover -s tests -v
```

I test usano dati sintetici e directory temporanee; non modificano resolver,
mailbox, client Piracy Shield o rotte reali. Coprono normalizzazione domini/IP,
IDNA, URL, whitelist, sottrazione CIDR, proprietà di aggregazione esatta,
precedenza CNCPO, MIME PEC annidato, categorie arbitrarie, deduplicazione,
statistiche, hash, fallback, liste vuote, cache scaduta, lock e dry-run.

L'integrazione upload simula gli eseguibili SSH/rsync per verificare che un errore
non diventi un evento di applicazione riuscita. Il rollback del symlink remoto
è provato su Linux con un reload simulato fallito. Se disponibili, i test nativi
passano gli output di tutte le categorie a named-checkconf, named-checkzone e
unbound-checkconf; in assenza dei binari sono indicati come skipped.

La CI esegue la suite nell'immagine `python:3.8.10-slim` e su Ubuntu con validatori
DNS e ShellCheck. Nessun test dipende dalla disponibilità corrente dei siti delle
autorità. Il test della grammatica e gli output sintetici non sostituiscono una
prova con elenchi riservati, PEC del proprio gestore, routing e resolver effettivi.

Prima di attivare una categoria, confrontare un campione di input/output, controllare
le soglie e verificare che la sorgente rappresenti una lista completa. Ripetere
questa verifica quando cambia il formato di un sito o di un allegato.
