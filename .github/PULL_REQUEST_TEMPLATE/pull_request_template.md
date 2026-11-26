## Description

<!-- Brief description of changes -->

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing

- [ ] Tests pass (`python -m pytest tests/ -v`)
- [ ] New tests added (if applicable)
- [ ] Manual testing completed

## Checklist

- [ ] Code follows project style guidelines
- [ ] Type hints on all public functions
- [ ] Docstrings updated (if applicable)
- [ ] No database calls in service functions
- [ ] README updated (if applicable)

## Screenshots (if applicable)

<!-- Add screenshots for UI changes -->

## Check run

- [ ] The `CI` workflow is green on the latest commit of this branch. Run URL:
      <!-- paste the Actions run URL here; required, leave empty only if CI cannot run -->
- [ ] `make ci` passes locally (the local equivalent of the CI workflow).

The `CI` workflow runs the backend, server-group, eval-gate, supply-chain, docs-drift, web, e2e-live and images jobs. A red or missing check run blocks merge.

## Rollback

<!-- Required. One line: the exact command or deploy step that reverts this change. The author must fill this in, for example "git revert <sha>" followed by the Render redeploy, or a redeploy of the previous Cloudflare Pages deployment if the change ships there. Do not guess a mechanism that does not exist. -->
Rollback:
