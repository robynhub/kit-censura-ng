"""INI configuration: data, never shell code. Paths are relative to the INI."""
import configparser
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')


def argv(value):
    result = json.loads(value)
    if not isinstance(result, list) or not all(isinstance(x, str) for x in result):
        raise ValueError('Commands must be JSON arrays of strings')
    return result


class Config:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.base = self.path.parent
        self.ini = configparser.ConfigParser(interpolation=None)
        with self.path.open(encoding='utf-8') as stream:
            self.ini.read_file(stream)
        if self.ini.defaults():
            raise ValueError('[DEFAULT] is unsupported; use [kit] and category sections')
        self.categories = []
        for section in self.ini.sections():
            if section.startswith('category:'):
                name = section.split(':', 1)[1]
                if not NAME.fullmatch(name):
                    raise ValueError('Invalid category name')
                if self.boolean(section, 'enabled', True):
                    self.categories.append((name, section))
            elif section not in ('kit', 'dns', 'routes', 'upload:bind', 'upload:unbound', 'hooks'):
                raise ValueError('Unknown section: ' + section)
        if not self.categories:
            raise ValueError('Configure at least one enabled category')
        self.state = self.path_value('kit', 'state_dir', 'state')
        self.log = self.path_value('kit', 'log_file', 'state/audit.jsonl')
        for name, section in self.categories:
            for key in ('download', 'parser'):
                command = self.get(section, key)
                if key == 'download' and not command:
                    raise ValueError(section + ': download is required')
                if command:
                    argv(command)
            for key in ('bind_a', 'bind_aaaa', 'bind_wildcard', 'unbound_redirect'):
                if '\n' in self.get(section, key):
                    raise ValueError('DNS values must be single-line')
        if self.get('kit', 'on_failure', 'keep') not in ('keep', 'abort'):
            raise ValueError('on_failure must be keep or abort')

    def get(self, section, key, default=''):
        return self.ini.get(section, key, fallback=default)

    def boolean(self, section, key, default=False):
        return self.ini.getboolean(section, key, fallback=default)

    def integer(self, section, key, default, minimum=0, maximum=2147483647):
        value = self.ini.getint(section, key, fallback=default)
        if not minimum <= value <= maximum:
            raise ValueError('%s.%s out of range' % (section, key))
        return value

    def path_value(self, section, key, default=''):
        value = self.get(section, key, default)
        if not value:
            return None
        path = Path(value.replace('{root}', str(ROOT)))
        return path if path.is_absolute() else self.base / path

    def command(self, section, key, values):
        command = argv(self.get(section, key, '[]'))
        # Replace known tokens only: braces in regexes or scripts remain literal.
        substitutions = dict(python=sys.executable, root=str(ROOT), config=str(self.path), base=str(self.base))
        substitutions.update(values)
        for token, value in substitutions.items():
            command = [arg.replace('{' + token + '}', str(value)) for arg in command]
        return command
