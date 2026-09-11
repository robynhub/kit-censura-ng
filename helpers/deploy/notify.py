#!/usr/bin/env python3
"""Optional SMTP notification hook, configured entirely in [hooks]."""
import datetime
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
from kit.config import Config


def main():
    config = Config(sys.argv[1])
    generation = Path(sys.argv[2])
    manifest = json.loads((generation / 'manifest.json').read_text(encoding='utf-8'))
    section = 'hooks'
    message = EmailMessage()
    message['From'] = config.get(section, 'smtp_from')
    recipients = config.get(section, 'smtp_to').split()
    if not recipients:
        raise ValueError('smtp_to is empty')
    message['To'] = ', '.join(recipients)
    message['Subject'] = config.get(section, 'smtp_subject', 'kit-censura-ng: application completed')
    body = config.get(section, 'smtp_body', 'Configured deployments completed for generation {run_id}.\nDomains: {domains}\nIP prefixes: {ip_prefixes}\nUTC: {time}')
    values = dict(manifest['totals'], run_id=manifest['run_id'],
                  time=datetime.datetime.now(datetime.timezone.utc).isoformat())
    for key, value in values.items():
        body = body.replace('{' + key + '}', str(value))
    message.set_content(body)
    host = config.get(section, 'smtp_host')
    mode = config.get(section, 'smtp_tls', 'ssl')
    if mode not in ('ssl', 'starttls'):
        raise ValueError('smtp_tls must be ssl or starttls')
    port = config.integer(section, 'smtp_port', 465 if mode == 'ssl' else 587, 1, 65535)
    context = ssl.create_default_context()
    connection = (smtplib.SMTP_SSL(host, port, timeout=30, context=context) if mode == 'ssl'
                  else smtplib.SMTP(host, port, timeout=30))
    with connection as smtp:
        if mode == 'starttls':
            smtp.starttls(context=context)
        user = config.get(section, 'smtp_user')
        if user:
            smtp.login(user, os.environ[config.get(section, 'smtp_password_env')])
        if smtp.send_message(message, to_addrs=recipients):
            raise RuntimeError('One or more recipients refused')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('SMTP notification failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
