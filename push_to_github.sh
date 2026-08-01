#!/bin/bash
# ============================================================
# MyHarness (MYH) — Gitee 仓库推送脚本
# 当前已推送至 Gitee: https://gitee.com/Taery-mingjun/myharness
# ============================================================
set -e

REPO_NAME="myharness"
GITEE_USER="Taery-mingjun"
REPO_URL="https://gitee.com/${GITEE_USER}/${REPO_NAME}.git"

echo "=========================================="
echo " MyHarness (MYH) GitHub 推送脚本"
echo "=========================================="
echo ""

# Step 1: 检查是否在项目目录
if [ ! -f "pyproject.toml" ]; then
    echo "❌ 错误: 请在 myharness 项目根目录执行此脚本"
    echo "   cd /path/to/myharness && bash push_to_github.sh"
    exit 1
fi

# Step 2: 检查 git 状态
echo "📋 Step 1/4: 检查 git 状态..."
if [ ! -d ".git" ]; then
    echo "   初始化 git 仓库..."
    git init
    git checkout -b main
fi

# Step 3: 检查远程仓库
echo ""
echo "🔗 Step 2/4: 配置远程仓库..."
if git remote get-url origin &>/dev/null; then
    CURRENT_URL=$(git remote get-url origin)
    echo "   当前远程: $CURRENT_URL"
    if [[ "$CURRENT_URL" != *"${GITHUB_USER}/${REPO_NAME}"* ]]; then
        git remote set-url origin "$REPO_URL"
        echo "   ✅ 已更新远程地址"
    else
        echo "   ✅ 远程地址正确"
    fi
else
    git remote add origin "$REPO_URL"
    echo "   ✅ 已添加远程仓库"
fi

# Step 4: 推送到 GitHub
echo ""
echo "🚀 Step 3/4: 推送代码到 GitHub..."
echo ""
echo "   如果仓库尚未创建，请先在浏览器打开："
echo "   https://github.com/new"
echo "   - Repository name: myharness"
echo "   - Description: MyHarness (MYH) - Cognitive Operating System for AI Agents"
echo "   - Public: ✓"
echo "   - 不要勾选 'Add a README file'"
echo "   - 点击 'Create repository'"
echo ""
read -p "   仓库已创建？按回车继续推送..."

echo ""
git push -u origin main

# Step 5: 验证
echo ""
echo "✅ Step 4/4: 推送完成！"
echo ""
echo "🔗 仓库地址: https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo ""
echo "=========================================="
echo " 项目信息"
echo "=========================================="
echo "  文件数:   $(find src -name '*.py' | wc -l | tr -d ' ') Python 模块"
echo "  测试:     $(find tests -name '*.py' -exec grep -l 'def test_' {} \; | wc -l | tr -d ' ') 个测试文件"
echo "  代码行:   $(find src tests -name '*.py' -exec cat {} + | wc -l | tr -d ' ') 行"
echo "=========================================="
