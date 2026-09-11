#!/usr/bin/env python3
"""Read-only IMAP attachment fetcher; configuration lives in the category section.

Fetch latest matching UID, including nested PEC MIME attachments. Never marks,
archives, deletes or acknowledges a message: those are separate operator actions.
"""
import argparse
import email
import imaplib
import os
import re
import socket
import ssl
import subprocess
import sys
from email.utils import getaddresses
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
from kit.config import Config


def attachment(message, senders, pattern):
    # Inspect nested message/rfc822 containers as well as ordinary messages.
    for container in message.walk():
        addresses = {addr.lower() for _, addr in getaddresses(container.get_all('From', []))}
        if not addresses.intersection(senders):
            continue
        for part in container.walk():
            filename = part.get_filename()
            if filename and pattern.fullmatch(filename):
                payload = part.get_payload(decode=True)
                if payload is not None:
                    return payload
    return None


def fetch(config, section):
    socket.setdefaulttimeout(config.integer(section, 'imap_timeout', 60, 1))
    password_env = config.get(section, 'imap_password_env')
    password = os.environ[password_env]
    senders = {x.lower() for x in config.get(section, 'imap_senders').split()}
    if not senders:
        raise ValueError('imap_senders required')
    pattern = re.compile(config.get(section, 'attachment_regex'))
    with imaplib.IMAP4_SSL(config.get(section, 'imap_host'),
                          config.integer(section, 'imap_port', 993, 1, 65535),
                          ssl_context=ssl.create_default_context()) as client:
        if client.login(config.get(section, 'imap_user'), password)[0] != 'OK':
            raise RuntimeError('IMAP login failed')
        if client.select(config.get(section, 'imap_folder', 'INBOX'), readonly=True)[0] != 'OK':
            raise RuntimeError('IMAP select failed')
        typ, data = client.uid('search', None, 'ALL')
        if typ != 'OK':
            raise RuntimeError('IMAP search failed')
        # Newest received full snapshot. UID order is explicit, never filename order.
        limit = config.integer(section, 'imap_max_messages', 1000, 1)
        for uid in reversed(data[0].split()[-limit:]):
            typ, response = client.uid('fetch', uid, '(BODY.PEEK[])')
            if typ != 'OK':
                raise RuntimeError('IMAP fetch failed')
            raw = b''.join(x[1] for x in response if isinstance(x, tuple))
            result = attachment(email.message_from_bytes(raw), senders, pattern)
            if result is not None:
                if config.boolean(section, 'gpg_decrypt'):
                    command = ['gpg', '--batch', '--decrypt']
                    home = config.path_value(section, 'gpg_home')
                    if home:
                        command[1:1] = ['--homedir', str(home)]
                    result = subprocess.run(command, input=result, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, check=True, timeout=60).stdout
                return result
    raise RuntimeError('No matching snapshot attachment')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('category')
    args = parser.parse_args()
    try:
        sys.stdout.buffer.write(fetch(Config(args.config), 'category:' + args.category))
    except Exception as error:
        print('PEC fetch failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
