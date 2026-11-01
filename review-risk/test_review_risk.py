"""Run: python3 -m unittest review-risk/test_review_risk.py"""

import unittest

from review_risk import ai_verdict, decide, parse_rules

RULES = parse_rules("""
# money
app/billing/*
*/security/*
*stripe*
.github/*
""")
BOT = 'github-actions[bot]'
SHA = 'abcdef1234567890'


def files(*pairs):
    return [{'path': p, 'changes': n} for p, n in pairs]


def tier(fs, ai='clean', assoc='MEMBER', login='dev'):
    return decide(fs, RULES, assoc, login, ai, max_lines=400)[0]


class Tiers(unittest.TestCase):
    def test_small_change_outside_risk_paths_is_low(self):
        self.assertEqual(tier(files(('app/models/user.py', 40))), 'low')

    def test_risk_path_is_high(self):
        self.assertEqual(tier(files(('app/billing/models/plan.py', 3))), 'high')

    def test_double_star_matches_at_the_root_and_deep(self):
        self.assertEqual(tier(files(('security/rules.csv', 1))), 'high')
        self.assertEqual(tier(files(('a/b/security/rules.xml', 1))), 'high')
        self.assertEqual(tier(files(('lib/stripe-client.ts', 1))), 'high')

    def test_tests_never_raise_the_tier(self):
        self.assertEqual(tier(files(('app/billing/tests/test_plan.py', 30))), 'low')
        self.assertEqual(tier(files(('__tests__/lib/stripe.test.ts', 30))), 'low')

    def test_a_test_named_file_outside_a_tests_folder_still_counts(self):
        self.assertEqual(tier(files(('app/billing/test_routes.py', 3))), 'high')

    def test_a_rename_out_of_a_risk_path_is_high(self):
        fs = [{'path': 'app/plans.py', 'previous': 'app/billing/plans.py', 'changes': 0}]
        self.assertEqual(tier(fs), 'high')

    def test_no_rules_file_floors_at_standard(self):
        self.assertEqual(decide(files(('app/a.py', 1)), None, 'MEMBER', 'k', 'clean', 400)[0], 'standard')

    def test_a_truncated_file_list_is_high(self):
        self.assertEqual(decide(files(('app/a.py', 1)) * 3000, RULES, 'MEMBER', 'k', 'clean', 400)[0], 'high')

    def test_the_rules_file_itself_is_high(self):
        fs = files(('.github/review-risk-paths', 1))
        self.assertEqual(decide(fs, [], 'MEMBER', 'k', 'not_needed', 400)[0], 'high')

    def test_over_max_lines_is_standard(self):
        self.assertEqual(tier(files(('app/a.py', 300), ('app/b.py', 101))), 'standard')
        self.assertEqual(tier(files(('app/a.py', 400))), 'low')

    def test_lockfiles_do_not_count_toward_size(self):
        self.assertEqual(tier(files(('package-lock.json', 5000), ('package.json', 2))), 'low')

    def test_ai_findings_raise_low_to_standard(self):
        self.assertEqual(tier(files(('app/a.py', 5)), ai='findings'), 'standard')

    def test_missing_ai_review_fails_closed(self):
        self.assertEqual(tier(files(('app/a.py', 5)), ai='missing'), 'standard')

    def test_ai_cannot_lower_a_tier(self):
        self.assertEqual(tier(files(('.github/workflows/x.yml', 5)), ai='clean'), 'high')
        self.assertEqual(tier(files(('.github/workflows/x.yml', 500)), ai='findings'), 'high')

    def test_outside_author_is_high(self):
        self.assertEqual(tier(files(('app/a.py', 5)), assoc='CONTRIBUTOR', login='someone'), 'high')

    def test_dependabot_is_treated_as_a_member(self):
        self.assertEqual(tier(files(('package.json', 2)), assoc='NONE', login='dependabot[bot]'), 'low')

    def test_a_major_version_bump_is_standard(self):
        fs = files(('package.json', 2))
        major = 'Bump date-fns from 3.6.0 to 4.4.0'
        minor = 'Bump the minor-and-patch group across 1 directory with 5 updates'
        self.assertEqual(decide(fs, RULES, 'NONE', 'dependabot[bot]', 'clean', 400, major)[0], 'standard')
        self.assertEqual(decide(fs, RULES, 'NONE', 'dependabot[bot]', 'clean', 400, minor)[0], 'low')
        self.assertEqual(decide(fs, RULES, 'NONE', 'dependabot[bot]', 'clean', 400, 'Bump x from 1.2 to 1.3')[0], 'low')

    def test_reasons_name_the_file(self):
        reasons = decide(files(('app/billing/x.py', 1)), RULES, 'MEMBER', 'k', 'clean', 400)[1]
        self.assertTrue(any('app/billing/x.py' in r for r in reasons))


class AiVerdict(unittest.TestCase):
    MARK = '<!-- opencode-review -->'

    def test_clean_for_head(self):
        body = f'{self.MARK}\nNothing blocking found. :)\n\n<sub>OpenCode review of {SHA[:9]}, advisory.</sub>'
        self.assertEqual(ai_verdict([(BOT, body)], SHA, files(('a.py', 1))), 'clean')

    def test_a_comment_by_a_person_is_ignored(self):
        body = f'{self.MARK}\nNothing blocking found. :)\n<sub>OpenCode review of {SHA[:9]}</sub>'
        self.assertEqual(ai_verdict([('someone', body)], SHA, files(('a.py', 1))), 'missing')

    def test_a_finding_that_quotes_the_clean_phrase_is_still_a_finding(self):
        item = '1. Says Nothing blocking found wrongly (`a.py`).'
        body = f'{self.MARK}\nChanges needed: 1 thing. :/\n\n{item}\n<sub>OpenCode review of {SHA[:9]}</sub>'
        self.assertEqual(ai_verdict([(BOT, body)], SHA, files(('a.py', 1))), 'findings')

    def test_findings_for_head(self):
        body = f'{self.MARK}\nChanges needed: 1 thing. :/\n\n<sub>OpenCode review of {SHA[:9]}</sub>'
        self.assertEqual(ai_verdict([(BOT, body)], SHA, files(('a.py', 1))), 'findings')

    def test_review_of_an_older_commit_is_missing(self):
        body = f'{self.MARK}\nNothing blocking found. :)\n<sub>OpenCode review of 999999999</sub>'
        self.assertEqual(ai_verdict([(BOT, body)], SHA, files(('a.py', 1))), 'missing')

    def test_unfinished_review_is_missing(self):
        body = f'{self.MARK}\nReview did not finish for {SHA[:9]}. -_-'
        self.assertEqual(ai_verdict([(BOT, body)], SHA, files(('a.py', 1))), 'missing')

    def test_no_code_needs_no_review(self):
        self.assertEqual(ai_verdict([], SHA, files(('README.md', 3), ('views/x.xml', 2))), 'not_needed')

    def test_lockfile_only_needs_no_review(self):
        self.assertEqual(ai_verdict([], SHA, files(('package-lock.json', 30))), 'not_needed')


if __name__ == '__main__':
    unittest.main()
