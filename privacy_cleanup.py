#!/usr/bin/env python3
"""Authorized author-email cleanup; preserve every file tree and use a push lease."""
import argparse
import json
import os
import re
import subprocess

OWNER_NAME = b'Felipe Reyes'
PRIVATE_ALIAS = b'282397050+freyestech-png@users.noreply.github.com'
ALLOWED_EMAILS = {PRIVATE_ALIAS, b'41898282+github-actions[bot]@users.noreply.github.com', b'noreply@github.com'}


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data)


def rewrite():
    old_head = git('rev-parse', 'origin/main').decode().strip()
    commits = git('rev-list', '--reverse', old_head).decode().split()
    mapping = {}
    changed_authors = 0
    for sha in commits:
        header, body = git('cat-file', 'commit', sha).split(b'\n\n', 1)
        lines = []
        discard = False
        for line in header.split(b'\n'):
            if line.startswith(b' '):
                if not discard:
                    lines.append(line)
                continue
            discard = line.startswith((b'gpgsig ', b'gpgsig-sha256 '))
            if discard:
                continue  # An original signature is invalid after changing commit metadata.
            if line.startswith(b'parent '):
                line = b'parent ' + mapping[line[7:].decode()].encode()
            if line.startswith((b'author ', b'committer ')):
                match = re.fullmatch(rb'(author|committer) (.*?) <([^<>]+)>(.*)', line)
                if not match:
                    raise ValueError('Unrecognized commit identity')
                kind, name, address, rest = match.groups()
                if address not in ALLOWED_EMAILS:
                    if name != OWNER_NAME:
                        raise ValueError('Unexpected author; stop without publishing')
                    changed_authors += int(kind == b'author')
                    line = kind + b' ' + name + b' <' + PRIVATE_ALIAS + b'>' + rest
            lines.append(line)
        cleaned = b'\n'.join(lines) + b'\n\n' + body
        fresh = git('hash-object', '-t', 'commit', '-w', '--stdin', data=cleaned).decode().strip()
        if git('show', '-s', '--format=%T', sha) != git('show', '-s', '--format=%T', fresh):
            raise ValueError('File tree changed; stop without publishing')
        mapping[sha] = fresh
    if changed_authors not in (0, 7):
        raise ValueError('Expected exactly seven author entries or an already-clean history')
    new_head = mapping[old_head] if changed_authors else old_head
    emails = set(git('log', new_head, '--format=%ae%n%ce').splitlines())
    if not emails <= ALLOWED_EMAILS:
        raise ValueError('Unexpected email remains; stop without publishing')
    return {'old_head': old_head, 'new_head': new_head, 'commits_verified': len(commits),
            'author_entries_cleaned': changed_authors, 'all_file_trees_unchanged': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = rewrite()
    if args.apply:
        if os.environ.get('PRIVACY_REWRITE_AUTHORIZED') != 'true':
            raise ValueError('Explicit authorization flag required')
        refs = git('ls-remote', '--heads', '--tags', 'origin').decode().splitlines()
        if len(refs) != 1 or refs[0].split()[1] != 'refs/heads/main':
            raise ValueError('Unexpected remote branches or tags; stop without overwriting')
        if refs[0].split()[0] != report['old_head']:
            raise ValueError('Remote changed since checkout; stop without overwriting')
        if report['author_entries_cleaned']:
            git('push', '--force-with-lease=refs/heads/main:' + report['old_head'],
                'origin', report['new_head'] + ':refs/heads/main')
        current = git('ls-remote', 'origin', 'refs/heads/main').decode().split()[0]
        if current != report['new_head']:
            raise ValueError('Remote verification failed')
        report['published_and_verified'] = True
    else:
        report['published_and_verified'] = False
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write('## Limpieza de autoría\n\n```json\n' + output + '\n```\n')


if __name__ == '__main__':
    main()
