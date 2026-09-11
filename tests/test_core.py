import importlib.util
import ipaddress
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from kit.config import Config
from kit.lists import parse, domain, network, filter_domains, filter_ips, aggregate
from kit.pipeline import Lock


def module(path):
    spec = importlib.util.spec_from_file_location('adapter', str(ROOT / path))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ListsTest(unittest.TestCase):
    def test_normalization_and_statistics(self):
        d, i, stats = parse('EXAMPLE.COM.\nexample.com\nhttps://www.example.org/path\n192.0.2.1\n2001:db8::1\n00001_2025.01.01\n')
        self.assertEqual(d, ['example.com', 'www.example.org'])
        self.assertEqual(i, ['192.0.2.1/32', '2001:db8::1/128'])
        self.assertEqual(stats['duplicates'], 1)
        self.assertEqual(domain('bücher.example'), 'xn--bcher-kva.example')

    def test_validation_and_url_policy(self):
        for value in ('invalid', 'bad..example', 'a";}.example', '999.1.1.1', 'fe80::1%en0', 'http://user:pass@example.org'):
            with self.assertRaises(ValueError):
                parse(value)
        self.assertEqual(parse('https://example.org/path', 'ignore')[2]['ignored_urls'], 1)
        with self.assertRaises(ValueError):
            parse('https://example.org/path', 'reject')
        self.assertEqual(parse('invalid\nexample.org', invalid_policy='skip')[2]['invalid'], 1)

    def test_domain_whitelist_and_pruning(self):
        self.assertEqual(filter_domains(['a.example.org', 'example.org', 'notexample.org'], {'example.org'}, True), ['notexample.org'])
        self.assertEqual(filter_domains(['a.example.org', 'example.org'], set(), True), ['example.org'])

    def test_whitelist_inside_network(self):
        result = filter_ips(['192.0.2.0/24', '2001:db8::/126'], [network('192.0.2.128/25'), network('2001:db8::1')])
        self.assertIn(network('192.0.2.0/25'), result)
        self.assertFalse(any(network('2001:db8::1').subnet_of(n) for n in result if n.version == 6))
        self.assertEqual(sum(n.num_addresses for n in result if n.version == 6), 3)

    def test_aggregation_exact_and_family_separate(self):
        values = [network('192.0.2.0/26'), network('192.0.2.64/26'), network('2001:db8::/127')]
        self.assertEqual(aggregate(values), [network('192.0.2.0/25'), network('2001:db8::/127')])
        self.assertEqual(aggregate([network('10.0.0.0/8')], 25), [network('10.0.0.0/8')])
        self.assertEqual(aggregate([network('192.0.2.0/25'), network('192.0.2.128/25')], 25),
                         [network('192.0.2.0/25'), network('192.0.2.128/25')])

    def test_random_aggregation_preserves_exact_membership(self):
        rng = random.Random(19)
        base = int(ipaddress.ip_address('192.0.2.0'))
        for _ in range(50):
            selected = {rng.randrange(256) for _ in range(120)}
            result = aggregate([network(str(ipaddress.ip_address(base + i))) for i in selected], 25)
            actual = {int(ip) - base for n in result for ip in n}
            self.assertEqual(actual, selected)

    def test_cncpo_precedence_and_validation(self):
        adapter = module('helpers/parse/cncpo.py')
        self.assertEqual(adapter.convert('1;20250101\nhttp://a.example;a.example;http://192.0.2.1;192.0.2.1\n;;http://192.0.2.2;192.0.2.2'), ['a.example', '192.0.2.2/32'])
        with self.assertRaises(ValueError):
            adapter.convert('1;20250101\nhttp://a.example;b.example;;')

    def test_pec_nested_mime(self):
        from email.message import EmailMessage
        import re
        adapter = module('helpers/download/pec.py')
        inner = EmailMessage()
        inner['From'] = 'source@example.org'
        inner.set_content('Snapshot')
        inner.add_attachment(b'example.org', maintype='application', subtype='octet-stream', filename='list.txt')
        outer = EmailMessage()
        outer['From'] = 'pec@example.net'
        outer.set_content('Envelope')
        outer.add_attachment(inner)
        self.assertEqual(adapter.attachment(outer, {'source@example.org'}, re.compile(r'list\.txt')), b'example.org')
        self.assertIsNone(adapter.attachment(outer, {'wrong@example.org'}, re.compile(r'list\.txt')))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kit test ')
        self.base = Path(self.temp.name)
        self.source = self.base / 'source.txt'
        self.source.write_text('EXAMPLE.ORG\n192.0.2.1\n192.0.2.2\n')
        self.config = self.base / 'kit.ini'
        self.config.write_text('[kit]\nstate_dir=state\nlog_file=audit.jsonl\n'
            '[category:arbitrary-new-name]\n'
            'download=' + json.dumps([str(ROOT / 'helpers/download/local.sh'), str(self.source)]) + '\n'
            'bind_a=0.0.0.0\nbind_wildcard=0.0.0.0\nunbound_redirect=0.0.0.0\nroutes=true\n')

    def tearDown(self):
        self.temp.cleanup()

    def run_kit(self, *args, expected=0):
        env = dict(os.environ, KIT_PYTHON=sys.executable)
        proc = subprocess.run([str(ROOT / 'bin/kit-censura-ng'), '-c', str(self.config)] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
        self.assertEqual(proc.returncode, expected, proc.stderr)
        return proc

    def current(self):
        return (self.base / 'state/current').resolve()

    def test_generation_dns_stats_integrity(self):
        self.run_kit('run')
        current = self.current()
        self.assertIn('zone "example.org"', (current / 'named.conf').read_text())
        self.assertIn('local-data: "example.org 300 IN A 0.0.0.0"', (current / 'unbound.conf').read_text())
        self.assertIn('* IN A 0.0.0.0', (current / 'zones/db.arbitrary-new-name').read_text())
        manifest = json.loads((current / 'manifest.json').read_text())
        self.assertEqual(manifest['totals']['domains'], 1)
        self.assertEqual(manifest['totals']['route_prefixes'], 2)
        self.run_kit('verify')
        (current / 'named.conf').write_text('tampered')
        self.run_kit('verify', expected=1)

    def test_failed_update_keeps_snapshot_and_returns_degraded(self):
        self.run_kit('update')
        before = (self.current() / 'lists/arbitrary-new-name').read_text()
        self.source.write_text('<html>Server error</html>')
        self.run_kit('update', expected=2)
        self.assertEqual((self.current() / 'lists/arbitrary-new-name').read_text(), before)
        self.assertTrue(json.loads((self.current() / 'manifest.json').read_text())['degraded'])

    def test_first_failure_does_not_publish(self):
        self.source.unlink()
        self.run_kit('update', expected=1)
        self.assertFalse((self.base / 'state/current').exists())

    def test_empty_snapshot_rejected(self):
        self.run_kit('update')
        self.source.write_text('')
        self.run_kit('update', expected=2)
        self.assertEqual((self.current() / 'lists/arbitrary-new-name').read_text(), 'example.org\n')

    def test_config_change_blocks_apply(self):
        self.run_kit('update')
        self.config.write_text(self.config.read_text() + '\n# changed\n')
        self.run_kit('apply', expected=1)

    def test_rebuild_from_cached_data(self):
        self.run_kit('update')
        self.source.unlink()
        self.run_kit('build')
        self.run_kit('summary')

    def test_arbitrary_categories_and_duplicate_precedence(self):
        self.config.write_text(self.config.read_text() + '\n[category:second]\ndownload=' +
                              json.dumps([str(ROOT / 'helpers/download/local.sh'), str(self.source)]) +
                              '\nbind_a=192.0.2.5\n')
        self.run_kit('update')
        named = (self.current() / 'named.conf').read_text()
        self.assertEqual(named.count('zone "example.org"'), 1)
        self.assertIn('db.arbitrary-new-name', named)
        self.assertEqual(json.loads((self.current() / 'manifest.json').read_text())['totals']['domains'], 1)

    def test_missing_whitelist_and_child_conflict(self):
        self.config.write_text(self.config.read_text().replace('[kit]', '[kit]\nwhitelist_domains=allow.txt'))
        self.run_kit('update', expected=1)
        (self.base / 'allow.txt').write_text('www.example.org')
        self.run_kit('update', expected=1)

    def test_lock_excludes_second_run(self):
        with Lock(self.base / 'state'):
            self.run_kit('update', expected=1)

    def test_dry_run_does_not_call_upload(self):
        self.config.write_text(self.config.read_text() + '\n[upload:unbound]\nenabled=true\nservers=does-not-exist.invalid\nremote_root=/tmp/kit\nmain_config=/etc/unbound/unbound.conf\n')
        self.run_kit('--dry-run', 'run')
        events = [json.loads(x)['event'] for x in (self.base / 'audit.jsonl').read_text().splitlines()]
        self.assertIn('upload_planned', events)
        self.assertNotIn('dns_applied', events)

    def test_debug_does_not_log_command_arguments(self):
        self.config.write_text(self.config.read_text().replace(str(self.source), str(self.base / 'SECRET_PASSWORD')))
        self.run_kit('--debug', 'run', expected=1)
        self.assertNotIn('SECRET_PASSWORD', (self.base / 'audit.jsonl').read_text())

    def test_stale_limit(self):
        self.run_kit('update')
        raw = self.current() / 'raw/arbitrary-new-name.json'
        data = json.loads(raw.read_text())
        data['fetched_at'] = 1
        raw.write_text(json.dumps(data))
        self.config.write_text(self.config.read_text() + 'max_age_seconds=1\n')
        self.source.unlink()
        self.run_kit('update', expected=1)


if __name__ == '__main__':
    unittest.main()
