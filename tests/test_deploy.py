"""Real activation logic with mocked DNS services; optional native syntax checks."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from kit.config import Config
from kit.dns import render


class NativeDNS(unittest.TestCase):
    def test_native_rendered_config(self):
        if not shutil.which('named-checkconf') or not shutil.which('unbound-checkconf'):
            self.skipTest('Native BIND/Unbound validators not installed')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config_file = base / 'kit.ini'
            example = (ROOT / 'config/kit.ini.example').read_text().replace('enabled = false', 'enabled = true')
            example = example.replace('/etc/bind/censura/current/zones', str(base / 'zones'))
            config_file.write_text(example)
            config = Config(config_file)
            render(config, base, [(n, s, [n + '.example']) for n, s in config.categories])
            for command in (['named-checkconf', str(base / 'named.conf')],
                            ['unbound-checkconf', str(base / 'unbound.conf')]):
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for name, _ in config.categories:
                subprocess.run(['named-checkzone', name + '.example', str(base / 'zones' / ('db.' + name))],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@unittest.skipUnless(sys.platform.startswith('linux'), 'Remote activation targets Linux (mv -T)')
class ActivationTest(unittest.TestCase):
    def test_reload_failure_restores_previous_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'releases/old').mkdir(parents=True)
            (base / 'releases/new/zones').mkdir(parents=True)
            (base / 'releases/new/named.conf').write_text('')
            (base / 'current').symlink_to('releases/old')
            commands = base / 'bin'
            commands.mkdir()
            for name in ('named-checkconf', 'named-checkzone'):
                path = commands / name
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            rndc = commands / 'rndc'
            rndc.write_text('#!/bin/sh\nexit 1\n')
            rndc.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'])
            process = subprocess.run(['bash', str(ROOT / 'helpers/deploy/activate.sh'), 'bind', str(base), 'new', '/etc/bind/named.conf'],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(os.readlink(str(base / 'current')), 'releases/old')
            self.assertFalse((base / '.activate-lock').exists())


class UploadFailureTest(unittest.TestCase):
    def test_failed_upload_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'source').write_text('blocked.example\n')
            config = base / 'kit.ini'
            config.write_text('[kit]\nstate_dir=state\nlog_file=audit\n[category:test]\ndownload=' +
                              json.dumps([str(ROOT / 'helpers/download/local.sh'), str(base / 'source')]) +
                              '\n[upload:unbound]\nenabled=true\nservers=server.example\nremote_root=/etc/unbound/censura\nmain_config=/etc/unbound/unbound.conf\n')
            commands = base / 'bin'
            commands.mkdir()
            for name in ('ssh', 'rsync'):
                path = commands / name
                path.write_text('#!/bin/sh\nexit 1\n')
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + ':' + os.environ['PATH'], KIT_PYTHON=sys.executable)
            result = subprocess.run([str(ROOT / 'bin/kit-censura-ng'), '-c', str(config), 'run'], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 1)
            events = [json.loads(x)['event'] for x in (base / 'audit').read_text().splitlines()]
            self.assertIn('dns_apply_failed', events)
            self.assertNotIn('dns_applied', events)
