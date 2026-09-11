"""Command entry point, shared lock, exit codes and audit lifecycle."""
import argparse
import datetime
import json
import os
import shutil
import sys
import uuid
from .audit import Audit
from .config import Config
from .pipeline import Lock, build, verify
from .deploy import apply


def doctor(config):
    missing = []
    for name, section in config.categories:
        for executable in config.get(section, 'requires').split():
            if not shutil.which(executable):
                missing.append(executable)
        for module in config.get(section, 'python_modules').split():
            import importlib.util
            if importlib.util.find_spec(module) is None:
                missing.append('Python module ' + module)
        for key in ('download', 'parser'):
            if config.get(section, key):
                command = config.command(section, key, dict(python=sys.executable))
                if not command or not shutil.which(command[0]):
                    missing.append(section + ' ' + key + ' executable')
    if any(config.boolean('upload:' + b, 'enabled') for b in ('bind', 'unbound')):
        missing.extend(x for x in ('ssh', 'rsync', 'bash') if not shutil.which(x))
    if config.boolean('routes', 'enabled') and not shutil.which('ip'):
        missing.append('ip (iproute2)')
    if missing:
        raise RuntimeError('Missing prerequisites: ' + ', '.join(sorted(set(missing))))
    print('OK: Python >= 3.8.10, configuration and configured helper prerequisites')
    print('Remote DNS validators and credentials are checked when used.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='kit-censura-ng 2.0.0')
    parser.add_argument('--config', '-c', default=os.environ.get('KIT_CONFIG', 'config/kit.ini'))
    parser.add_argument('--debug', action='store_true',
                        help='Show structured event fields and helper stderr; helper stderr is not written to the audit log')
    parser.add_argument('--dry-run', action='store_true', help='Plan apply only, without remote/routing changes')
    parser.add_argument('--category', action='append', help='Refresh only this category, retain other cached lists')
    parser.add_argument('command', choices=('doctor', 'update', 'build', 'apply', 'run', 'summary', 'verify'))
    args = parser.parse_args()
    audit = None
    try:
        if sys.version_info < (3, 8, 10):
            raise RuntimeError('Python 3.8.10 or newer required')
        config = Config(args.config)
        if args.command == 'doctor':
            doctor(config)
            return 0
        with Lock(config.state):
            run_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:12]
            audit = Audit(config.log, run_id, args.debug or config.boolean('kit', 'debug'))
            audit.emit('run_started', command=args.command, dry_run=args.dry_run,
                       selected_categories=args.category or [])
            degraded, failed = False, False
            if args.command in ('update', 'build', 'run'):
                _, manifest = build(config, audit, args.category, args.command != 'build')
                degraded = manifest['degraded']
            if args.command in ('apply', 'run'):
                _, applied_manifest = verify(config)
                degraded = applied_manifest['degraded']
                failed = apply(config, audit, args.dry_run)
            if args.command in ('summary', 'verify'):
                _, manifest = verify(config)
                degraded = manifest['degraded']
                audit.emit('integrity_verified', generation=manifest['run_id'])
                if args.command == 'summary':
                    for name, stats in manifest['lists'].items():
                        audit.emit('list_statistics', category=name, **stats)
                    print(json.dumps(dict(lists=manifest['lists'], totals=manifest['totals']), indent=2))
            rc = 1 if failed else 2 if degraded else 0
            audit.emit('run_finished', level='ERROR' if failed else 'WARNING' if degraded else 'INFO', exit_code=rc)
            return rc
    except Exception as error:
        # Generic failures must not leak credentials from URLs, subprocess args or INI.
        if audit:
            audit.emit('run_failed', level='ERROR', error_type=type(error).__name__)
        print('ERROR: %s' % (str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__), file=sys.stderr)
        return 1
    finally:
        if audit:
            audit.close()
