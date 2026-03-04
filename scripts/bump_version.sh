#!/usr/bin/env bash
# =============================================================================
# SOC Dashboard — Version Bump Script
# ใช้: bash scripts/bump_version.sh [major|minor|patch] ["changelog message"]
#
# ตัวอย่าง:
#   bash scripts/bump_version.sh patch "Fix login redirect bug"
#   bash scripts/bump_version.sh minor "Add MOPH Notify support"
#   bash scripts/bump_version.sh major "Breaking: new DB schema"
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${REPO_ROOT}/VERSION"
CHANGELOG_FILE="${REPO_ROOT}/CHANGELOG.md"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }
err()  { echo -e "\033[0;31m[ERROR]${NC} $*"; exit 1; }

# ── Args ──────────────────────────────────────────────────────────────────────
BUMP_TYPE="${1:-patch}"
CHANGE_MSG="${2:-}"

[[ "$BUMP_TYPE" =~ ^(major|minor|patch)$ ]] || \
    err "ระบุ type: major | minor | patch\nการใช้: $0 <major|minor|patch> [\"message\"]"

# ── Read current version ──────────────────────────────────────────────────────
[[ -f "$VERSION_FILE" ]] || err "ไม่พบ VERSION file ที่ ${VERSION_FILE}"
CURRENT=$(cat "$VERSION_FILE" | tr -d '[:space:]')

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

# ── Bump ──────────────────────────────────────────────────────────────────────
case "$BUMP_TYPE" in
    major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
    patch) PATCH=$((PATCH + 1)) ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
TODAY=$(date +%Y-%m-%d)

info "Bumping version: ${CURRENT} → ${NEW_VERSION}"

# ── Confirm ───────────────────────────────────────────────────────────────────
read -rp "Confirm bump to v${NEW_VERSION}? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { echo "Aborted."; exit 0; }

# ── Prompt changelog if not provided ─────────────────────────────────────────
if [[ -z "$CHANGE_MSG" ]]; then
    read -rp "Changelog entry (เว้นว่างเพื่อข้าม): " CHANGE_MSG
fi

# ── Update VERSION ────────────────────────────────────────────────────────────
echo "${NEW_VERSION}" > "$VERSION_FILE"
ok "VERSION → ${NEW_VERSION}"

# ── Update CHANGELOG ─────────────────────────────────────────────────────────
if [[ -n "$CHANGE_MSG" ]]; then
    NEW_ENTRY="## [${NEW_VERSION}] - ${TODAY}\n\n### Changed\n- ${CHANGE_MSG}\n"
    # แทรกหลังบรรทัด "---" แรก
    awk -v entry="${NEW_ENTRY}" '
        /^---$/ && !done { print; print ""; printf "%s", entry; done=1; next }
        { print }
    ' "$CHANGELOG_FILE" > "${CHANGELOG_FILE}.tmp" && mv "${CHANGELOG_FILE}.tmp" "$CHANGELOG_FILE"
    ok "CHANGELOG updated"
fi

# ── Git commit + tag ──────────────────────────────────────────────────────────
cd "$REPO_ROOT"

# ตรวจสอบว่ามี git repo
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    err "ไม่ใช่ git repository"
fi

# ตรวจว่า tag นี้มีแล้วหรือยัง
if git tag -l | grep -q "^v${NEW_VERSION}$"; then
    err "Tag v${NEW_VERSION} มีอยู่แล้ว"
fi

git add VERSION CHANGELOG.md
git commit -m "chore: bump version to v${NEW_VERSION}${CHANGE_MSG:+ — ${CHANGE_MSG}}"
git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}${CHANGE_MSG:+: ${CHANGE_MSG}}"
ok "Git commit + tag v${NEW_VERSION} created"

# ── Push ──────────────────────────────────────────────────────────────────────
read -rp "Push to GitHub? [Y/n]: " PUSH_CONFIRM
PUSH_CONFIRM="${PUSH_CONFIRM:-y}"
if [[ "${PUSH_CONFIRM,,}" == "y" ]]; then
    git push origin main
    git push origin "v${NEW_VERSION}"
    ok "Pushed to GitHub"
    echo ""
    echo -e "  ${CYAN}Release URL:${NC} https://github.com/jacom/SOC-Dashboard/releases/tag/v${NEW_VERSION}"
else
    echo ""
    info "Push ด้วยตนเอง:"
    echo "  git push origin main"
    echo "  git push origin v${NEW_VERSION}"
fi

echo ""
echo -e "${GREEN}✓ Version bumped: ${CURRENT} → ${NEW_VERSION}${NC}"
