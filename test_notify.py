import json
import tempfile
import unittest
from pathlib import Path

import notify as n


class FakeGitHub:
    def __init__(self):
        self.issues = []
        self.fail = False
        self.lost_response = False

    def find(self, key):
        return next((i for i in self.issues if f'pryma-alert:{key}' in i['body']), None)

    def create(self, title, body):
        if self.fail:
            raise OSError('Network unavailable')
        issue = {'title': title, 'body': body, 'html_url': f'https://example.test/issues/{len(self.issues) + 1}'}
        self.issues.append(issue)
        if self.lost_response:
            raise OSError('Response lost after successful creation')
        return issue


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'history').mkdir()
        self.history = self.root / 'history/2026-11.jsonl'
        self.client = FakeGitHub()
        self.counter = 0

    def append(self, status='en_eliminacion'):
        self.counter += 1
        record = {'domain': 'pryma.cl', 'status': status, 'queried': True,
                  'checked_at': f'2026-11-14T04:{self.counter:02}:00+00:00',
                  'time_cl': f'2026-11-14T01:{self.counter:02}:00-03:00',
                  'run_id': str(self.counter), 'mode': 'whois', 'results': []}
        with self.history.open('a') as f:
            f.write(json.dumps(record) + '\n')
        return record

    def runAlert(self):
        return n.run(self.root, self.client)

    def test_initial_test_is_not_availability_notice(self):
        self.append()
        self.runAlert()
        self.assertIn('[PRUEBA DE AVISO]', self.client.issues[0]['title'])
        self.assertNotIn('DISPONIBLE', self.client.issues[0]['title'])
        self.assertIn('@freyestech-png', self.client.issues[0]['body'])

    def test_same_status_and_reruns_send_no_duplicates(self):
        self.append(); self.runAlert()
        self.append(); self.runAlert(); self.runAlert()
        self.assertEqual(len(self.client.issues), 1)

    def test_available_alert_contains_time_source_and_registration_link(self):
        self.append(); self.runAlert()
        self.append('disponible'); self.runAlert()
        issue = self.client.issues[-1]
        self.assertIn('PRYMA.CL DISPONIBLE', issue['title'])
        self.assertNotIn('PRUEBA', issue['title'])
        self.assertIn('01:02:00-03:00', issue['body'])
        self.assertIn(n.URL, issue['body'])
        self.assertIn('https://www.nic.cl/', issue['body'])

    def test_initial_available_is_real_alert_not_test(self):
        self.append('disponible'); self.runAlert()
        self.assertIn('PRYMA.CL DISPONIBLE', self.client.issues[0]['title'])

    def test_prymax_control_uses_same_template_without_pryma_claim(self):
        import control_prymax
        record, title, body = control_prymax.verify()
        self.assertEqual(record['domain'], 'prymax.cl')
        self.assertTrue(title.startswith('[PRUEBA PRYMAX.CL] PRYMAX.CL DISPONIBLE'))
        self.assertIn('no de PRYMA.CL', body)
        self.assertIn('Whois.do?d=prymax.cl', body)
        self.assertNotIn('**pryma.cl no está registrado**', body)

    def test_production_history_refuses_control_domain(self):
        record = self.append('disponible')
        record['domain'] = 'prymax.cl'
        self.history.write_text(json.dumps(record) + '\n')
        with self.assertRaises(ValueError): self.runAlert()
        self.assertEqual(self.client.issues, [])

    def test_error_is_not_availability_and_recovery_is_reported(self):
        self.append(); self.runAlert()
        self.append('error_consulta'); self.runAlert()
        self.append('error_consulta'); self.runAlert()
        self.append('en_eliminacion'); self.runAlert()
        self.assertEqual(len(self.client.issues), 3)
        self.assertNotIn('DISPONIBLE', self.client.issues[1]['title'])

    def test_failed_delivery_remains_pending(self):
        self.append(); self.runAlert()
        self.append('disponible'); self.client.fail = True
        with self.assertRaises(OSError): self.runAlert()
        self.client.fail = False
        self.runAlert()
        self.assertEqual(len(self.client.issues), 2)
        self.assertIn('DISPONIBLE', self.client.issues[-1]['title'])

    def test_lost_response_after_creation_is_deduplicated(self):
        self.append(); self.client.lost_response = True
        with self.assertRaises(OSError): self.runAlert()
        self.client.lost_response = False
        self.runAlert()
        self.assertEqual(len(self.client.issues), 1)

    def test_pending_transient_availability_is_not_lost(self):
        self.append(); self.runAlert()
        self.append('disponible'); self.append('registrado')
        self.runAlert()
        self.assertEqual(len(self.client.issues), 3)
        self.assertIn('DISPONIBLE', self.client.issues[1]['title'])
        self.assertIn('Registrado', self.client.issues[2]['title'])

    def test_corrupt_cursor_fails_without_sending(self):
        self.append(); self.runAlert()
        (self.root / 'notifications.json').write_text('{}')
        with self.assertRaises(ValueError): self.runAlert()
        self.assertEqual(len(self.client.issues), 1)

    def test_unknown_status_fails_without_sending(self):
        self.append('unknown')
        with self.assertRaises(ValueError): self.runAlert()
        self.assertEqual(self.client.issues, [])


if __name__ == '__main__':
    unittest.main()
