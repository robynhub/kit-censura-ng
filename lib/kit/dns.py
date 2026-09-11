"""DNS renderers. Category names and responses come exclusively from configuration."""
import ipaddress
import re
from .lists import domain


def absolute_name(value):
    return domain(value) + '.'


def render(config, destination, categories):
    zones = destination / 'zones'
    zones.mkdir()
    zone_dir = config.get('dns', 'bind_zone_directory', '/etc/bind/censura/current/zones')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', zone_dir) or '..' in zone_dir.split('/'):
        raise ValueError('bind_zone_directory must be a safe absolute path')
    ttl = config.integer('dns', 'ttl', 300, maximum=2147483647)
    serial = config.integer('dns', 'serial', 1, minimum=1, maximum=4294967295)
    ns = absolute_name(config.get('dns', 'soa_ns', 'ns.localhost.'))
    mailbox = absolute_name(config.get('dns', 'soa_mailbox', 'root.localhost.'))
    refresh = config.integer('dns', 'refresh', 2419200)
    retry = config.integer('dns', 'retry', 2419200)
    expire = config.integer('dns', 'expire', 2419200)
    named, unbound, owners = [], ['server:'], {}
    # File order defines deterministic precedence for an identical domain.
    for name, section, names in categories:
        named.append('// category: ' + name)
        unbound.append('    # category: ' + name)
        zone = ['$TTL %d' % ttl,
                '@ IN SOA %s %s (%d %d %d %d %d)' % (ns, mailbox, serial, refresh, retry, expire, ttl),
                '@ IN NS ' + absolute_name(config.get('dns', 'zone_ns', 'ns.localhost.'))]
        for key, rtype, version in (('bind_a', 'A', 4), ('bind_aaaa', 'AAAA', 6)):
            for value in config.get(section, key).split():
                ip = ipaddress.ip_address(value)
                if ip.version != version:
                    raise ValueError('Wrong address family for ' + key)
                zone.append('@ IN %s %s' % (rtype, ip))
        wildcard = config.get(section, 'bind_wildcard')
        if wildcard:
            try:
                ip = ipaddress.ip_address(wildcard)
                zone.append('* IN %s %s' % ('A' if ip.version == 4 else 'AAAA', ip))
            except ValueError:
                zone.append('* IN CNAME ' + absolute_name(wildcard))
        (zones / ('db.' + name)).write_text('\n'.join(zone) + '\n', encoding='utf-8')
        redirect = config.get(section, 'unbound_redirect')
        record = None
        if redirect:
            try:
                ip = ipaddress.ip_address(redirect)
                record = ('A' if ip.version == 4 else 'AAAA') + ' ' + str(ip)
            except ValueError:
                record = 'CNAME ' + absolute_name(redirect)
        mode = config.get(section, 'unbound_mode', 'legacy')
        if mode not in ('legacy', 'redirect', 'static', 'always_nxdomain', 'refuse'):
            raise ValueError('Invalid unbound_mode')
        if mode == 'redirect' and (not record or record.startswith('CNAME')):
            raise ValueError('Unbound redirect mode requires an IP response')
        for d in names:
            if d in owners:
                continue
            owners[d] = name
            named.append('zone "%s" { type master; file "%s/db.%s"; };' % (d, zone_dir, name))
            if mode != 'legacy':
                unbound.append('    local-zone: "%s" %s' % (d, mode))
            if record and mode in ('legacy', 'redirect', 'static'):
                unbound.append('    local-data: "%s %d IN %s"' % (d, ttl, record))
            elif mode == 'legacy':
                unbound.append('    local-zone: "%s" static' % d)
    (destination / 'named.conf').write_text('\n'.join(named) + '\n', encoding='utf-8')
    (destination / 'unbound.conf').write_text('\n'.join(unbound) + '\n', encoding='utf-8')
    return owners
