#!/bin/bash
# 初始化 git 仓库并推送到 GitHub
set -e

cd "$(dirname "$0")"

REPO_NAME="ai-infra-monitor"
GITHUB_USER="gudanqiangshou"

# 检查 gh CLI
if ! command -v gh &> /dev/null; then
    echo "❌ gh CLI not installed. Install: brew install gh"
    exit 1
fi

# 检查 GH token
if [ -z "$GITHUB_TOKEN" ]; then
    echo "❌ GITHUB_TOKEN env var required"
    exit 1
fi

# 1. 初始化 git
if [ ! -d .git ]; then
    git init -b main
    echo "✅ git init"
fi

# 2. 创建 .gitignore
cat > .gitignore <<EOF
__pycache__/
*.pyc
logs/*.log
data/*.db-journal
.DS_Store
.env
EOF

# 3. 初始 commit
git add .gitignore config.yaml scripts/ docs/ com.a1.ai-infra-monitor.plist setup_github.sh
git diff --cached --quiet || git commit -m "init: AI infra monitor — capex + token + investment dashboard"

# 4. 创建 GitHub repo（如不存在）
if ! gh repo view "$GITHUB_USER/$REPO_NAME" &> /dev/null; then
    gh repo create "$GITHUB_USER/$REPO_NAME" --public \
        --description "AI infrastructure investment monitor — hyperscaler capex + global AI token consumption" \
        --source=. --remote=origin --push
    echo "✅ created repo"
else
    git remote get-url origin > /dev/null 2>&1 || \
        git remote add origin "https://github.com/$GITHUB_USER/$REPO_NAME.git"
    git push -u origin main
    echo "✅ pushed to existing repo"
fi

# 5. 启用 GitHub Pages（main branch /docs）
gh api -X POST "repos/$GITHUB_USER/$REPO_NAME/pages" \
    -f "source[branch]=main" -f "source[path]=/docs" 2>/dev/null || \
gh api -X PUT "repos/$GITHUB_USER/$REPO_NAME/pages" \
    -f "source[branch]=main" -f "source[path]=/docs" 2>/dev/null || \
    echo "ℹ️ Pages may already be configured"

echo ""
echo "🎉 Setup complete!"
echo "   Repo:      https://github.com/$GITHUB_USER/$REPO_NAME"
echo "   Pages URL: https://$GITHUB_USER.github.io/$REPO_NAME/  (may take 1-2 min)"
