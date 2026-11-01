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
# Test folders only: a module named test_*.py can be a real route.
TEST_PATTERNS = ('*/tests/*', '*/__tests__/*', '*.test.*', '*.spec.*')  # with _match's leading /
AI_AUTHOR = 'github-actions[bot]'  # the review posts with the job token; anyone else could fake it
MAX_FILES = 3000  # the PR files API stops here


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


def ai_verdict(comments, head_sha, files):
    """clean, findings, missing (no finished review of this commit) or not_needed (no code changed).
    `comments` is (author login, body) pairs, oldest first."""
    if not any(_code(f['path']) for f in files):
        return 'not_needed'
    for login, body in reversed(comments):
        if login != AI_AUTHOR or AI_MARKER not in body:
            continue
        if f'review of {head_sha[:9]}' not in body:
            return 'missing'
        status = body.split(AI_MARKER, 1)[1].strip().split('\n', 1)[0]  # the line under the marker
        if status.startswith('Nothing blocking found'):
            return 'clean'
        if status.startswith('Changes needed'):
            return 'findings'
        return 'missing'
    return 'missing'


def decide(files, rules, author_assoc, author_login, ai, max_lines):
    """Return (tier, reasons). `rules` is None when the base branch has no rules file."""
    level, reasons = 0, []

    def raise_to(t, why):
        nonlocal level
        level = max(level, TIERS.index(t))
        reasons.append(f'{t}: {why}')

    if author_assoc not in MEMBERS and author_login not in TRUSTED_BOTS:
        raise_to('high', f'author {author_login} is outside the team')
    if len(files) >= MAX_FILES:
        raise_to('high', f'{MAX_FILES} or more files, so the list may be cut off')
    if rules is None:
        raise_to('standard', f'the base branch has no {RULES_FILE}')
    for f in files:
        for p in filter(None, (f['path'], f.get('previous'))):  # a rename out of a risky folder counts
            if p == RULES_FILE or (_any(p, rules or []) and not _any(p, TEST_PATTERNS)):
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


def set_label(gh, n, tier):
    """Leave exactly one risk label. Reads the live labels: the event's copy is stale on a re-run."""
    for lb in gh.call(f'/issues/{n}/labels'):
        if lb['name'].startswith('risk: ') and lb['name'] != f'risk: {tier}':
            try:
                gh.call(f'/issues/{n}/labels/{urllib.parse.quote(lb["name"])}', method='DELETE')
            except urllib.error.HTTPError as e:
                if e.code != 404:  # already gone
                    raise
    gh.call(f'/issues/{n}/labels', method='POST', data={'labels': [f'risk: {tier}']})


def main(env):
    event = json.load(open(env['GITHUB_EVENT_PATH']))
    pr = event.get('pull_request')
    if not pr:
        print('Not a pull request event, nothing to do.')
        return
    gh = GitHub(env.get('GITHUB_API_URL', 'https://api.github.com'), env['GITHUB_REPOSITORY'], env['GH_TOKEN'])
    n, head = pr['number'], pr['head']['sha']
    files = [
        {'path': f['filename'], 'previous': f.get('previous_filename'), 'changes': f['changes']}
        for f in gh.pages(f'/pulls/{n}/files')
    ]
    try:  # from the base branch, so a PR cannot loosen its own rules
        raw = gh.call(f'/contents/{RULES_FILE}?ref={pr["base"]["sha"]}', accept='application/vnd.github.raw')
        rules = parse_rules(raw.decode())
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        rules = None
    comments = [(c['user']['login'], c['body'] or '') for c in gh.pages(f'/issues/{n}/comments')]
    ai = ai_verdict(comments, head, files)
    tier, reasons = decide(
        files,
        rules,
        pr.get('author_association', ''),
        pr['user']['login'],
        ai,
        int(env.get('RISK_MAX_LINES') or 400),
    )
    set_label(gh, n, tier)

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
    try:
        main(os.environ)
    except Exception:
        # Fail closed: a label left from an older commit must not stand for this one.
        event = json.load(open(os.environ['GITHUB_EVENT_PATH']))
        if event.get('pull_request'):
            gh = GitHub(
                os.environ.get('GITHUB_API_URL', 'https://api.github.com'),
                os.environ['GITHUB_REPOSITORY'],
                os.environ['GH_TOKEN'],
            )
            try:
                set_label(gh, event['pull_request']['number'], 'standard')
            except Exception as e:  # noqa: BLE001 - e.g. a read-only token; the error below says enough
                print(f'Could not set the fallback label: {e}')
        raise
