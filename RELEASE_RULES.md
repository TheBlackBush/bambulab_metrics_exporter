# RELEASE_RULES.md

Release and PR rules for `bambulab-metrics-exporter`.

## Important intent rule

If the user asks to bump/update version, the task is **not done** at "commit + push".
It is complete only when version files, changelog, tag, and GitHub Release are all updated and consistent.

## 0) Git identity (required before any commit/release action)

- Verify active git identity before starting work and again before release steps.
- Required identity for this repo workflow:
  - `user.name` must be `"Idan Bush"`
  - `user.email` must be the configured email for this repo
- Verify local identity:
  - `git config user.name`
  - `git config user.email`
- Set local repo identity (preferred over global for safety):
  - `git config user.name "Idan Bush"`
  - `git config user.email "idan.bushari@gmail.com"` (or repo-approved email)

## 1) PR workflow (required)

**Policy enforcement (main branch protection intent):**
- Do **not** push feature/content changes directly to `main`.
- All non-emergency changes must go through a branch + PR.
- Direct commits to `main` are allowed only for an explicitly approved emergency hotfix.

1. Branch from latest `main`:
   - `git checkout main && git pull --ff-only`
   - `git checkout -b <branch-name>`
2. Implement changes and add/update tests.
3. Open a PR with a high-quality description:
   - what changed,
   - why,
   - validation performed,
   - release intent (if this PR is meant to ship a release).
4. Wait for CI to pass (green).
5. Perform the code review checklist (scope, tests, docs/changelog/version consistency as relevant).
6. Merge only after all required checks and review items pass.

## 2) Version bump workflow (for release-intended PRs)

1. Bump **patch** version in required files:
   - `pyproject.toml` (`project.version`)
   - `src/bambulab_metrics_exporter/__init__.py` (if version is defined there)
2. Update `CHANGELOG.md` with a release-ready entry for that version.
3. Ensure the PR includes both version bump and changelog updates.
4. Ensure version values are consistent across files and with planned tag/release.

## 3) Release workflow

1. Create or update tag `vX.Y.Z`.
2. Ensure the tag points to the merge commit on `main`.
3. Create or edit GitHub Release for that tag.
4. Release title must follow repo convention: same as tag (for example `v0.1.37`).
5. Release notes quality guidelines:
   - concise sections: **Added**, **Behavior**, **Quality**,
   - technically accurate,
   - mention compatibility/unchanged behavior where relevant.

## 4) Operational checklist (quick run)

- [ ] Working branch started from latest `main`.
- [ ] Implementation + tests complete.
- [ ] PR description is complete and clear.
- [ ] CI is green.
- [ ] Review checklist completed; only then merge.
- [ ] `pyproject.toml` version updated.
- [ ] `src/.../__init__.py` version updated (if applicable).
- [ ] `CHANGELOG.md` updated for release version.
- [ ] Tag `vX.Y.Z` exists and points to merge commit on `main`.
- [ ] GitHub Release exists/updated, title matches tag, notes are well-formatted.

## Common pitfalls to avoid

- Tag points to the wrong commit (not merged `main`).
- Version mismatch between `pyproject.toml`, `__init__.py`, changelog, tag, or release title.
- PR merged before CI/review checklist is complete.
- Release notes with broken Markdown formatting or missing required sections.
- Changelog text and release notes diverge in meaning.
