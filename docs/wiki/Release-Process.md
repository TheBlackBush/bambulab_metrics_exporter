# Release Process

Tag-based workflow. Docker images are published to GHCR when a GitHub Release is published.

---

## Version Format

`v<major>.<minor>.<patch>` — e.g., `v0.1.36`. Tracked in `pyproject.toml`.

---

## CI/CD Summary

| Trigger | What runs |
|---------|-----------|
| Pull Request | Essential checks (fast feedback) |
| Push/merge to `main` | Full test suite |
| GitHub Release published | Full tests + Docker build + push to GHCR |

Docker: `ghcr.io/theblackbush/bambulab_metrics_exporter:<tag>`

Release notes are updated automatically with Docker image paths after a successful publish.

---

## Step-by-Step

### 1. Verify CI on main

https://github.com/TheBlackBush/bambulab_metrics_exporter/actions

### 2. Update CHANGELOG.md

```markdown
## [0.1.X] - YYYY-MM-DD

### Added / Changed / Fixed
- ...
```

```bash
git add CHANGELOG.md && git commit -m "chore: update changelog for v0.1.X"
git push origin main
```

### 3. Bump version in pyproject.toml

```bash
git add pyproject.toml && git commit -m "chore: bump version to v0.1.X"
git push origin main
```

### 4. Tag and push

```bash
git tag v0.1.X
git push origin v0.1.X
```

### 5. Publish GitHub Release

1. https://github.com/TheBlackBush/bambulab_metrics_exporter/releases/new
2. Select tag `v0.1.X`, set title `v0.1.X`
3. Paste relevant CHANGELOG section as release notes
4. Click **Publish release**

### 6. Verify

- Workflow: https://github.com/TheBlackBush/bambulab_metrics_exporter/actions/workflows/docker-publish.yml
- Package: https://github.com/TheBlackBush/bambulab_metrics_exporter/pkgs/container/bambulab_metrics_exporter

---

## Running Tests Locally

```bash
make test           # full suite with coverage gate (>90%)
make test-unit      # unit tests only
make test-integration  # integration (no coverage gate)
make test-e2e       # e2e (no coverage gate)
make test-profile   # smoke profile (integration + e2e)
```

Or directly:

```bash
pip install -e .[dev]
pytest --cov=src --cov-report=term-missing
```

---

## Notes

- Integration/e2e use `--no-cov` to avoid false negatives from the global coverage threshold
- Coverage gate: >90% for core modules
- Sample regression artifacts: `examples/sample_mqtt_message.json`, `examples/sample_metrics.prom`
