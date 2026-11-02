# Contributing to PayFlow App

Thanks for your interest! This project is built in public as a learning portfolio, so the workflow below is kept simple and strict.

## Setup
0. Install pre-commit (once per machine) and the hooks (once per clone):
   ```bash
   pipx install pre-commit      # or: pip install pre-commit
   ```
1. Clone the repo:
   ```bash
   git clone git@github.com:owais-io/payflow-app.git
   cd payflow-app
   ```
2. Install the pre-commit hooks (once per clone):
   ```bash
   pre-commit install
   ```
   Every `git commit` now runs formatting and safety checks automatically.
3. Python services use a virtualenv per service; see each service’s README (coming in Phase 1).
## Workflow

`main` is protected. All changes go through a pull request:

1. Update `main`: `git switch main && git pull`
2. Create a branch **before** editing: `git switch -c <type>/<short-description>`
3. Commit your changes (pre-commit runs automatically)
4. Push and open a PR: `git push -u origin <branch>` then `gh pr create --fill`
5. Squash-merge: `gh pr merge --squash --delete-branch`

If a pre-commit hook **modifies** files, the commit stops. Review the changes, `git add` them, and commit again.

## Branch names

| Prefix | Use for | Example |
|---|---|---|
| `feat/` | New functionality | `feat/accounts-api-balance` |
| `fix/` | Bug fixes | `fix/payments-insufficient-funds` |
| `docs/` | Documentation only | `docs/phase-3-journal` |
| `ci/` | CI/CD pipelines | `ci/release-workflow` |
| `chore/` | Housekeeping, tooling, dependencies | `chore/pre-commit-autoupdate` |

## Commit messages examples

```
feat: add Helm chart for payflow services
fix: correct readiness probe path for payments-api
docs: add 3.2 journal entry
```

The type matches the branch prefix.

## Build journal

Journal entries for this repo are kept in [payflow-platform](https://github.com/owais-io/payflow-platform/tree/main/docs/journal).

## Never commit

- Secrets, passwords, tokens, or private keys
- AWS account IDs, ARNs, or portal URLs
- `*.tfstate` files or `.env` files
