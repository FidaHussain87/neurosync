## Summary

<!-- What does this PR do and why? Keep it to 1-3 sentences. -->

## Related Issue

<!-- REQUIRED — CI will fail without this.
     Link the issue: "Fixes #123", "Closes #456", or "Resolves #789"
     For trivial PRs without an issue: "Related issue: N/A" -->

Fixes #

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (existing functionality would change)
- [ ] Performance improvement
- [ ] Refactoring (no functional changes)
- [ ] Documentation update
- [ ] Test improvement (no production code changes)
- [ ] CI / build / tooling

## Changes

<!-- Focus on the "why" — the diff shows the "what". -->

-

## How to Test

<!-- Concrete steps a reviewer can follow to verify. Include commands. -->

1.
2.
3.

## Screenshots / Logs

<!-- If applicable — UI changes, CLI output, error messages. Delete this section if not needed. -->

## Checklist

### Required (CI-enforced)

- [ ] All tests pass — `pytest --cov=neurosync -v`
- [ ] Lint clean — `ruff check neurosync/` and `ruff format --check neurosync/`
- [ ] Coverage >= 85%
- [ ] PR title is 10-72 characters
- [ ] PR body references an issue (or states `Related issue: N/A`)
- [ ] PR description is filled out (not just the template placeholders)

### If applicable

- [ ] New code has tests
- [ ] Frontend builds — `cd frontend && npm run typecheck && npm run build`
- [ ] `CLAUDE.md` updated (if architecture or tool behavior changed)
- [ ] `docs/` updated (if user-facing behavior changed)
- [ ] No new dependencies added (or discussed in the linked issue first)
- [ ] Commit messages follow [conventional format](CONTRIBUTING.md#commit-messages)
