#!/bin/bash
set -u

echo "=== STEP 1 EXTRA ==="
PID=$(systemctl show crm-streamlit.service -p MainPID --value)
echo "MAIN_PID=$PID"
echo "CWD=$(readlink -f /proc/$PID/cwd 2>/dev/null || echo UNAVAILABLE)"
echo "EXE=$(readlink -f /proc/$PID/exe 2>/dev/null || echo UNAVAILABLE)"
printf "CMDLINE="
tr '\0' ' ' < /proc/$PID/cmdline 2>/dev/null || echo UNAVAILABLE
echo

echo "=== STEP 2: GIT DISCOVERY ==="
find /opt /root /home -maxdepth 6 \( -type d -o -type f \) -name .git -print 2>/dev/null || true

echo "=== STEP 3: /opt/CRM_Streamlit STATE ==="
cd /opt/CRM_Streamlit
echo "TOPLEVEL=$(git rev-parse --show-toplevel)"
echo "HEAD=$(git rev-parse HEAD)"
echo "BRANCH=$(git branch --show-current)"

echo "=== STATUS ==="
git status --short | head -60

echo "=== STATUS FULL ==="
git status

echo "=== DIFF STAT ==="
git diff --stat | tail -20

echo "=== DIFF NAMES ==="
git diff --name-status | head -60

echo "=== REMOTE ==="
git remote -v

echo "=== BRANCHES ==="
git branch -avv

echo "=== WORKTREES ==="
git worktree list --porcelain 2>/dev/null || true

echo "=== RECENT GRAPH ==="
git log --all --graph --decorate --oneline --date-order -n 100
