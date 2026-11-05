"""Check a pull request body against the team format, and turn a merged one into a release draft.

pull_request event: post one comment listing what the body misses, and delete it once the body is fixed.
It never fails the check, so it never blocks a merge.
push event (a merge into the release branch): if the PR says `release: feature` or `release: fix`,
create an UNPUBLISHED changelog post. A merge is not a deploy, so a person publishes it after the deploy.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.request

HEADINGS = ('What changes for users', 'Who gets it', 'How it works', 'Proof', 'Deploy and rollback')
RELEASES = {'feature': 'Feature', 'fix': 'Bug Fix', 'none': None}
MAX_WORDS = 150
CHECK_MARKER = '<!-- pr-body-check -->'
DRAFT_MARKER = '<!-- release-draft -->'
BOT = 'github-actions[bot]'  # comments by anyone else could fake a marker
SKIP_AUTHORS = ('dependabot[bot]',)

COMMENT = re.compile(r'<!--.*?-->', re.S)
MARKER = re.compile(r'<!--\s*(release|deploy):\s*(.*?)\s*-->')
NOT_PROSE = re.compile(r'```.*?```|<details>.*?</details>|<!--.*?-->|^#+ [^\n]*', re.S | re.M)


def parse(body):
    """Return ({heading: text without comments}, {'release': str | None, 'deploy': [str]})."""
    sections, current, fenced = {}, None, False
    for line in (body or '').splitlines():
        if line.lstrip().startswith('```'):
            fenced = not fenced
        if line.startswith('## ') and not fenced:
            current = line[3:].strip()
            sections[current] = []
        elif current:
            sections[current].append(line)
    sections = {h: COMMENT.sub('', '\n'.join(lines)).strip() for h, lines in sections.items()}
    markers = {'release': None, 'deploy': []}
    for key, value in MARKER.findall(body or ''):
        if key == 'deploy':
            markers['deploy'].append(value)
        else:
            markers['release'] = value
    return sections, markers


def problems(body):
    sections, markers = parse(body)
    out = []
    for h in HEADINGS:
        if h not in sections:
            out.append(f'Missing the `## {h}` heading.')
        elif not sections[h]:
            out.append(f'`## {h}` is empty.')
    if markers['release'] not in RELEASES:
        out.append('Add `<!-- release: feature -->`, `fix` or `none` at the end.')
    words = len(NOT_PROSE.sub(' ', body or '').split())
    if words > MAX_WORDS:
        out.append(f'{words} words outside code and `<details>`. Keep it to {MAX_WORDS}.')
    return out


def draft(body, tags):
    """The changelog post payload, or None when the PR is not a release."""
    sections, markers = parse(body)
    category = RELEASES.get(markers['release'] or 'none')
    lines = [ln.strip() for ln in sections.get(HEADINGS[0], '').splitlines() if ln.strip()]
    if not category or not lines:
        return None
    return {
        'title': lines[0],
        'subtitle': lines[1] if len(lines) > 1 else lines[0],
        'category': category,
        'tags': tags,
        'content': ''.join(f'<p>{html.escape(ln)}</p>' for ln in lines[1:] or lines),
        'is_published': False,
    }


def call(url, token, method='GET', data=None):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def bot_comment(api, token, n, marker):
    # ponytail: first 100 comments only, page through if a PR ever runs longer
    for c in call(f'{api}/issues/{n}/comments?per_page=100', token):
        if c['user']['login'] == BOT and marker in (c['body'] or ''):
            return c
    return None


def check(env, api, token, pr):
    if pr['user']['login'] in SKIP_AUTHORS:
        return
    found = problems(pr.get('body'))
    old = bot_comment(api, token, pr['number'], CHECK_MARKER)
    if not found:
        if old:
            call(old['url'], token, method='DELETE')
        print('PR body follows the format.')
        return
    text = '\n'.join(
        [CHECK_MARKER, 'This PR body misses parts of the team format:', '']
        + [f'- {p}' for p in found]
        + ['', 'The `pr-body` skill writes it for you. This comment goes away once the body is fixed.']
    )
    print(text)
    if old:
        call(old['url'], token, method='PATCH', data={'body': text})
    else:
        call(f'{api}/issues/{pr["number"]}/comments', token, method='POST', data={'body': text})


def release_draft(env, api, token):
    sha = env['GITHUB_SHA']
    prs = call(f'{api}/commits/{sha}/pulls', token)
    pr = next((p for p in prs if p.get('merged_at') and p.get('merge_commit_sha') == sha), None)
    if not pr:
        print(f'{sha[:9]} is no PR merge, so no release draft.')
        return
    post = draft(pr.get('body'), env.get('CHANGELOG_TAGS') or 'Platform')
    if not post:
        print(f'PR #{pr["number"]} is not a release, so no draft.')
        return
    if bot_comment(api, token, pr['number'], DRAFT_MARKER):  # a re-run must not post it twice
        print(f'PR #{pr["number"]} already has a release draft.')
        return
    # Marker first, so a re-run after a lost comment never posts twice; removed again if the POST fails.
    claim = call(
        f'{api}/issues/{pr["number"]}/comments',
        token,
        method='POST',
        data={'body': f'{DRAFT_MARKER}\nCreating the release draft.'},
    )
    try:
        created = call(env['CHANGELOG_URL'], env['CHANGELOG_KEY'], method='POST', data=post)
    except Exception:
        call(claim['url'], token, method='DELETE')
        raise
    text = (
        f'{DRAFT_MARKER}\nRelease draft {(created or {}).get("id", "?")} created, unpublished: '
        f'"{post["title"]}". It goes live on the changelog when someone publishes it after the deploy.'
    )
    call(claim['url'], token, method='PATCH', data={'body': text})
    print(text)


def main(env):
    api = f'{env.get("GITHUB_API_URL", "https://api.github.com")}/repos/{env["GITHUB_REPOSITORY"]}'
    token = env['GH_TOKEN']
    event = json.load(open(env['GITHUB_EVENT_PATH']))
    if env['GITHUB_EVENT_NAME'] == 'push':
        release_draft(env, api, token)
    elif event.get('pull_request'):
        try:
            check(env, api, token, event['pull_request'])
        except Exception as e:  # noqa: BLE001 - a warning bot must never block a merge
            print(f'::warning::pr-body check could not run: {e}')


if __name__ == '__main__':
    main(os.environ)
