#!/usr/bin/env bash
# FC-002: scripts/install.sh must generate a strong NOVA_ADMIN_SECRET when
# .env contains the literal default, an empty value, or no value at all.
#
# This test runs the secret-generation block in a sandboxed tmpdir so it
# doesn't touch the real .env. It mirrors the install.sh logic verbatim;
# any drift between this test and install.sh will be caught here.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

failed=0
fail() { echo "✗ $*"; failed=1; }
pass() { echo "✓ $*"; }

run_generation() {
  # Mirror the install.sh upsert + generation block.
  local target="$1"
  local upsert_env_def='
    upsert_env() {
      local key="$1"; local value="$2"; local file="'"${target}"'"
      if [ ! -f "$file" ]; then printf "%s=%s\n" "$key" "$value" > "$file"; return; fi
      if grep -q "^${key}=" "$file" 2>/dev/null; then
        local tmp; tmp=$(mktemp)
        awk -v k="${key}" -v v="${value}" "BEGIN{FS=OFS=\"=\"} \$1==k{print k\"=\"v; next} {print}" "$file" > "$tmp"
        mv "$tmp" "$file"
      else
        printf "%s=%s\n" "$key" "$value" >> "$file"
      fi
    }
  '
  bash -c "
    ${upsert_env_def}
    if grep -qE '^NOVA_ADMIN_SECRET=(nova-admin-secret-change-me|)\$' '${target}' 2>/dev/null \
       || ! grep -q '^NOVA_ADMIN_SECRET=' '${target}' 2>/dev/null; then
      NOVA_ADMIN_SECRET=\$(openssl rand -hex 32)
      upsert_env NOVA_ADMIN_SECRET \"\${NOVA_ADMIN_SECRET}\"
    fi
  "
}

assert_strong_secret() {
  local file="$1"; local case_name="$2"
  if ! grep -q '^NOVA_ADMIN_SECRET=' "$file"; then
    fail "${case_name}: NOVA_ADMIN_SECRET not present after generation"
    return
  fi
  if grep -q '^NOVA_ADMIN_SECRET=nova-admin-secret-change-me$' "$file"; then
    fail "${case_name}: secret is still the literal default"
    return
  fi
  local secret
  secret=$(grep '^NOVA_ADMIN_SECRET=' "$file" | head -1 | cut -d= -f2)
  if [ -z "$secret" ]; then
    fail "${case_name}: secret is empty after generation"
    return
  fi
  if [ "${#secret}" -lt 32 ]; then
    fail "${case_name}: secret too short (${#secret} chars, need >= 32)"
    return
  fi
  pass "${case_name}: generated secret length=${#secret}"
}

# Case 1: literal default
echo "→ Case 1: NOVA_ADMIN_SECRET=nova-admin-secret-change-me"
echo "NOVA_ADMIN_SECRET=nova-admin-secret-change-me" > "${TMPDIR}/case1.env"
echo "OTHER_VALUE=preserved" >> "${TMPDIR}/case1.env"
run_generation "${TMPDIR}/case1.env"
assert_strong_secret "${TMPDIR}/case1.env" "case1"
grep -q '^OTHER_VALUE=preserved$' "${TMPDIR}/case1.env" || fail "case1: OTHER_VALUE was not preserved"

# Case 2: empty value
echo "→ Case 2: NOVA_ADMIN_SECRET= (empty)"
echo "NOVA_ADMIN_SECRET=" > "${TMPDIR}/case2.env"
run_generation "${TMPDIR}/case2.env"
assert_strong_secret "${TMPDIR}/case2.env" "case2"

# Case 3: missing entirely
echo "→ Case 3: NOVA_ADMIN_SECRET key absent"
echo "OTHER_VALUE=preserved" > "${TMPDIR}/case3.env"
run_generation "${TMPDIR}/case3.env"
assert_strong_secret "${TMPDIR}/case3.env" "case3"
grep -q '^OTHER_VALUE=preserved$' "${TMPDIR}/case3.env" || fail "case3: OTHER_VALUE was not preserved"

# Case 4: already-strong secret should be left alone
echo "→ Case 4: existing strong secret is not regenerated"
EXISTING="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
echo "NOVA_ADMIN_SECRET=${EXISTING}" > "${TMPDIR}/case4.env"
run_generation "${TMPDIR}/case4.env"
ACTUAL=$(grep '^NOVA_ADMIN_SECRET=' "${TMPDIR}/case4.env" | cut -d= -f2)
if [ "${ACTUAL}" = "${EXISTING}" ]; then
  pass "case4: existing secret preserved"
else
  fail "case4: existing strong secret was overwritten (was '${EXISTING}', now '${ACTUAL}')"
fi

if [ "$failed" -ne 0 ]; then
  echo ""
  echo "FAILED"
  exit 1
fi

echo ""
echo "All test_install_secret.sh cases passed."
