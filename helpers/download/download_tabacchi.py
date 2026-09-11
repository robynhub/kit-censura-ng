#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import re
import os
import argparse
import html
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse, parse_qs
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

LISTING_URL = "https://www.adm.gov.it/portale/siti-inibiti-tabacchi"
UA = "Mozilla/5.0 (Python urllib; ADM elenco_siti_inibiti_tabacchi.txt fetcher)"

# ---------------------------
# HTTP helpers
# ---------------------------
def http_get(url, timeout=25, binary=False):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if binary:
            return data, resp.headers.get_content_type(), resp.headers
        charset = resp.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace"), resp.headers.get_content_type(), resp.headers

def is_same_domain(url, domain="adm.gov.it"):
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc.endswith(domain)
    except Exception:
        return False

def content_disposition_filename(headers):
    cd = headers.get("Content-Disposition") or headers.get("content-disposition")
    if not cd:
        return None
    m = re.search(r'filename\*\s*=\s*(?:UTF-8\'\')?([^;]+)', cd, flags=re.I)
    if m:
        return unquote_pct(m.group(1)).strip('"\' ')
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(r'filename\s*=\s*([^;]+)', cd, flags=re.I)
    if m:
        return m.group(1).strip('"\' ')
    return None

def unquote_pct(s):
    try:
        from urllib.parse import unquote
        return unquote(s)
    except Exception:
        return s

# ---------------------------
# HTML parsing
# ---------------------------
class AnchorCollector(HTMLParser):
    """Raccoglie (href, text) in ordine di apparizione."""
    def __init__(self):
        super().__init__()
        self.links = []
        self._in_a = False
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._in_a = True
            self._href = None
            for k, v in attrs:
                if k.lower() == "href" and v:
                    self._href = v.strip()
                    break

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._in_a:
            text = html.unescape("".join(self._buf)).strip()
            if self._href:
                self.links.append((self._href, text))
            self._in_a = False
            self._href = None
            self._buf = []

    def handle_data(self, data):
        if self._in_a and data:
            self._buf.append(data)

def parse_anchors(base_url, html_text):
    p = AnchorCollector()
    p.feed(html_text)
    out = []
    seen = set()
    for href, text in p.links:
        if not href or href.startswith("#"):
            continue
        absu = urljoin(base_url, href)
        key = (absu, text.strip())
        if key not in seen:
            out.append((absu, text.strip()))
            seen.add(key)
    return out

# ---------------------------
# Heuristics
# ---------------------------
FILE_EXTS = (".txt", ".pdf", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".csv", ".zip", ".7z")

def looks_like_file_url(u: str) -> bool:
    path = urlparse(u).path.lower()
    return any(path.endswith(ext) for ext in FILE_EXTS)

def is_txt_url(u: str) -> bool:
    path = urlparse(u).path.lower()
    if path.endswith(".txt"):
        return True
    q = parse_qs(urlparse(u).query)
    for vals in q.values():
        for v in vals:
            if ".txt" in v.lower():
                return True
    return False

def is_txt_response(url, ctype, headers, data):
    """Validate TXT downloads exposed through opaque ADM document URLs."""
    if is_txt_url(url):
        return True
    filename = content_disposition_filename(headers)
    if filename and filename.lower().endswith('.txt'):
        return True
    ctype = (ctype or '').lower()
    if ctype == 'text/plain':
        return True
    prefix = data[:512].lstrip().lower()
    if prefix.startswith(b'%pdf-') or prefix.startswith(b'pk\x03\x04') or prefix.startswith(b'\xd0\xcf\x11\xe0'):
        return False
    if prefix.startswith(b'<!doctype html') or prefix.startswith(b'<html'):
        return False
    return ctype in ('application/octet-stream', 'application/download', 'binary/octet-stream', '')

# ---------------------------
# Individua direttamente elenco_siti_inibiti_tabacchi.txt
# ---------------------------
TARGET_SUBSTR = "elenco_siti_inibiti_tabacchi.txt"

def find_txt_url_on_page(listing_url, timeout=25, verbose=False):
    """Find the tabacchi TXT, accepting opaque ADM document links."""
    html_text, ctype, _ = http_get(listing_url, timeout=timeout, binary=False)
    if verbose:
        print(f"[INFO] Apertura pagina: {listing_url} (Content-Type: {ctype})", file=sys.stderr)

    anchors = parse_anchors(listing_url, html_text)

    def score_link(absu, text):
        u = absu.lower()
        t = (text or '').strip().lower()
        score = 0
        if 'siti' in t and 'inibit' in t:
            score += 70
        if 'tabacchi' in t:
            score += 50
        if 'txt' in t:
            score += 40
        if TARGET_SUBSTR in u:
            score += 100
        if is_txt_url(u):
            score += 30
        if 'sha' in t or 'sha' in u or 'controllo' in t:
            score -= 200
        if is_same_domain(absu):
            score += 10
        return score

    ranked = sorted(((score_link(absu, txt), absu, txt) for absu, txt in anchors), reverse=True)
    for score, absu, txt in ranked:
        if score >= 60:
            if verbose:
                print(f"[INFO] Candidato TXT da anchor: {absu} | testo={txt!r} | score={score}", file=sys.stderr)
            return absu

    patterns = [
        r'(?P<u>https?://[^\s"\'<>]*elenco_siti_inibiti_tabacchi\.txt(?:\?[^\s"\'<>]*)?)',
        r'(?P<u>/[^\s"\'<>]*elenco_siti_inibiti_tabacchi\.txt(?:\?[^\s"\'<>]*)?)',
        r'(?P<u>[A-Za-z0-9_\-./]*elenco_siti_inibiti_tabacchi\.txt(?:\?[^\s"\'<>]*)?)',
    ]
    for pat in patterns:
        m = re.search(pat, html_text, flags=re.I)
        if m:
            return urljoin(listing_url, m.group("u"))

    return None

VERSION_LINE_RE = re.compile(r"^\s*\d{5,}[_-]\d{4}\.\d{2}\.\d{2}\s*$")

def bytes_to_text_normalized(data, headers):
    charset = None
    try:
        charset = headers.get_content_charset()
    except Exception:
        pass
    if charset:
        try:
            text = data.decode(charset, errors="replace")
        except Exception:
            text = data.decode("utf-8", errors="replace")
    else:
        try:
            text = data.decode("utf-8-sig")
        except Exception:
            text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return text

def clean_sort_dedupe_domains(text):
    lines = text.split("\n")
    cleaned = []
    seen = set()
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if VERSION_LINE_RE.match(s):
            continue
        s = s.lower()
        if s.startswith(("http://", "https://")):
            s = s.split("://", 1)[1]
        s = s.split("/", 1)[0]
        if s.endswith("."):
            s = s[:-1]
        if s.startswith("#"):
            continue
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    cleaned.sort()
    return "\n".join(cleaned) + ("\n" if cleaned else "")

def guess_filename(file_url, headers=None, default="elenco_siti_inibiti_tabacchi.txt"):
    if headers:
        fn = content_disposition_filename(headers)
        if fn:
            return fn
    path = urlparse(file_url).path
    base = os.path.basename(path)
    return base or default

def ensure_txt_name(name):
    return name if name.lower().endswith(".txt") else (os.path.splitext(name)[0] + ".txt")

def save_text_to_path(text: str, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def download(file_url, timeout=25, verbose=False):
    data, ctype, headers = http_get(file_url, timeout=timeout, binary=True)
    if verbose:
        clen = headers.get("Content-Length") or len(data)
        print(f"[INFO] Download: {file_url} ({ctype}, {clen} bytes)", file=sys.stderr)
    return data, ctype, headers

def main():
    ap = argparse.ArgumentParser(
        description="Scarica 'elenco_siti_inibiti_tabacchi.txt' (ADM), pulisce e stampa/salva l'elenco (LF, ordinato, no duplicati)."
    )
    ap.add_argument("--start", default=LISTING_URL, help="URL della pagina (default: %(default)s)")
    ap.add_argument("-o", "--output", default=None,
                    help="Percorso di output (file o cartella). Se omesso, stampa su stdout.")
    ap.add_argument("--timeout", type=int, default=25, help="Timeout HTTP in secondi (default: %(default)s)")
    ap.add_argument("--require-txt", dest="require_txt", action="store_true",
                    help="Fallisce se la risposta scaricata non sembra un file TXT")
    ap.add_argument("-v", "--verbose", action="store_true", help="Log dettagliati su stderr")
    args = ap.parse_args()

    txt_url = find_txt_url_on_page(args.start, timeout=args.timeout, verbose=args.verbose)
    if not txt_url:
        print("ERRORE: impossibile trovare 'elenco_siti_inibiti_tabacchi.txt' sulla pagina.", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"[OK] URL TXT candidato: {txt_url}", file=sys.stderr)

    try:
        data, ctype, headers = download(txt_url, timeout=args.timeout, verbose=args.verbose)
    except Exception as e:
        print(f"ERRORE durante il download: {e}", file=sys.stderr)
        sys.exit(3)

    if args.require_txt and not is_txt_response(txt_url, ctype, headers, data):
        filename = content_disposition_filename(headers)
        detail = f"Content-Type={ctype or 'unknown'}"
        if filename:
            detail += f", filename={filename!r}"
        print(f"ERRORE: la risposta del link selezionato non sembra TXT ({detail}).", file=sys.stderr)
        sys.exit(2)

    text = bytes_to_text_normalized(data, headers)
    result = clean_sort_dedupe_domains(text)

    if args.output is None:
        sys.stdout.write(result)
    else:
        out_arg = Path(args.output)
        if out_arg.exists() and out_arg.is_dir():
            fname = ensure_txt_name(guess_filename(txt_url, headers=headers, default="elenco_siti_inibiti_tabacchi.txt"))
            dest = out_arg / fname
        else:
            if str(out_arg).endswith(os.sep) or (out_arg.suffix == "" and not out_arg.exists()):
                out_arg.mkdir(parents=True, exist_ok=True)
                fname = ensure_txt_name(guess_filename(txt_url, headers=headers, default="elenco_siti_inibiti_tabacchi.txt"))
                dest = out_arg / fname
            else:
                dest = out_arg
                if dest.suffix == "":
                    dest = dest.with_suffix(".txt")
        try:
            save_text_to_path(result, dest)
            if args.verbose:
                print(f"[OK] Salvato: {dest}", file=sys.stderr)
        except Exception as e:
            print(f"ERRORE nel salvataggio su {dest}: {e}", file=sys.stderr)
            sys.exit(4)

if __name__ == "__main__":
    main()
