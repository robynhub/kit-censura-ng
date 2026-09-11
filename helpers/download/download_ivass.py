#!/usr/bin/env python3
"""IVASS PDF adapter: stdlib HTTP/HTML + optional pypdf. Fail on partial downloads."""
import argparse
import io
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
from kit.lists import domain

DASHES = str.maketrans({x: '-' for x in '\u2010\u2011\u2012\u2013\u2014\u2212\ufe58\ufe63\uff0d'})
CANDIDATE = re.compile(r'(?<![\w@.-])[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,63}(?![\w.-])')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            self.urls.extend(v for k, v in attrs if k.lower() == 'href' and v)


def fetch(url, timeout):
    if urlsplit(url).scheme != 'https':
        raise ValueError('HTTPS required')
    with urlopen(Request(url, headers={'User-Agent': 'kit-censura-ng/2.0'}), timeout=timeout) as response:
        if urlsplit(response.url).scheme != 'https':
            raise ValueError('Insecure redirect')
        return response.read()


def extract(data, suffixes, excluded):
    from pypdf import PdfReader
    found = set()
    reader = PdfReader(io.BytesIO(data))
    for page in reader.pages:
        text = (page.extract_text() or '').translate(DASHES)
        candidates = [m.group(0) for m in CANDIDATE.finditer(text)]
        for reference in page.get('/Annots', []):
            annotation = reference.get_object()
            action = annotation.get('/A')
            if action and action.get('/S') == '/URI':
                candidates.append(urlsplit(str(action.get('/URI', '')).translate(DASHES)).hostname or '')
        for candidate in candidates:
            try:
                name = domain(candidate)
            except (ValueError, UnicodeError):
                continue
            if name.rsplit('.', 1)[1] in suffixes and not any(name == x or name.endswith('.' + x) for x in excluded):
                found.add(name)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True)
    parser.add_argument('--exclude-file', required=True)
    parser.add_argument('--tlds', default=str(Path(__file__).with_name('tlds.txt')))
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--max-pages', type=int, default=1000)
    args = parser.parse_args()
    suffixes = {x.lower() for x in Path(args.tlds).read_text().splitlines() if x and not x.startswith('#')}
    excluded = {x.strip() for x in Path(args.exclude_file).read_text().splitlines() if x and not x.startswith('#')}
    pdfs, seen, result = set(), set(), set()
    url = args.start
    for _ in range(args.max_pages):
        if url in seen:
            raise ValueError('Pagination loop')
        seen.add(url)
        links = Links()
        links.feed(fetch(url, args.timeout).decode('utf-8'))
        urls = [urljoin(url, x) for x in links.urls]
        pdfs.update(x for x in urls if 'ivcs' in x.lower() and '.pdf' in x.lower())
        next_page = len(seen) + 1
        next_urls = [x for x in urls if re.search(r'[?&]page=%d(?:&|$)' % next_page, x)]
        if not next_urls:
            break
        url = next_urls[0]
    else:
        raise ValueError('Pagination limit reached; refusing a partial snapshot')
    if not pdfs:
        raise ValueError('No PDF documents found')
    for url in sorted(pdfs):
        result.update(extract(fetch(url, args.timeout), suffixes, excluded))
    if not result:
        raise ValueError('No domains found')
    print('\n'.join(sorted(result)))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('IVASS download failed: %s: %s' % (type(error).__name__, error), file=sys.stderr)
        sys.exit(1)
