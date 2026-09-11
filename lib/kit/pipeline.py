"""Locked, staged generations: the current snapshot changes only after validation."""
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from .audit import digest
from .dns import render
from .lists import parse, lines, domain, network, filter_domains, filter_ips, aggregate


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def write_lines(path, values):
    path.write_text(''.join(str(x) + '\n' for x in values), encoding='utf-8')


class Lock:
    def __init__(self, state):
        state.mkdir(parents=True, exist_ok=True)
        self.path = state / '.lock'

    def __enter__(self):
        self.stream = self.path.open('a')
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stream.close()
            raise RuntimeError('Another process is using this state directory') from None
        return self

    def __exit__(self, *args):
        self.stream.close()


def execute(command, config, audit, event, output=None, timeout=None, env=None):
    if not command:
        raise ValueError('Empty command: ' + event)
    effective_timeout = timeout or config.integer('kit', 'helper_timeout', 300, 1)
    audit.emit(event + '_started', level='DEBUG', executable=Path(command[0]).name,
               timeout=effective_timeout)
    # stderr can contain provider credentials, so it must never be copied into
    # the audit log. With explicit debug enabled, inherit stderr instead: helper
    # diagnostics go directly to the operator's terminal and remain outside the
    # persistent structured log.
    with open(os.devnull, 'wb') as null:
        result = subprocess.Popen(command, cwd=str(config.base), stdout=output or null,
                                  stderr=None if audit.debug else null,
                                  env=env, start_new_session=True)
        try:
            result.wait(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            os.killpg(result.pid, signal.SIGKILL)
            result.wait()
            raise RuntimeError('%s timed out after %ds' % (event, effective_timeout)) from None
    if result.returncode:
        raise RuntimeError('%s exited with status %d' % (event, result.returncode))
    audit.emit(event + '_completed', level='DEBUG')


def build(config, audit, selected=None, refresh=True):
    if selected and set(selected) - {n for n, _ in config.categories}:
        raise ValueError('Unknown or disabled category selected')
    previous = config.state / 'current'
    generation = config.state / 'generations' / audit.run_id
    generation.mkdir(parents=True)
    rawdir, listdir, sourcedir = [generation / x for x in ('raw', 'lists', 'sources')]
    for path in (rawdir, listdir, sourcedir):
        path.mkdir()
    allowed_domains, allowed_ips = set(), []
    dp = config.path_value('kit', 'whitelist_domains')
    ip = config.path_value('kit', 'whitelist_ips')
    # A configured but missing/invalid whitelist is a fatal error.
    if dp:
        allowed_domains = {domain(v) for v in lines(dp.read_text(encoding='utf-8'))}
    if ip:
        allowed_ips = [network(v) for v in lines(ip.read_text(encoding='utf-8'))]
    categories, all_ips, route_ips, statistics, degraded = [], [], [], {}, False
    failures = []
    for name, section in config.categories:
        old = previous / 'raw' / (name + '.json')
        cached = json.loads(old.read_text(encoding='utf-8')) if old.exists() else None
        data = None
        status = 'cached'
        update = refresh and config.boolean(section, 'update', True) and (not selected or name in selected)
        refresh_error = None
        if update:
            try:
                source = sourcedir / (name + '.txt')
                values = dict(category=name, output=str(source), python=sys.executable)
                if config.get(section, 'before_download'):
                    execute(config.command(section, 'before_download', values), config, audit, 'prepare_' + name)
                command = config.command(section, 'download', values)
                with source.open('wb') as stream:
                    execute(command, config, audit, 'download_' + name, stream,
                            config.integer(section, 'timeout', config.integer('kit', 'helper_timeout', 300, 1), 1))
                max_bytes = config.integer('kit', 'max_source_bytes', 104857600, 1)
                if source.stat().st_size > max_bytes:
                    raise ValueError('Source exceeds max_source_bytes')
                parsed = source
                if config.get(section, 'parser'):
                    parsed = sourcedir / (name + '.parsed.txt')
                    command = config.command(section, 'parser', dict(values, input=str(source)))
                    with parsed.open('wb') as stream:
                        execute(command, config, audit, 'parse_' + name, stream)
                domains, ips, stats = parse(parsed.read_text(encoding=config.get(section, 'encoding', 'utf-8-sig')),
                                            config.get(section, 'url_policy', 'host'),
                                            config.get(section, 'invalid_policy', 'fail'))
                total = len(domains) + len(ips)
                minimum = config.integer(section, 'min_entries', 1)
                if total < minimum:
                    raise ValueError('List below min_entries')
                if cached:
                    old_count = len(cached['domains']) + len(cached['ips'])
                    drop = config.integer(section, 'max_drop_percent', 100, maximum=100)
                    if old_count and total < old_count * (100 - drop) / 100:
                        raise ValueError('List exceeds max_drop_percent')
                data = dict(domains=domains, ips=ips, stats=stats, fetched_at=time.time(),
                            source_sha256=digest(source))
                status = 'downloaded'
                audit.emit('source_validated', category=name, source_sha256=data['source_sha256'], **stats)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                degraded = True
                refresh_error = error
                audit.emit('source_failed', level='ERROR', category=name,
                           error_type=type(error).__name__, error=str(error))
                if config.get('kit', 'on_failure', 'keep') == 'abort':
                    failures.append(name)
                status = 'stale'
        if data is None:
            data = cached
            if data is None:
                failures.append(name)
                if refresh_error is not None:
                    reason = 'refresh_failed_no_cache'
                elif selected and name not in selected:
                    reason = 'not_selected_no_cache'
                elif not refresh:
                    reason = 'build_requested_no_cache'
                else:
                    reason = 'no_cache'
                audit.emit('source_unavailable', level='ERROR', category=name, reason=reason)
                continue
            max_age = config.integer(section, 'max_age_seconds', 0)
            if max_age and time.time() - data['fetched_at'] > max_age:
                failures.append(name)
                audit.emit('source_expired', level='ERROR', category=name)
                continue
        write_json(rawdir / (name + '.json'), data)
        domains = filter_domains(data['domains'], allowed_domains,
                                 config.boolean(section, 'remove_subdomains', False))
        # A BIND parent zone also shadows whitelisted children. Fail rather than
        # claim an exception is effective when the DNS backend cannot honor it.
        for allowed in allowed_domains:
            if any(allowed.endswith('.' + parent) for parent in domains):
                raise ValueError('Whitelist child conflicts with blocked parent in ' + name)
        ips = filter_ips(data['ips'], allowed_ips)
        write_lines(listdir / name, domains)
        write_lines(listdir / (name + '-ip'), ips)
        categories.append((name, section, domains))
        all_ips.extend(ips)
        if config.boolean(section, 'routes', False):
            route_ips.extend(ips)
        stats = dict(status=status, domains_raw=len(data['domains']), ips_raw=len(data['ips']),
                     domains=len(domains), ip_prefixes=len(ips), fetched_at=data['fetched_at'],
                     source_sha256=data['source_sha256'], parsing=data['stats'])
        statistics[name] = stats
        audit.emit('list_statistics', category=name, **stats)
    if failures:
        raise RuntimeError('No usable snapshot for categories: ' + ', '.join(sorted(set(failures))))
    all_ips = sorted(set(all_ips), key=lambda n: (n.version, int(n.network_address), n.prefixlen))
    floor4 = config.integer('routes', 'min_prefix_v4', 25, maximum=32)
    floor6 = config.integer('routes', 'min_prefix_v6', 0, maximum=128)
    cidrs = aggregate(all_ips, floor4, floor6) if config.boolean('routes', 'aggregate', True) else all_ips
    route_ips = (aggregate(route_ips, floor4, floor6) if config.boolean('routes', 'aggregate', True)
                 else sorted(set(route_ips), key=lambda n: (n.version, int(n.network_address), n.prefixlen)))
    write_lines(generation / 'ip-fullist', all_ips)
    write_lines(generation / 'cidr-fullist', cidrs)
    write_lines(generation / 'routes.txt', route_ips)
    owners = render(config, generation, categories)
    write_json(generation / 'domain-owners.json', owners)
    for backend in ('bind', 'unbound'):
        if config.get('dns', backend + '_check'):
            execute(config.command('dns', backend + '_check', dict(generation=str(generation))),
                    config, audit, backend + '_validation')
    hashes = {str(p.relative_to(generation)): digest(p) for p in generation.rglob('*') if p.is_file()}
    manifest = dict(version='2.0.0', run_id=audit.run_id, config_sha256=digest(config.path),
                    generated_at=time.time(), degraded=degraded, lists=statistics,
                    totals=dict(domains=len(owners), ip_prefixes=len(all_ips),
                                cidrs=len(cidrs), route_prefixes=len(route_ips)), sha256=hashes)
    write_json(generation / 'manifest.json', manifest)
    # The staging generation is complete; a single symlink replacement publishes it.
    pending = config.state / ('.current-' + audit.run_id)
    pending.symlink_to(Path('generations') / audit.run_id)
    os.replace(str(pending), str(previous))
    audit.emit('generation_published', manifest_sha256=digest(generation / 'manifest.json'),
               generation=audit.run_id, degraded=degraded, **manifest['totals'])
    return generation, manifest


def verify(config):
    generation = (config.state / 'current').resolve(strict=True)
    manifest = json.loads((generation / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['config_sha256'] != digest(config.path):
        raise ValueError('Configuration changed; build a new generation before apply')
    for name, expected in manifest['sha256'].items():
        path = generation / name
        if Path(name).is_absolute() or '..' in Path(name).parts or digest(path) != expected:
            raise ValueError('Generation integrity check failed')
    return generation, manifest
