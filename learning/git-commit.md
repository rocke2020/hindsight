# Git Commit and Push

Use explicit file paths so only the intended documentation is committed. The pre-commit hook requires `uv`, `uvx`, and `npx` on `PATH`.

```bash
cd "$(git rev-parse --show-toplevel)"

export PATH="$HOME/.local/bin:/opt/homebrew/opt/node/bin:/opt/homebrew/bin:$PATH"
command -v uv uvx npx

# Stage only the intended docs. Replace these paths as needed.
git add .

# Review the exact commit boundary.
# git diff --cached --name-status
# git diff --cached --check
# git diff --cached

# Commit; the repository pre-commit hook runs automatically.
git commit -m "docs: describe the documentation update"

# Confirm the commit contains only the intended files, then push.
git show --name-status --oneline HEAD
git status --short
git push origin "$(git branch --show-current)"
```

Avoid `git add -A`, `git commit -a`, and `git commit --no-verify` for a docs-only update.
