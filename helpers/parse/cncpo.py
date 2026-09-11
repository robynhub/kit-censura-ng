#!/usr/bin/env python3
"""CNCPO CSV -> lines. Keep upstream domain precedence over an IP in the same row."""
import csv
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
from kit.lists import domain, network


def convert(text):
    rows = list(csv.reader(text.splitlines(), delimiter=';', strict=True))
    if not rows or len(rows[0]) != 2 or not all(x.strip().isdigit() for x in rows[0]):
        raise ValueError('Invalid CSV serial/timestamp header')
    result = []
    for row in rows[1:]:
        if not any(x.strip() for x in row):
            continue
        if len(row) != 4:
            raise ValueError('Expected four CSV fields')
        url, host, ipurl, ip = [x.strip() for x in row]
        if url:
            extracted = domain(urlsplit(url if '://' in url else 'http://' + url).hostname or '')
            if host and domain(host) != extracted:
                raise ValueError('Mismatched CSV domain fields')
            host = extracted
        if ipurl:
            extracted = str(network(urlsplit(ipurl if '://' in ipurl else 'http://' + ipurl).hostname or ''))
            if ip and str(network(ip)) != extracted:
                raise ValueError('Mismatched CSV IP fields')
            ip = extracted
        if host:
            result.append(domain(host))
        elif ip:
            result.append(str(network(ip)))
        else:
            raise ValueError('Empty record')
    return result


if __name__ == '__main__':
    try:
        print('\n'.join(convert(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))))
    except Exception:
        print('Invalid CNCPO CSV', file=sys.stderr)
        sys.exit(1)
