# Ignore policy

- Keep shared ignore rules in the repository root and review them as governance changes.
- Keep role-root `.gitignore` files local when the team uses personal local preferences.
- Before changing a rule, run `git check-ignore -v -- <path>`; before removing a tracked file from the index, inspect it and obtain maintainer confirmation.
- Keep reproducible source, necessary evidence and final deliverables under version control. Keep caches, secrets, generated bulk output and local exchange bundles outside it unless the team records an exception.
