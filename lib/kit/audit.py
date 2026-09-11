"""Append-only JSON lines, UTC timestamps and run IDs; no shell tracing/secrets."""
import datetime
import hashlib
import json
import os
import socket
import sys


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


class Audit:
    def __init__(self, path, run_id, debug=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open('a', encoding='utf-8')
        self.run_id, self.debug = run_id, debug

    def emit(self, event, level='INFO', **fields):
        if level == 'DEBUG' and not self.debug:
            return
        record = dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      run_id=self.run_id, host=socket.gethostname(), event=event, level=level)
        record.update(fields)
        self.stream.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())
        print('%s %s %s' % (record['time'], level, event), file=sys.stderr)

    def close(self):
        self.stream.close()
