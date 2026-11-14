#!/usr/bin/env python3
"""Notify the repository owner through GitHub issues. No extra NIC requests."""
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from monitor import DOMAIN, STATES, URL, atomic_json

REPO = 'freyestech-png/pryma-domain-monitor'
RECIPIENT = 'freyestech-png'
LABELS = {'disponible': 'DISPONIBLE', 'registrado': 'Registrado',
          'en_eliminacion': 'En eliminación', 'error_consulta': 'Error de consulta'}


def record_key(record):
    identity = [record['domain'], record['checked_at'], record.get('run_id'), record['status']]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def message(record, previous, initial=False):
    domain = record['domain']
    if domain not in (DOMAIN, 'prymax.cl'):
        raise ValueError('Unexpected notification domain')
    query_url = 'https://www.nic.cl/registry/Whois.do?d=' + domain
    status = record['status']
    key = record_key(record)
    if status == 'disponible':
        title = domain.upper() + ' DISPONIBLE — revisar e inscribir en NIC Chile'
        lead = (f'NIC Chile indicó explícitamente que **{domain} no está registrado**. '
                'Revisa la consulta y, si sigue disponible, inscríbelo ahora en NIC Chile. '
                'Este aviso no reserva el dominio ni garantiza que siga libre al abrirlo.')
    elif initial:
        title = f'[PRUEBA DE AVISO] PRYMA: vigilancia activada — {LABELS[status]}'
        lead = ('**Esta es una prueba del canal de avisos, no un anuncio de disponibilidad.** '
                'El estado real observado aparece abajo. Recibirás otro aviso si cambia.')
    elif status == 'error_consulta':
        title = 'PRYMA: error de consulta — disponibilidad desconocida'
        lead = ('No se pudo determinar el estado. **Un error no significa que esté disponible.** '
                'Revisa el historial y los registros de ejecución.')
    else:
        title = f'PRYMA: cambio de estado — {LABELS[status]}'
        lead = ('El estado del dominio cambió. **En eliminación no significa disponible.** '
                'Sólo se enviará el aviso de disponibilidad cuando NIC lo indique explícitamente.')
    run_id = str(record.get('run_id') or '')
    run_link = f'https://github.com/{REPO}/actions/runs/{run_id}' if run_id.isdigit() else f'https://github.com/{REPO}/actions'
    body = (f'@{RECIPIENT}\n\n{lead}\n\n'
            f'- Dominio: **{domain}**\n'
            f'- Estado anterior: **{LABELS.get(previous, "Inicio de vigilancia")}**\n'
            f'- Estado detectado: **{LABELS[status]}**\n'
            f'- Fecha y hora de Chile: **{record.get("time_cl", record["checked_at"])}**\n'
            f'- Consulta UTC: {record["checked_at"]}\n'
            f'- Método: {record.get("mode", "no informado")}\n'
            f'- Pausado por restricción: {"sí" if record.get("pause") else "no"}\n\n'
            f'[Consultar {domain} en NIC]({query_url}) · [Inscribir en NIC Chile](https://www.nic.cl/) · '
            f'[Ejecución y registros]({run_link})\n\n'
            'Resultado completo del monitor (sin datos personales del titular):\n\n'
            '```json\n' + json.dumps(record, ensure_ascii=False, indent=2) + '\n```\n\n'
            'Si el aviso llega tarde, verifica la fecha de observación y el estado actual en NIC. '
            'No se efectúan compras automáticas.\n\n'
            f'<!-- pryma-alert:{key} -->')
    return title, body


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError('Missing GitHub token')
        self.token = token

    def request(self, path, payload=None):
        req = urllib.request.Request('https://api.github.com/repos/' + REPO + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + self.token,
                     'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28',
                     'User-Agent': 'PRYMA-Domain-Monitor', 'Content-Type': 'application/json'})
        # Credentials must never follow a redirect to a different endpoint.
        from monitor import NoRedirect
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as response:
            return json.load(response)

    def find(self, key):
        marker = f'<!-- pryma-alert:{key} -->'
        for page in range(1, 11):
            query = urllib.parse.urlencode({'state': 'all', 'creator': 'github-actions[bot]',
                                            'per_page': 100, 'page': page})
            rows = self.request('/issues?' + query)
            for row in rows:
                if marker in (row.get('body') or '') and 'pull_request' not in row:
                    return row
            if len(rows) < 100:
                return None
        raise ValueError('Issue lookup limit reached; refusing possible duplicate')

    def create(self, title, body):
        # A mention already delivers email; assignment produced a second email in the live test.
        return self.request('/issues', {'title': title, 'body': body})


def run(state_dir='state', client=None):
    root = Path(state_dir)
    records = []
    for path in sorted((root / 'history').glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            record = json.loads(line)
            if record.get('domain') != DOMAIN or record.get('status') not in STATES or record.get('queried') is not True:
                raise ValueError('Invalid history record; refusing false alert')
            records.append(record)
    if not records:
        raise ValueError('No observed results available; cannot test notification')
    path = root / 'notifications.json'
    initial = not path.exists()
    state = {} if initial else json.loads(path.read_text(encoding='utf-8'))
    if initial:
        pending = records[-1:]
    else:
        if state.get('schema_version') != 1 or state.get('domain') != DOMAIN or state.get('last_status') not in STATES:
            raise ValueError('Invalid notification state; refusing reset')
        keys = [record_key(r) for r in records]
        if state.get('last_processed_key') not in keys:
            raise ValueError('Notification cursor missing from history')
        pending = records[keys.index(state['last_processed_key']) + 1:]
    sent = []
    for record in pending:
        if initial or record['status'] != state.get('last_status'):
            client = client or GitHub(os.environ.get('GH_TOKEN'))
            key = record_key(record)
            issue = client.find(key)
            if issue is None:
                issue = client.create(*message(record, state.get('last_status'), initial))
            state['last_issue_url'] = issue['html_url']
            sent.append(issue['html_url'])
        state.update(schema_version=1, domain=DOMAIN, last_processed_key=record_key(record),
                     last_status=record['status'])
        # Save only after delivery to GitHub; failed deliveries remain pending.
        atomic_json(path, state)
        initial = False
    return {'processed': len(pending), 'notifications': sent,
            'delivery': 'github_created_or_already_exists; email_receipt_not_proven'}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
