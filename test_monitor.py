import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import monitor as m

NOW = dt.datetime(2026, 11, 14, 4, tzinfo=dt.timezone.utc)


def table(text, domain='pryma.cl'):
    return f'<table class="tablabusqueda"><tr><td>{domain}</td></tr><tr><td>{text}</td></tr></table>'


class ClassificationTests(unittest.TestCase):
    def assertStatus(self, text, status, method='http'):
        self.assertEqual(m.classify(text, method)['status'], status)

    def test_real_deletion_fixture(self):
        raw = (Path(__file__).parent / 'fixture-deletion.html').read_text()
        self.assertStatus(raw, 'en_eliminacion')

    def test_restoration(self):
        self.assertStatus(table('Se puede restaurar hasta 2026-11-12'), 'en_eliminacion')

    def test_registered(self):
        self.assertStatus(table('Titular: Ejemplo Agente Registrador: NIC Chile'), 'registrado')

    def test_available(self):
        self.assertStatus(table('Nombre de dominio no existe'), 'disponible')

    def test_available_accents_entities(self):
        self.assertStatus(table('Este dominio no est&aacute; registrado'), 'disponible')

    def test_available_explicit_name(self):
        self.assertStatus(table('El dominio pryma.cl no existe'), 'disponible')

    def test_conflicting_signals(self):
        self.assertStatus(table('Nombre de dominio no existe Titular: Ejemplo Agente Registrador: NIC Chile'), 'error_consulta')

    def test_empty_and_unrecognized_are_errors(self):
        for raw in ('', '<html>NIC Chile</html>', table('Formato nuevo')):
            with self.subTest(raw=raw): self.assertStatus(raw, 'error_consulta')

    def test_query_field_is_not_domain_evidence(self):
        self.assertStatus('<input value="pryma.cl"><div>Nombre de dominio no existe</div>', 'error_consulta')

    def test_wrong_domain(self):
        self.assertStatus(table('Nombre de dominio no existe', 'otra.cl'), 'error_consulta')

    def test_domain_substring(self):
        self.assertStatus(table('Nombre de dominio no existe', 'no-pryma.cl'), 'error_consulta')

    def test_two_result_tables_are_ambiguous(self):
        self.assertStatus(table('Nombre de dominio no existe') * 2, 'error_consulta')

    def test_scripts_and_hidden_text_cannot_claim_availability(self):
        for tag in ('script', 'style', 'template'):
            self.assertStatus(table(f'<{tag}>Nombre de dominio no existe</{tag}>'), 'error_consulta')
        self.assertStatus(table('<div style="display:none">Nombre de dominio no existe</div>'), 'error_consulta')

    def test_captcha_challenge_pauses(self):
        self.assertTrue(m.classify('<p>Verify you are human</p>', 'http')['pause'])

    def test_captcha_library_alone_does_not_block_result(self):
        self.assertStatus('<script src="captcha.js"></script>' + table('Este dominio está en proceso de eliminación.'), 'en_eliminacion')

    def test_access_denied_overrides_domain_text(self):
        result = m.classify('<p>Access denied</p>' + table('Nombre de dominio no existe'), 'http')
        self.assertEqual(result['status'], 'error_consulta')
        self.assertTrue(result['pause'])

    def test_whois_registered(self):
        self.assertStatus('Domain name: pryma.cl\nRegistrar name: NIC Chile\nCreation date: 2020-01-01', 'registrado', 'whois')

    def test_whois_wrong_domain(self):
        self.assertStatus('Domain name: otra.cl\nRegistrar name: NIC Chile\nCreation date: 2020', 'error_consulta', 'whois')

    def test_whois_deletion(self):
        self.assertStatus('Domain name: pryma.cl\nStatus: pendingDelete', 'en_eliminacion', 'whois')

    def test_whois_negative_must_name_domain(self):
        for raw in ('pryma.cl: no entries found.', '%% No entries found for "pryma.cl".'):
            self.assertStatus(raw, 'disponible', 'whois')
        for raw in ('No entries found.', 'otra.cl: no entries found.', 'Error pryma.cl: no entries found.'):
            self.assertStatus(raw, 'error_consulta', 'whois')

    def test_methods_availability_disagreement(self):
        results = [m.verdict('disponible', 'a'), m.verdict('registrado', 'b')]
        self.assertEqual(m.reconcile(results)['status'], 'error_consulta')

    def test_deletion_is_more_specific_than_registered(self):
        results = [m.verdict('registrado', 'a'), m.verdict('en_eliminacion', 'b')]
        self.assertEqual(m.reconcile(results)['status'], 'en_eliminacion')

    def test_one_transport_failure_does_not_erase_evidence(self):
        results = [m.verdict('en_eliminacion', 'a'), m.verdict('error_consulta', 'b')]
        self.assertEqual(m.reconcile(results)['status'], 'en_eliminacion')


class TransportTests(unittest.TestCase):
    def test_http_429_and_retry_after(self):
        headers = Message(); headers['Retry-After'] = '3600'
        err = urllib.error.HTTPError(m.URL, 429, 'Too many', headers, io.BytesIO())
        with patch('urllib.request.OpenerDirector.open', side_effect=err):
            result = m.probe('http', NOW)
        self.assertEqual(result['http_status'], 429)
        self.assertEqual(result['retry_after_seconds'], 3600)
        self.assertTrue(result['pause'])

    def test_no_redirect_following(self):
        with self.assertRaises(urllib.error.HTTPError):
            m.NoRedirect().redirect_request(urllib.request.Request(m.URL), None, 302, '', Message(), 'https://example.com')

    def test_retry_after_date(self):
        self.assertEqual(m.retry_seconds('Sat, 14 Nov 2026 05:00:00 GMT', NOW), 3600)
        self.assertEqual(m.retry_seconds('bad', NOW), 0)

    def test_dns_failure_is_error(self):
        with patch('socket.create_connection', side_effect=m.socket.gaierror()):
            result = m.probe('whois', NOW)
        self.assertEqual(result['status'], 'error_consulta')
        self.assertEqual(result['error_type'], 'gaierror')

    def test_partial_whois_then_timeout_is_not_available(self):
        with patch('socket.create_connection') as create:
            sock = create.return_value.__enter__.return_value
            sock.recv.side_effect = [b'pryma.cl: no entries found.\n', TimeoutError()]
            self.assertEqual(m.probe('whois', NOW)['status'], 'error_consulta')


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state, self.out = self.root / 'state', self.root / 'out'
        self.calls = []

    def good(self, method, now):
        self.calls.append(method)
        return {'method': method, **m.verdict('en_eliminacion', 'explicit_deletion_or_restoration')}

    def runMonitor(self, now=NOW, mode='http', fn=None):
        return m.run(mode, self.state, self.out, now, fn or self.good)

    def test_history_appends_and_state_survives(self):
        self.runMonitor()
        self.runMonitor(NOW + dt.timedelta(minutes=15))
        rows = (self.state / 'history/2026-11.jsonl').read_text().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertFalse(json.loads(rows[1])['changed'])
        self.assertEqual(m.load_state(self.state / 'control.json')['last_good_status'], 'en_eliminacion')

    def test_early_run_makes_no_network_call(self):
        self.runMonitor()
        r = self.runMonitor(NOW + dt.timedelta(minutes=14))
        self.assertFalse(r['queried'])
        self.assertEqual(self.calls, ['http'])

    def test_no_fallback_after_restriction(self):
        def blocked(method, now):
            self.calls.append(method)
            return {'method': method, **m.verdict('error_consulta', 'restricted', pause=True)}
        self.runMonitor(mode='compare', fn=blocked)
        self.assertEqual(self.calls, ['http'])
        r = self.runMonitor(NOW + dt.timedelta(days=2))
        self.assertFalse(r['queried'])
        self.assertEqual(r['reason'], 'paused_by_restriction')

    def test_error_preserves_last_good_and_backs_off(self):
        self.runMonitor()
        self.runMonitor(NOW + dt.timedelta(minutes=15), fn=lambda method, now: m.verdict('error_consulta', 'timeout'))
        state = m.load_state(self.state / 'control.json')
        self.assertEqual(state['last_good_status'], 'en_eliminacion')
        self.assertEqual(state['last_status'], 'error_consulta')
        self.assertEqual(state['next_allowed_at'], (NOW + dt.timedelta(minutes=45)).isoformat())

    def test_corrupt_state_fails_before_network(self):
        self.state.mkdir()
        (self.state / 'control.json').write_text('{broken')
        with self.assertRaises(ValueError): self.runMonitor()
        self.assertEqual(self.calls, [])

    def test_wrong_domain_state_fails_closed(self):
        self.state.mkdir()
        (self.state / 'control.json').write_text('{"schema_version": 1, "domain": "otra.cl"}')
        with self.assertRaises(ValueError): self.runMonitor()

    def test_compare_records_both_methods(self):
        self.runMonitor(mode='compare')
        self.assertEqual(self.calls, ['http', 'whois'])

    def test_retry_after_is_not_capped_by_local_backoff(self):
        record = {'status': 'error_consulta', 'results': [{'retry_after_seconds': 172800}]}
        state = m.next_state({}, record, NOW)
        self.assertEqual(state['next_allowed_at'], (NOW + dt.timedelta(days=2)).isoformat())


if __name__ == '__main__':
    unittest.main()
