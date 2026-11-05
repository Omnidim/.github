"""Run: python3 -m unittest discover -s pr-body"""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from pr_body import HEADINGS, main, parse, problems, release_post

GOOD = """## What changes for users
Agents can push call results to Salesforce.
Before, only HubSpot was supported.

## Who gets it
Direct customers and resellers with Workflows. Post-call webhooks are unchanged.

## How it works
```
call ends -> post_call -> salesforce_sync(contact, summary)
```

## Proof
Staging call 81234 created a contact. Not proven: sandbox orgs.

## Deploy and rollback
-u omni_assistant, then set the client id. Roll back by uninstalling the app.

<!-- release: feature -->
<!-- deploy: -u omni_assistant -->
<!-- deploy: param salesforce.oauth_client_id -->
"""


class Parse(unittest.TestCase):
    def test_reads_sections_and_every_deploy_marker(self):
        sections, markers = parse(GOOD)
        self.assertIn('Who gets it', sections)
        self.assertEqual(markers['release'], 'feature')
        self.assertEqual(markers['deploy'], ['-u omni_assistant', 'param salesforce.oauth_client_id'])


class Template(unittest.TestCase):
    def test_untouched_template_warns_on_every_heading_and_the_release(self):
        path = Path(__file__).parent.parent / '.github' / 'pull_request_template.md'
        text = path.read_text()
        self.assertEqual(tuple(parse(text)[0]), HEADINGS)
        self.assertEqual(len(problems(text)), len(HEADINGS) + 1)  # every heading empty, release unpicked


class Problems(unittest.TestCase):
    def test_hash_heading_inside_a_code_fence_is_code(self):
        body = GOOD.replace('call ends -> post_call', '## step one\ncall ends -> post_call')
        self.assertEqual(problems(body), [])
        self.assertEqual(tuple(parse(body)[0]), HEADINGS)

    def test_good_body_has_none(self):
        self.assertEqual(problems(GOOD), [])

    def test_missing_heading_is_named(self):
        body = GOOD.replace('## Who gets it', '## Audience')
        self.assertTrue(any('Who gets it' in p for p in problems(body)))

    def test_heading_holding_only_the_template_prompt_counts_as_empty(self):
        body = GOOD.replace('Staging call 81234 created a contact. Not proven: sandbox orgs.', '<!-- the real call -->')
        self.assertTrue(any('Proof' in p for p in problems(body)))

    def test_missing_release_marker(self):
        body = GOOD.replace('<!-- release: feature -->', '')
        self.assertTrue(any('release:' in p for p in problems(body)))

    def test_unknown_release_value(self):
        body = GOOD.replace('release: feature', 'release: maybe')
        self.assertTrue(any('release:' in p for p in problems(body)))

    def test_over_150_words_outside_code_and_details(self):
        body = GOOD.replace('Not proven: sandbox orgs.', 'word ' * 150)
        self.assertTrue(any('150' in p for p in problems(body)))

    def test_words_in_code_and_details_do_not_count(self):
        bulk = 'word ' * 300
        hidden = f'<details><summary>log</summary>\n{bulk}\n</details>\n```\n{bulk}\n```'
        body = GOOD.replace('Not proven: sandbox orgs.', hidden)
        self.assertEqual(problems(body), [])


class ReleasePost(unittest.TestCase):
    def test_feature_becomes_a_published_feature_post(self):
        post = release_post(GOOD, 'Integrations')
        self.assertEqual(post['category'], 'Feature')
        self.assertEqual(post['title'], 'Agents can push call results to Salesforce.')
        self.assertEqual(post['subtitle'], 'Before, only HubSpot was supported.')
        self.assertEqual(post['tags'], 'Integrations')
        self.assertIs(post['is_published'], True)
        self.assertIn('<p>Before, only HubSpot was supported.</p>', post['content'])

    def test_fix_becomes_bug_fix(self):
        self.assertEqual(release_post(GOOD.replace('release: feature', 'release: fix'), 'API')['category'], 'Bug Fix')

    def test_none_or_missing_release_makes_no_post(self):
        self.assertIsNone(release_post(GOOD.replace('release: feature', 'release: none'), 'API'))
        self.assertIsNone(release_post(GOOD.replace('<!-- release: feature -->', ''), 'API'))

    def test_one_line_section_reuses_the_title_as_subtitle(self):
        body = GOOD.replace('\nBefore, only HubSpot was supported.', '')
        post = release_post(body, 'API')
        self.assertEqual(post['subtitle'], post['title'])

    def test_html_in_the_body_is_escaped(self):
        post = release_post(GOOD.replace('Before, only', '<script>x</script> Before, only'), 'API')
        self.assertNotIn('<script>', post['content'])


class FakeServer(BaseHTTPRequestHandler):
    """GitHub and the changelog API in one: replies from `routes`, records every request."""

    routes, seen = {}, []

    def _reply(self):
        size = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(size)) if size else None
        FakeServer.seen.append((self.command, self.path, body))
        out = json.dumps(FakeServer.routes.get((self.command, self.path), {})).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PATCH = do_DELETE = _reply

    def log_message(self, *a):
        pass


class PublishFlow(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(('127.0.0.1', 0), FakeServer)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{self.srv.server_port}'
        FakeServer.seen = []
        FakeServer.routes = {
            ('GET', '/repos/o/r/commits/abc/pulls'): [
                {'number': 7, 'merged_at': 'x', 'merge_commit_sha': 'abc', 'body': GOOD}
            ],
            ('GET', '/repos/o/r/issues/7/comments?per_page=100'): [],
            ('POST', '/changelog'): {'id': 1200},
            ('POST', '/repos/o/r/issues/7/comments'): {'url': f'{base}/repos/o/r/issues/comments/55'},
        }
        event = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
        json.dump({}, event)
        event.close()
        self.env = {
            'GITHUB_API_URL': base,
            'GITHUB_REPOSITORY': 'o/r',
            'GH_TOKEN': 't',
            'GITHUB_EVENT_NAME': 'push',
            'GITHUB_EVENT_PATH': event.name,
            'GITHUB_SHA': 'abc',
            'CHANGELOG_URL': f'{base}/changelog',
            'CHANGELOG_KEY': 'k',
            'CHANGELOG_TAGS': 'Integrations',
        }

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def posts(self, path):
        return [body for method, p, body in FakeServer.seen if method == 'POST' and p == path]

    def test_merge_publishes_once_and_tells_the_pr(self):
        main(self.env)
        [post] = self.posts('/changelog')
        self.assertIs(post['is_published'], True)
        [first] = self.posts('/repos/o/r/issues/7/comments')
        self.assertIn('<!-- release-post -->', first['body'])  # the marker lands before the POST
        [(_, final)] = [(p, b) for m, p, b in FakeServer.seen if m == 'PATCH']
        self.assertIn('1200', final['body'])

    def test_warning_comment_appears_then_goes_when_fixed(self):
        self.env['GITHUB_EVENT_NAME'] = 'pull_request'
        pr = {'number': 7, 'user': {'login': 'dev'}, 'body': GOOD.replace('## Proof', '## Evidence')}
        with open(self.env['GITHUB_EVENT_PATH'], 'w') as fh:
            json.dump({'pull_request': pr}, fh)
        main(self.env)
        [warn] = self.posts('/repos/o/r/issues/7/comments')
        self.assertIn('Proof', warn['body'])
        FakeServer.routes[('GET', '/repos/o/r/issues/7/comments?per_page=100')] = [
            {'user': {'login': 'someone'}, 'body': '<!-- pr-body-check -->', 'url': f'{self.env["GITHUB_API_URL"]}/x'},
            {'user': {'login': 'github-actions[bot]'}, 'body': warn['body'], 'url': f'{self.env["GITHUB_API_URL"]}/y'},
        ]
        pr['body'] = GOOD
        with open(self.env['GITHUB_EVENT_PATH'], 'w') as fh:
            json.dump({'pull_request': pr}, fh)
        main(self.env)
        deletes = [p for method, p, _ in FakeServer.seen if method == 'DELETE']
        self.assertEqual(deletes, ['/y'])  # only the bot's own comment

    def test_push_whose_sha_no_pr_merged_as_posts_nothing(self):
        FakeServer.routes[('GET', '/repos/o/r/commits/abc/pulls')][0]['merge_commit_sha'] = 'other'
        main(self.env)
        self.assertEqual(self.posts('/changelog'), [])

    def test_failed_post_leaves_no_marker_so_a_rerun_retries(self):
        self.env['CHANGELOG_URL'] = 'http://127.0.0.1:1/closed'
        with self.assertRaises(OSError):
            main(self.env)
        deletes = [p for method, p, _ in FakeServer.seen if method == 'DELETE']
        self.assertEqual(deletes, ['/repos/o/r/issues/comments/55'])

    def test_rerun_after_a_post_posts_nothing(self):
        FakeServer.routes[('GET', '/repos/o/r/issues/7/comments?per_page=100')] = [
            {'user': {'login': 'github-actions[bot]'}, 'body': '<!-- release-post -->\nPublished as post 1200'}
        ]
        main(self.env)
        self.assertEqual(self.posts('/changelog'), [])


if __name__ == '__main__':
    unittest.main()
