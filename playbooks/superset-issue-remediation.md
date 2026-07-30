# Superset Issue Remediation

## Outcome

Given a single issue from `mattyiceg-org/superset` (issue number, title, body,
and URL supplied in the session prompt), resolve it with a minimal, correct
change and open a pull request that references the issue — following this
repo's own conventions, not generic best practice, wherever the two disagree.

## Required from user (per session)

- Issue number
- Issue title
- Issue body
- Issue URL

## Procedure

1. Open `mattyiceg-org/superset` (already reachable via the connected GitHub
   integration — do not ask for credentials).
2. Read the full issue body supplied in the prompt before touching any code.
3. Read `CLAUDE.md` and `SECURITY.md` at the repo root and follow their
   conventions: type hints, docstring style, PR title format
   (Conventional Commits), pre-commit requirements.
4. Locate the exact file(s) the issue names or clearly implies.
5. Make the smallest change that satisfies the issue's stated proposal —
   do not expand scope beyond what it describes.
6. If the issue is a dependency bump: change only the pin(s) it names, in the
   file(s) it names, and regenerate any lockfile the repo's own tooling
   expects (see `requirements/README.md`). Do not touch unrelated pins.
7. If the issue asks for new tests: match the mocking style and fixtures of
   the nearest sibling test file rather than introducing a new pattern.
8. If the issue asks for a new CLI command or function: mirror the structure
   of the most similar existing command/function in the same file, including
   decorators and output style (e.g. `click.secho` color conventions).
9. Run the relevant test/lint commands for the changed files and fix any
   failures before proceeding — you do not need to run the full suite.
10. Run `pre-commit run` on the changed files and resolve anything it flags.
11. Commit with a Conventional Commits message.
12. Open a pull request against `mattyiceg-org/superset`'s default branch,
    using `.github/PULL_REQUEST_TEMPLATE.md` if present, referencing the issue
    (e.g. "Closes #N").
13. Comment on the original issue with the PR link and a one-paragraph
    summary of what changed and why.
14. Populate the session's structured output exactly as specified by its
    `structured_output_schema`.

## Advice

- Prefer the smallest diff that fully addresses the issue; do not refactor
  unrelated code you happen to pass through.
- If the issue's premise no longer matches what you observe in the live code
  (e.g. the described gap is already fixed), stop and report
  `status: "needs_review"` with an explanation instead of inventing unrelated
  work to justify the session.
- Match this repo's existing conventions over generic best practice when they
  conflict (e.g. `~Model.field` instead of `Model.field == False`, per
  `CLAUDE.md`).

## Forbidden actions

- Do not modify files outside the scope of the issue.
- Do not disable, skip, or weaken existing tests to make the suite pass.
- Do not touch migrations, authorization/security checks, or CI/workflow
  config unless the issue explicitly asks for it.
- Do not widen dependency ranges in `pyproject.toml` beyond what the issue
  specifies.

## Structured output

Return JSON matching the session's schema:

```json
{
  "status": "success | failed | needs_review",
  "pr_url": "<url, or empty string if none was opened>",
  "summary": "<one paragraph>",
  "tests_passed": true
}
```
