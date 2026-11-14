#!/usr/bin/env python3
"""Replay the actual NIC control response and send one explicitly labelled test."""
import json
import os
from pathlib import Path
import monitor
import notify


def verify():
    record = json.loads(Path('validation-prymax.json').read_text())
    fixture = Path('fixture-prymax.html').read_text()
    assert record['domain'] == 'prymax.cl' and record['test_only'] is True
    result = monitor.classify(fixture, 'http', 'prymax.cl')
    assert result['status'] == record['status'] == 'disponible'
    assert monitor.classify(fixture, 'http')['status'] == 'error_consulta'
    record['validation_run_id'] = os.environ.get('GITHUB_RUN_ID')
    record['validation_type'] = 'replay_of_real_http_response_no_additional_NIC_request'
    title, body = notify.message(record, None)
    title = '[PRUEBA PRYMAX.CL] ' + title
    body = ('**PRUEBA DE CONTROL: este correo trata de PRYMAX.CL, no de PRYMA.CL.**\n\n'
            'Se validó en Actions la respuesta HTTP real de NIC recibida a la hora indicada. '
            'Esta prueba no cambia el dominio vigilado ni su historial. '
            'La disponibilidad puede cambiar después de esa observación.\n\n'
            + body + '\n\nCuando PRYMA.CL produzca la misma señal, la misma plantilla usará '
            'el asunto **PRYMA.CL DISPONIBLE — revisar e inscribir en NIC Chile**.\n')
    return record, title, body


def main():
    record, title, body = verify()
    client = notify.GitHub(os.environ.get('GH_TOKEN'))
    key = notify.record_key(record)
    issue = client.find(key) or client.create(title, body)
    print(json.dumps({'control_domain': record['domain'], 'status': record['status'],
                      'nic_message': record['results'][0]['nic_message'],
                      'test_issue': issue['html_url'], 'production_domain': monitor.DOMAIN,
                      'NIC_request_in_this_run': False}, ensure_ascii=False))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write('## Prueba de control PRYMAX.CL\n\n' + title + '\n\n' + issue['html_url'] + '\n')


if __name__ == '__main__':
    main()
