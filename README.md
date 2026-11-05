# .github

Organization defaults for [Omnidim](https://github.com/Omnidim).

- `profile/README.md` renders on the organization landing page.
- `SECURITY.md` and `SUPPORT.md` apply to every repository in the organization
  that does not define its own.
- `.github/pull_request_template.md` and `.github/ISSUE_TEMPLATE/` are the default
  PR and issue forms for every repository.
- `pr-body/` is an action that warns when a PR body misses the PR form, and turns
  a merged `release: feature` or `release: fix` PR into an unpublished changelog draft.
  Tests: `python3 -m unittest discover -s pr-body`.

Editing `profile/README.md` changes what every visitor to the organization page
sees, so treat it as public brand copy.
