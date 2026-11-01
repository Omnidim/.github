"""Sort a pull request into a review tier: low, standard or high.

Each signal can only raise the tier:
1. Paths. Any changed file matching the repo's .github/review-risk-paths is high, and so is an outside author.
2. Size. Over max_lines changed lines, lockfiles aside, is standard.
3. The OpenCode review verdict. Findings, or no finished review of the head commit, make it standard,
   so a broken or slow review never lets a PR through.
"""

from __future__ import annotations

import fnmatch
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TIERS = ('low', 'standard', 'high')
RULES_FILE = '.github/review-risk-paths'
AI_MARKER = '<!-- opencode-review -->'
MEMBERS = ('OWNER', 'MEMBER', 'COLLABORATOR')
TRUSTED_BOTS = ('dependabot[bot]',)
# Matches the OpenCode review action, so "not reviewed" and "nothing to review" agree.
CODE = ('py js jsx mjs cjs ts tsx go rs java kt rb php cs c h cc cpp hpp swift scala sh').split()
GENERATED = (
    'package-lock.json npm-shrinkwrap.json yarn.lock pnpm-lock.yaml bun.lock bun.lockb poetry.lock '
    'uv.lock Pipfile.lock Cargo.lock go.sum Gemfile.lock composer.lock *.po *.pot *.min.js *.min.css *.map'
).split()
TEST_PATTERNS = ('*/tests/*', '*/__tests__/*', '*/test_*.py', '*.test.*', '*.spec.*')  # with _match's leading /


def parse_rules(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith('#')]


def _match(path, pattern):
    # fnmatch's * also crosses "/", so "**/x/**" means "any x folder"; the leading "/" lets it match at the root.
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase('/' + path, pattern)


def _any(path, patterns):
    return any(_match(path, p) for p in patterns)


def _generated(path):
    return _any(path.rsplit('/', 1)[-1], GENERATED)


def _code(path):
    return path.rsplit('.', 1)[-1] in CODE and not _generated(path)


def ai_verdict(comment_bodies, head_sha, files):
    """clean, findings, missing (no finished review of this commit) or not_needed (no code changed)."""
    if not any(_code(f['path']) for f in files):
        return 'not_needed'
    for body in reversed(comment_bodies):
        if AI_MARKER not in body:
            continue
        if f'review of {head_sha[:9]}' not in body:
            return 'missing'
        if 'Nothing blocking found' in body:
            return 'clean'
        if 'Changes needed' in body:
            return 'findings'
        return 'missing'
    return 'missing'


def decide(files, rules, author_assoc, author_login, ai, max_lines):
    """Return (tier, reasons)."""
    level, reasons = 0, []

    def raise_to(t, why):
        nonlocal level
        level = max(level, TIERS.index(t))
        reasons.append(f'{t}: {why}')

    if author_assoc not in MEMBERS and author_login not in TRUSTED_BOTS:
        raise_to('high', f'author {author_login} is outside the team')
    for f in files:
        p = f['path']
        if p == RULES_FILE or (_any(p, rules) and not _any(p, TEST_PATTERNS)):
            raise_to('high', f'changes `{p}`')
    lines = sum(f['changes'] for f in files if not _generated(f['path']))
    if lines > max_lines:
        raise_to('standard', f'{lines} changed lines, over {max_lines}')
    if ai == 'findings':
        raise_to('standard', 'the AI review found something to fix')
    elif ai == 'missing':
        raise_to('standard', 'no finished AI review of the head commit')
    return TIERS[level], reasons


class GitHub:
    def __init__(self, api, repo, token):
        self.base, self.token = f'{api}/repos/{repo}', token

    def call(self, path, method='GET', data=None, accept='application/vnd.github+json'):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': f'Bearer {self.token}', 'Accept': accept},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        return raw if accept.endswith('raw') else (json.loads(raw) if raw else None)

    def pages(self, path):
        out, page = [], 1
        while True:
            batch = self.call(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
            out += batch
            if len(batch) < 100 or page >= 30:
                return out
            page += 1


def main(env):
    event = json.load(open(env['GITHUB_EVENT_PATH']))
    pr = event.get('pull_request')
    if not pr:
        print('Not a pull request event, nothing to do.')
        return
    gh = GitHub(env.get('GITHUB_API_URL', 'https://api.github.com'), env['GITHUB_REPOSITORY'], env['GH_TOKEN'])
    n, head = pr['number'], pr['head']['sha']
    files = [{'path': f['filename'], 'changes': f['changes']} for f in gh.pages(f'/pulls/{n}/files')]
    try:  # from the base branch, so a PR cannot loosen its own rules
        raw = gh.call(f'/contents/{RULES_FILE}?ref={pr["base"]["sha"]}', accept='application/vnd.github.raw')
        rules = parse_rules(raw.decode())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        rules = []
    comments = [c['body'] or '' for c in gh.pages(f'/issues/{n}/comments')]
    ai = ai_verdict(comments, head, files)
    tier, reasons = decide(
        files,
        rules,
        pr.get('author_association', ''),
        pr['user']['login'],
        ai,
        int(env.get('RISK_MAX_LINES') or 400),
    )
    label = f'risk: {tier}'
    for t in TIERS:
        if f'risk: {t}' != label and any(lb['name'] == f'risk: {t}' for lb in pr.get('labels', [])):
            gh.call(f'/issues/{n}/labels/{urllib.parse.quote(f"risk: {t}")}', method='DELETE')
    gh.call(f'/issues/{n}/labels', method='POST', data={'labels': [label]})

    summary = [f'## Review tier: {tier}', '', f'AI review: {ai}.', '']
    summary += [f'- {r}' for r in reasons] or ['- nothing raised it']
    print('\n'.join(summary))
    if env.get('GITHUB_STEP_SUMMARY'):
        with open(env['GITHUB_STEP_SUMMARY'], 'a') as fh:
            fh.write('\n'.join(summary) + '\n')
    if env.get('GITHUB_OUTPUT'):
        with open(env['GITHUB_OUTPUT'], 'a') as fh:
            fh.write(f'tier={tier}\n')


if __name__ == '__main__':
    main(os.environ)
