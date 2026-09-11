#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download the latest AGCOM "Allegato B" TXT list.

AGCOM may expose attachments through opaque download URLs. Candidate discovery is
therefore based on page semantics, while --require-txt validates the downloaded
response rather than requiring a .txt suffix in the URL.
"""
import argparse
import html
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

LISTING_URL = "https://www.agcom.it/provvedimenti-a-tutela-del-diritto-d-autore"
UA = "Mozilla/5.0 (Python urllib; AGCOM Allegato B fetcher)"
FILE_EXTS = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".csv", ".zip", ".7z", ".txt")
VERSION_LINE_RE = re.compile(r"^\s*\d{5,}[_-]\d{4}\.\d{2}\.\d{2}\s*$")


class AnchorCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = next((v.strip() for k, v in attrs if k.lower() == "href" and v), None)
            self._buf = []

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            if self._href:
                self.links.append((self._href, html.unescape("".join(self._buf)).strip()))
            self._href = None
            self._buf = []

    def handle_data(self, data):
        if self._href is not None and data:
            self._buf.append(data)


def http_get(url, timeout=25, binary=False):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if binary:
            return data, resp.headers.get_content_type(), resp.headers
        charset = resp.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace"), resp.headers.get_content_type(), resp.headers


def parse_anchors(base_url, html_text):
    parser = AnchorCollector()
    parser.feed(html_text)
    out, seen = [], set()
    for href, text in parser.links:
        if not href or href.startswith("#"):
            continue
        url = urljoin(base_url, href)
        key = (url, text)
        if key not in seen:
            out.append(key)
            seen.add(key)
    return out


def is_same_domain(url, domain="agcom.it"):
    try:
        host = (urlparse(url).hostname or "").lower()
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def is_txt_url(url):
    parsed = urlparse(url)
    if parsed.path.lower().endswith(".txt"):
        return True
    return any(".txt" in value.lower() for values in parse_qs(parsed.query).values() for value in values)


def looks_like_file_url(url):
    return urlparse(url).path.lower().endswith(FILE_EXTS)


def content_disposition_filename(headers):
    value = headers.get("Content-Disposition") or headers.get("content-disposition")
    if not value:
        return None
    match = re.search(r"filename\*\s*=\s*(?:UTF-8''|utf-8'')?([^;]+)", value, re.I)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1)).strip("\"' ")
    match = re.search(r'filename\s*=\s*"([^"]+)"', value, re.I)
    if match:
        return match.group(1)
    match = re.search(r"filename\s*=\s*([^;]+)", value, re.I)
    return match.group(1).strip("\"' ") if match else None


def is_txt_response(url, ctype, headers, data):
    """Accept text attachments even when the provider uses an opaque URL."""
    if is_txt_url(url):
        return True
    filename = content_disposition_filename(headers)
    if filename and filename.lower().endswith(".txt"):
        return True
    ctype = (ctype or "").lower()
    if ctype == "text/plain":
        return True
    prefix = data[:512].lstrip().lower()
    if prefix.startswith(b"%pdf-") or prefix.startswith(b"pk\x03\x04") or prefix.startswith(b"\xd0\xcf\x11\xe0"):
        return False
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        return False
    return ctype in ("application/octet-stream", "application/download", "binary/octet-stream", "")


def find_download_links(page_url, html_text):
    candidates = []
    for url, text in parse_anchors(page_url, html_text):
        low = text.lower()
        if looks_like_file_url(url) or any(word in low for word in ("download", "scarica", "allegato")):
            candidates.append(url)
    return candidates


def resolve_allegato_b_urls(post_url, timeout, verbose=False):
    html_text, ctype, _ = http_get(post_url, timeout=timeout)
    if verbose:
        print(f"[INFO] Apertura post: {post_url} (Content-Type: {ctype})", file=sys.stderr)
    preferred, other = [], []
    for url, text in parse_anchors(post_url, html_text):
        if not is_same_domain(url) or "allegato b" not in text.lower():
            continue
        if looks_like_file_url(url) or "download" in url.lower():
            (preferred if is_txt_url(url) else other).append(url)
            continue
        try:
            inner, inner_type, _ = http_get(url, timeout=timeout)
            if verbose:
                print(f"[INFO] Apertura pagina allegato: {url} (Content-Type: {inner_type})", file=sys.stderr)
        except Exception as error:
            if verbose:
                print(f"[WARN] Impossibile aprire pagina allegato: {url} ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        for candidate in find_download_links(url, inner):
            (preferred if is_txt_url(candidate) else other).append(candidate)

    if not preferred and not other:
        for url, text in parse_anchors(post_url, html_text):
            if not is_same_domain(url):
                continue
            low = text.lower().strip()
            if ("download" in url.lower() or looks_like_file_url(url)) and ("allegato" in low or low == "b"):
                (preferred if is_txt_url(url) else other).append(url)
    return dedupe(preferred), dedupe(other)


def dedupe(values):
    out, seen = [], set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def pick_latest_post_with_allegato_b(listing_url, timeout, verbose=False, max_candidates=60):
    listing, ctype, _ = http_get(listing_url, timeout=timeout)
    if verbose:
        print(f"[INFO] Apertura listing: {listing_url} (Content-Type: {ctype})", file=sys.stderr)
    checked, seen = 0, set()
    for url, _ in parse_anchors(listing_url, listing):
        if checked >= max_candidates:
            break
        if not url.lower().startswith("http") or not is_same_domain(url) or url in seen:
            continue
        seen.add(url)
        if urlparse(url).path.lower().endswith((".jpg", ".png", ".gif", ".svg", ".css", ".js")):
            continue
        checked += 1
        if verbose:
            print(f"[INFO] Controllo post candidato {checked}: {url}", file=sys.stderr)
        try:
            preferred, other = resolve_allegato_b_urls(url, timeout, verbose)
        except Exception as error:
            if verbose:
                print(f"[WARN] Errore su {url}: {type(error).__name__}: {error}", file=sys.stderr)
            continue
        if preferred or other:
            return url, preferred, other
    return None, [], []


def bytes_to_text_normalized(data, headers):
    charset = headers.get_content_charset() if headers else None
    try:
        text = data.decode(charset or "utf-8-sig")
    except (LookupError, UnicodeDecodeError):
        text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def clean_sort_dedupe_domains(text):
    result = set()
    for line in text.splitlines():
        value = line.strip().lower()
        if not value or value.startswith("#") or VERSION_LINE_RE.match(value):
            continue
        if value.endswith("."):
            value = value[:-1]
        result.add(value)
    return "\n".join(sorted(result)) + ("\n" if result else "")


def download(url, timeout=25, verbose=False):
    data, ctype, headers = http_get(url, timeout=timeout, binary=True)
    if verbose:
        print(f"[INFO] Download: {url} ({ctype}, {headers.get('Content-Length') or len(data)} bytes)", file=sys.stderr)
    return data, ctype, headers


def choose_download(candidates, timeout, require_txt, verbose):
    """Try candidates until one satisfies the requested response format."""
    failures = []
    for url in candidates:
        try:
            data, ctype, headers = download(url, timeout, verbose)
        except Exception as error:
            failures.append(f"{type(error).__name__}: {error}")
            if verbose:
                print(f"[WARN] Download candidato fallito: {url} ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        if require_txt and not is_txt_response(url, ctype, headers, data):
            filename = content_disposition_filename(headers)
            detail = f"Content-Type={ctype or 'unknown'}"
            if filename:
                detail += f", filename={filename!r}"
            failures.append("not TXT: " + detail)
            if verbose:
                print(f"[WARN] Candidato scartato: {url} ({detail})", file=sys.stderr)
            continue
        return url, data, headers
    detail = failures[-1] if failures else "no usable candidate"
    raise RuntimeError("no usable Allegato B download: " + detail)


def save_result(result, output, chosen_url, headers):
    if output is None:
        sys.stdout.write(result)
        return
    out = Path(output)
    filename = content_disposition_filename(headers) or os.path.basename(urlparse(chosen_url).path) or "Allegato_B.txt"
    if not filename.lower().endswith(".txt"):
        filename = os.path.splitext(filename)[0] + ".txt"
    if out.exists() and out.is_dir():
        dest = out / filename
    elif str(out).endswith(os.sep) or (out.suffix == "" and not out.exists()):
        out.mkdir(parents=True, exist_ok=True)
        dest = out / filename
    else:
        dest = out if out.suffix else out.with_suffix(".txt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result, encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description="Scarica l'ultimo Allegato B AGCOM e produce la lista normalizzata.")
    parser.add_argument("--start", default=LISTING_URL)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--max-candidates", type=int, default=60)
    parser.add_argument("--require-txt", action="store_true",
                        help="Fallisce se nessuna risposta candidata risulta un file TXT")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    post, preferred, other = pick_latest_post_with_allegato_b(
        args.start, args.timeout, args.verbose, args.max_candidates)
    if not post:
        raise RuntimeError("non sono riuscito a individuare un post con 'Allegato B'")
    if args.verbose:
        print(f"[OK] Post trovato: {post}", file=sys.stderr)
        print(f"[INFO] Candidati: {len(preferred) + len(other)} ({len(preferred)} URL riconoscibili come TXT)", file=sys.stderr)
    candidates = preferred + other
    if not candidates:
        raise RuntimeError("nessun link per 'Allegato B' trovato nel post")
    chosen, data, headers = choose_download(candidates, args.timeout, args.require_txt, args.verbose)
    result = clean_sort_dedupe_domains(bytes_to_text_normalized(data, headers))
    if not result:
        raise RuntimeError("Allegato B scaricato ma lista risultante vuota")
    save_result(result, args.output, chosen, headers)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"AGCOM download failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
