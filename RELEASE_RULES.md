# RELEASE_RULES.md

Release checklist for `bambulab-metrics-exporter`.

## Important user intent rule

If the user asks to "raise/bump/update version", it **always** and **without exception** means:
- update changelog,
- create/push a Git tag for that version,
- create a GitHub Release with notes matching the changelog.

Never stop after "commit + push". The task is incomplete until tag + release both exist remotely.

## Mandatory sync points (always)

1. `pyproject.toml`
   - Update `project.version`.

2. `CHANGELOG.md`
   - Add a new top section for the target version.
   - Keep concise user-facing bullets.

3. GitHub Release
   - Create release/tag for the same version (`vX.Y.Z`).
   - Release notes should summarize the same changes.

## Standard release flow

1. Bump version in `pyproject.toml`.
2. Update `CHANGELOG.md`.
3. Commit and push to `main`.
4. Create tag `vX.Y.Z` and push it.
5. Create GitHub Release `vX.Y.Z` with notes.

## PR creation checklist (always use this)

When preparing a change for review, follow this exact sequence:

1. Create a **new branch from `main`**
   - Never open release/fix PRs from another feature branch.
   - Example: `git checkout main && git pull --ff-only && git checkout -b <branch-name>`

2. Prepare release docs before opening PR
   - Update `CHANGELOG.md` with the relevant version section and concise bullets.
   - Update `README.md` if metrics/labels/behavior changed.

3. Open PR with a title that matches the real change
   - Title must describe the user-facing fix/feature (not generic wording).
   - Prefer format: `<scope>: <what changed>` or `Release X.Y.Z: <summary>`.

4. Add PR description with:
   - What changed (bullet list)
   - Why it changed (short context)
   - Version to be released (e.g. `0.1.25`)
   - Validation proof (tests/live checks if relevant)

## Validation guard

Before tag/release, ensure:
- CI-critical files are consistent (workflow/config/docs touched as needed).
- No version mismatch between `pyproject.toml`, changelog section, tag, and release title.

## Definition of Done (version request)

A version request is complete only when all are true:
- [ ] `pyproject.toml` updated to the target version.
- [ ] `CHANGELOG.md` includes the new version section.
- [ ] Changes are committed and pushed to remote.
- [ ] Git tag `vX.Y.Z` is created and pushed.
- [ ] GitHub Release `vX.Y.Z` is created with notes matching changelog.
- [ ] Verification passed:
  - `git ls-remote --tags origin | grep "refs/tags/vX.Y.Z"`
  - `gh release view vX.Y.Z --repo <owner/repo>`

If verification fails, continue fixing in the same task until both checks pass.
