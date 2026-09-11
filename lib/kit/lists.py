"""Validated domain/IP lists and exact (never expanding) CIDR aggregation."""
import ipaddress
import re
from urllib.parse import urlsplit

LABEL = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
VERSION = re.compile(r'^\d+[_-]\d{4}\.\d{2}\.\d{2}$')


def domain(value):
    value = value.lower().rstrip('.').encode('idna').decode('ascii')
    labels = value.split('.')
    if (len(value) > 253 or len(labels) < 2 or labels[-1].isdigit()
            or not all(LABEL.fullmatch(x) for x in labels)):
        raise ValueError('Invalid domain')
    return value


def network(value):
    if '%' in value:
        raise ValueError('Scoped IPs are unsupported')
    return ipaddress.ip_network(value, strict=False)


def lines(text):
    return [line.split('#', 1)[0].strip() for line in text.lstrip('\ufeff').splitlines()
            if line.split('#', 1)[0].strip()]


def parse(text, url_policy='host', invalid_policy='fail'):
    if url_policy not in ('host', 'reject', 'ignore') or invalid_policy not in ('fail', 'skip'):
        raise ValueError('Invalid parsing policy')
    domains, ips = set(), set()
    stats = dict(input=0, invalid=0, ignored_urls=0, duplicates=0)
    for value in lines(text):
        if VERSION.fullmatch(value):
            continue
        stats['input'] += 1
        try:
            if value.startswith(('http://', 'https://')):
                url = urlsplit(value)
                if url.username or url.password or not url.hostname:
                    raise ValueError('Invalid URL')
                if url.path not in ('', '/') or url.query or url.fragment:
                    if url_policy == 'ignore':
                        stats['ignored_urls'] += 1
                        continue
                    if url_policy == 'reject':
                        raise ValueError('Path-specific URL cannot be blocked by DNS')
                value = url.hostname
            try:
                item = str(network(value))
                target = ips
            except ValueError:
                item = domain(value)
                target = domains
            if item in target:
                stats['duplicates'] += 1
            target.add(item)
        except (ValueError, UnicodeError):
            stats['invalid'] += 1
            if invalid_policy == 'fail':
                # Do not place list contents in an audit error or traceback.
                raise ValueError('Invalid list entry at record %d' % stats['input']) from None
    return sorted(domains), sorted(ips), stats


def covered(name, domains):
    labels = name.split('.')
    return any('.'.join(labels[i:]) in domains for i in range(len(labels)))


def filter_domains(domains, allowed, remove_subdomains):
    filtered = {d for d in domains if not covered(d, allowed)}
    if remove_subdomains:
        filtered = {d for d in filtered if not covered(d.split('.', 1)[1], filtered)}
    return sorted(filtered)


def filter_ips(values, allowed):
    """Subtract whitelisted ranges, including a whitelist inside a blocked range."""
    result = []
    for value in values:
        fragments = [network(value)]
        for permit in allowed:
            remaining = []
            for part in fragments:
                if part.version != permit.version or not part.overlaps(permit):
                    remaining.append(part)
                elif not part.subnet_of(permit):
                    remaining.extend(part.address_exclude(permit))
            fragments = remaining
        result.extend(fragments)
    return sorted(set(result), key=lambda n: (n.version, int(n.network_address), n.prefixlen))


def aggregate(values, min_v4=25, min_v6=0):
    """Merge siblings only; preserve original networks broader than the merge floor."""
    original = set(values)
    result = []
    for version, floor in ((4, min_v4), (6, min_v6)):
        collapsed = ipaddress.collapse_addresses(n for n in original if n.version == version)
        for net in collapsed:
            if net.prefixlen >= floor or net in original:
                result.append(net)
            else:
                # Keep originally broad entries, split only newly merged prefixes.
                broad = [n for n in original if n.version == version
                         and n.subnet_of(net) and n.prefixlen < floor]
                pieces = filter_ips([str(net)], broad)
                result.extend(broad)
                for part in pieces:
                    result.extend(part.subnets(new_prefix=floor) if part.prefixlen < floor else [part])
    return sorted(set(result), key=lambda n: (n.version, int(n.network_address), n.prefixlen))
