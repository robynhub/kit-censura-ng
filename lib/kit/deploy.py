"""Deployment calls isolated Bash helpers; success is recorded per destination."""
import os
import subprocess
from .config import ROOT
from .pipeline import execute, verify


def apply(config, audit, dry_run=False):
    generation, manifest = verify(config)
    failed = False
    targets = 0
    for backend in ('bind', 'unbound'):
        section = 'upload:' + backend
        if not config.boolean(section, 'enabled', False):
            continue
        servers = config.get(section, 'servers').split()
        if not servers:
            raise ValueError(section + ': servers is empty')
        remote_root = config.get(section, 'remote_root')
        if backend == 'bind' and config.get('dns', 'bind_zone_directory') != remote_root + '/current/zones':
            raise ValueError('bind_zone_directory must match upload remote_root/current/zones')
        for server in servers:
            targets += 1
            if dry_run:
                audit.emit('upload_planned', backend=backend, server=server, generation=manifest['run_id'])
                continue
            try:
                command = [str(ROOT / 'helpers/deploy/upload.sh'), backend, server, remote_root,
                           str(generation), config.get(section, 'main_config'),
                           str(config.integer(section, 'connect_timeout', 10, 1)),
                           str(config.integer(section, 'ssh_port', 22, 1, 65535))]
                execute(command, config, audit, 'upload', timeout=config.integer(section, 'timeout', 180, 1))
                audit.emit('dns_applied', server=server, backend=backend, generation=manifest['run_id'])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                failed = True
                audit.emit('dns_apply_failed', level='ERROR', server=server, backend=backend, error=str(error))
    if config.boolean('routes', 'enabled', False):
        targets += 1
        if dry_run:
            audit.emit('routes_planned', prefixes=manifest['totals']['route_prefixes'])
        else:
            try:
                command = [str(ROOT / 'helpers/deploy/routes.sh'), str(generation / 'routes.txt'),
                           config.get('routes', 'table', '254'), config.get('routes', 'protocol', '186'),
                           config.get('routes', 'nexthop_v4'), config.get('routes', 'nexthop_v6')]
                execute(command, config, audit, 'routes', timeout=config.integer('routes', 'timeout', 300, 1))
                audit.emit('routes_applied', generation=manifest['run_id'], prefixes=manifest['totals']['route_prefixes'])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                failed = True
                audit.emit('routes_apply_failed', level='ERROR', error=str(error))
    if not targets:
        audit.emit('apply_skipped', reason='No deployment enabled')
    # Optional notification hook runs only after every enabled deployment succeeds.
    if targets and not failed and not dry_run and config.get('hooks', 'after_apply'):
        env = dict(os.environ, KIT_GENERATION=str(generation), KIT_RUN_ID=manifest['run_id'])
        execute(config.command('hooks', 'after_apply', dict(generation=str(generation))),
                config, audit, 'after_apply', env=env)
    return failed
