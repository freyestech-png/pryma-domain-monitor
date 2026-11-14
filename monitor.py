#!/usr/bin/env python3
"""Read-only NIC Chile monitor. Python 3.10+ standard library; no credentials."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

DOMAIN = 'pryma.cl'
URL = 'https://www.nic.cl/registry/Whois.do?d=pryma.cl'
WHOIS_HOST = 'whois.nic.cl'
MAX_BYTES = 256_000
INTERVAL = 900
TIMEOUT = 20
STATES = {'disponible', 'registrado', 'en_eliminacion', 'error_consulta'}


def normalized(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', text)
                           if not unicodedata.combining(c)).casefold().split())


class Page(HTMLParser):
    """Extract visible text and result tables; ignore scripts, hidden CAPTCHA, forms."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.text = []
        self.tables = []
        self.current = None
        self.table_depth = 0
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        hidden = (self.hidden or tag in ('script', 'style', 'noscript', 'template', 'form')
                  or 'hidden' in a or a.get('aria-hidden') == 'true'
                  or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', a.get('style', ''), re.I))
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.stack.append((tag, self.hidden))
            self.hidden = bool(hidden)
        if tag == 'table':
            if self.current is not None:
                self.table_depth += 1
            elif not hidden and 'tablabusqueda' in a.get('class', '').split():
                self.current = []
                self.table_depth = 1

    def handle_endtag(self, tag):
        if tag == 'table' and self.current is not None:
            self.table_depth -= 1
            if not self.table_depth:
                self.tables.append(' '.join(self.current))
                self.current = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.hidden = self.stack[i][1]
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.current is not None:
                self.current.append(data)


def verdict(status, reason, **extra):
    return {'status': status, 'reason': reason, **extra}


def classify(raw, method):
    if method == 'http':
        page = Page()
        page.feed(raw)
        visible = normalized(' '.join(page.text))
        tables = [normalized(t) for t in page.tables]
        candidates = [t for t in tables if re.search(r'(?<![\w.-])pryma\.cl(?![\w.-])', t)]
        # One domain-specific table is mandatory. A query box or footer is not evidence.
        evidence = candidates[0] if len(candidates) == 1 else ''
    else:
        visible = normalized(raw)
        evidence = visible
    blocked = re.search(r'verify you are human|verifique que (?:usted )?es humano|access denied|'
                        r'too many requests|rate limit|query limit|exceso de consultas|'
                        r'limite de consultas|automated queries|access blocked', visible)
    if blocked:
        return verdict('error_consulta', 'access_restricted', pause=True)
    if method == 'http' and not evidence:
        if 'captcha' in visible or 'verificacion humana' in visible:
            return verdict('error_consulta', 'captcha_required', pause=True)
        return verdict('error_consulta', 'missing_or_ambiguous_domain_result')
    if method == 'whois':
        names = re.findall(r'^\s*Domain name:\s*(\S+)\s*$', raw, flags=re.M | re.I)
        if names and (len(names) != 1 or names[0].casefold() != DOMAIN):
            return verdict('error_consulta', 'domain_mismatch')
        bound = bool(names)
    else:
        bound = True
    deletion = (bool(re.search(r'este dominio esta en proceso de eliminacion|'
                              r'se puede restaurar hasta|pending\s*delete|redemption\s*period|'
                              r'status:\s*(?:pendingdelete|redemptionperiod)', evidence)))
    available = bool(re.search(r'nombre de dominio no existe|este dominio no esta registrado|'
                               r'(?:el )?dominio pryma\.cl no (?:esta registrado|existe)|'
                               r'pryma\.cl\s+(?:esta )?disponible', evidence))
    # Strict WHOIS negative: bind the explicit "no entries" message to this domain.
    if method == 'whois':
        available = bool(re.search(r'(?:^|\n)\s*(?:%+\s*)?(?:pryma\.cl:\s*no entries found\.?|'
                                   r'no entries found for\s+[\"\x27]?pryma\.cl[\"\x27]?\.?)\s*(?:\n|$)', raw, re.I))
    registered = (bound and (('registrar name:' in evidence and 'creation date:' in evidence)
                             if method == 'whois' else
                             ('titular' in evidence and ('agente registrador' in evidence or 'fecha de expiracion' in evidence))))
    if available and (registered or deletion):
        return verdict('error_consulta', 'conflicting_signals')
    if deletion and bound:
        return verdict('en_eliminacion', 'explicit_deletion_or_restoration')
    if available:
        return verdict('disponible', 'explicit_not_registered_confirm_manually')
    if registered:
        return verdict('registrado', 'domain_registration_record')
    return verdict('error_consulta', 'unrecognized_response')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Unexpected redirect', headers, fp)


def retry_seconds(value, now):
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        try:
            return max(0, int((parsedate_to_datetime(value) - now).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return 0


def probe(method, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    base = {'method': method, 'source': URL if method == 'http' else 'whois.nic.cl:43',
            'observed_at': now.isoformat(timespec='seconds')}
    start = time.monotonic()
    try:
        if method == 'http':
            req = urllib.request.Request(URL, headers={
                'User-Agent': 'PRYMA-Domain-Monitor/0.2 (single-domain, read-only)',
                'Accept': 'text/html', 'Cache-Control': 'no-cache'})
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=TIMEOUT) as response:
                base['http_status'] = response.status
                base['content_type'] = response.headers.get_content_type()
                if response.status != 200:
                    return {**base, **verdict('error_consulta', 'unexpected_http_status')}
                if base['content_type'] not in ('text/html', 'application/xhtml+xml'):
                    return {**base, **verdict('error_consulta', 'unexpected_content_type')}
                age = response.headers.get('Age', '0')
                if age.isdigit() and int(age) >= INTERVAL:
                    return {**base, **verdict('error_consulta', 'stale_http_cache')}
                data = response.read(MAX_BYTES + 1)
                charset = response.headers.get_content_charset() or 'utf-8'
        else:
            # No shell, referrals, proxy tunnelling or alternative hosts/IPs.
            with socket.create_connection((WHOIS_HOST, 43), timeout=TIMEOUT) as sock:
                sock.sendall((DOMAIN + '\r\n').encode('ascii'))
                data = bytearray()
                while len(data) <= MAX_BYTES:
                    remaining = TIMEOUT - (time.monotonic() - start)
                    if remaining <= 0:
                        raise TimeoutError('WHOIS deadline exceeded')
                    sock.settimeout(remaining)
                    chunk = sock.recv(min(4096, MAX_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                charset = 'utf-8'
        base.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if len(data) > MAX_BYTES:
            result = verdict('error_consulta', 'response_too_large')
        else:
            result = classify(data.decode(charset, errors='strict'), method)
        return {**base, **result, 'elapsed_ms': round((time.monotonic() - start) * 1000)}
    except urllib.error.HTTPError as exc:
        return {**base, **verdict('error_consulta', 'http_error'), 'http_status': exc.code,
                'pause': exc.code in (401, 403, 429),
                'retry_after_seconds': retry_seconds(exc.headers.get('Retry-After') if exc.headers else None, now)}
    except (OSError, urllib.error.URLError, ValueError, LookupError) as exc:
        # Exception class only: no response content, credentials or personal data in logs.
        return {**base, **verdict('error_consulta', 'transport_or_decode_error'),
                'error_type': type(exc).__name__, 'elapsed_ms': round((time.monotonic() - start) * 1000)}


def reconcile(results):
    good = [r for r in results if r['status'] != 'error_consulta']
    states = {r['status'] for r in good}
    if not good:
        return verdict('error_consulta', 'no_usable_method')
    if 'disponible' in states and len(states) > 1:
        return verdict('error_consulta', 'methods_disagree_on_availability')
    if 'en_eliminacion' in states:
        return verdict('en_eliminacion', 'explicit_deletion_or_restoration')
    return verdict(good[0]['status'], good[0]['reason'])


def next_state(previous, record, now):
    error = record['status'] == 'error_consulta'
    failures = previous.get('consecutive_errors', 0) + 1 if error else 0
    delay = min(86400, INTERVAL * 2 ** min(failures, 7)) if error else INTERVAL
    delay = max(delay, *(r.get('retry_after_seconds', 0) for r in record['results']))
    paused = previous.get('paused', False) or any(r.get('pause') for r in record['results'])
    return {'schema_version': 1, 'domain': DOMAIN, 'last_attempt_at': now.isoformat(),
            'next_allowed_at': (now + dt.timedelta(seconds=delay)).isoformat(),
            'consecutive_errors': failures, 'paused': paused,
            'last_status': record['status'],
            'last_good_status': previous.get('last_good_status') if error else record['status'],
            'last_good_at': previous.get('last_good_at') if error else now.isoformat()}


def load_state(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 1 or value.get('domain') != DOMAIN:
        raise ValueError('Invalid state; refusing to discard rate-limit history')
    if type(value.get('paused')) is not bool or type(value.get('consecutive_errors')) is not int:
        raise ValueError('Invalid state fields')
    for field in ('next_allowed_at', 'last_attempt_at'):
        stamp = dt.datetime.fromisoformat(value[field])
        if stamp.tzinfo is None:
            raise ValueError('State timestamps must have timezone')
    return value


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def run(mode, state_dir, output_dir, now=None, probe_fn=probe):
    now = now or dt.datetime.now(dt.timezone.utc)
    state_dir, output_dir = Path(state_dir), Path(output_dir)
    previous = load_state(state_dir / 'control.json')
    if previous.get('paused') or (previous.get('next_allowed_at') and
                                now < dt.datetime.fromisoformat(previous['next_allowed_at'])):
        skipped = {'domain': DOMAIN, 'checked_at': now.isoformat(), 'queried': False,
                   'reason': 'paused_by_restriction' if previous.get('paused') else 'cooldown',
                   'last_status': previous.get('last_status'), 'next_allowed_at': previous.get('next_allowed_at')}
        atomic_json(output_dir / 'result.json', skipped)
        return skipped
    methods = ('http', 'whois') if mode == 'compare' else (mode,)
    results = []
    for method in methods:
        results.append(probe_fn(method, now))
        # A site access restriction is not an invitation to switch transport.
        if results[-1].get('pause'):
            break
    record = {'schema_version': 1, 'domain': DOMAIN, 'queried': True,
              'checked_at': now.isoformat(timespec='seconds'),
              'time_cl': now.astimezone(ZoneInfo('America/Santiago')).isoformat(timespec='seconds'),
              'execution_environment': 'github_actions' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'local',
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'mode': mode, 'results': results,
              **reconcile(results)}
    record['changed'] = record['status'] != previous.get('last_status')
    record['pause'] = any(r.get('pause') for r in results)
    new_state = next_state(previous, record, now)
    # Reserve cooldown before other writes; corrupt state fails closed on next run.
    atomic_json(state_dir / 'control.json', new_state)
    history = state_dir / 'history' / (now.strftime('%Y-%m') + '.jsonl')
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    atomic_json(state_dir / 'latest.json', record)
    atomic_json(output_dir / 'result.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('http', 'whois', 'compare'), default='http')
    parser.add_argument('--state-dir', default='state')
    parser.add_argument('--output-dir', default='out')
    args = parser.parse_args()
    result = run(args.mode, args.state_dir, args.output_dir)
    print(json.dumps(result, ensure_ascii=False))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write('# PRYMA Domain Monitor\n\n```json\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\n```\n')
    return 2 if result.get('status') == 'error_consulta' or result.get('pause') else 0


if __name__ == '__main__':
    raise SystemExit(main())
