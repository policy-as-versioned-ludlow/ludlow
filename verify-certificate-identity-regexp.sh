#!/usr/bin/env bash
# Ticket cs-14: proves release.yml's EXPECTED_IDENTITY_REGEXP matches main and
# the release/<major>.<minor>.x maintenance-branch shape, and rejects a
# foreign org/repo. Offline, no cluster needed -- pure regexp check against
# gitsign's actual --certificate-identity-regexp string (RE2; bash's ERE is a
# safe stand-in here since the pattern uses no RE2-only syntax).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }

REGEXP=$(grep -oE 'EXPECTED_IDENTITY_REGEXP: .*' "$HERE/.github/workflows/release.yml" \
  | sed 's/^EXPECTED_IDENTITY_REGEXP: //')
[ -n "$REGEXP" ] || fail "could not extract EXPECTED_IDENTITY_REGEXP from release.yml"
echo "pattern: $REGEXP"

check() { # identity, want (match|reject)
  local id="$1" want="$2" got=reject
  [[ "$id" =~ $REGEXP ]] && got=match
  [ "$got" = "$want" ] || fail "$id -> $got, want $want"
  echo "OK ($want): $id"
}

# must match: own org/repo, main and a real maintenance branch shape
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/main" match
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/release/1.0.x" match
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/release/12.34.x" match

# must reject: foreign org, foreign repo, wrong workflow path, wrong ref shape,
# prefix/suffix smuggling that an unanchored or unescaped pattern would allow
check "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-ludlow/other-repo/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/other.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/maint/1.0" reject
check "https://evil.example/https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/main.evil.example" reject
# the dot before "github" must be literal, not "any character"
check "https://githubXcom/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/main" reject
# the PROPOSER's identity is not a publisher's identity (ticket 78): propose-tier.yml
# signs cage-tier proposal COMMITS with this repo's own Actions identity, and a
# release TAG must never verify under it, or a workflow that may only propose
# could publish
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/main" reject

echo "PASS: EXPECTED_IDENTITY_REGEXP matches only policy-as-versioned-ludlow/ludlow's cut-release.yml on main or release/<major>.<minor>.x."

echo
echo "== EXPECTED_PROPOSAL_IDENTITY_REGEXP (propose-tier.yml -- the cage-tier proposal commit, ticket 78) =="
# A SECOND constant, deliberately not an alternation widened into the one above:
# proposing a tighter cage and publishing a release are different powers, and the
# identity that holds one must not hold the other.
PROPOSAL_REGEXP=$(grep -oE 'EXPECTED_PROPOSAL_IDENTITY_REGEXP: .*' "$HERE/.github/workflows/propose-tier.yml" \
  | sed 's/^EXPECTED_PROPOSAL_IDENTITY_REGEXP: //')
[ -n "$PROPOSAL_REGEXP" ] || fail "no EXPECTED_PROPOSAL_IDENTITY_REGEXP in propose-tier.yml -- the proposal commit's signature would be verified against nothing"
echo "pattern: $PROPOSAL_REGEXP"

check_proposal() { # identity, want (match|reject)
  local id="$1" want="$2" got=reject
  [[ "$id" =~ $PROPOSAL_REGEXP ]] && got=match
  [ "$got" = "$want" ] || fail "$id -> $got, want $want (proposal regexp)"
  echo "OK ($want): $id"
}

# what propose-tier.yml's own run presents. `refs/heads/main` is the ref the
# WORKFLOW runs on (schedule, dispatch, merged pin bump), never the
# `wargamer/retune-*` branch it writes.
check_proposal "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/main" match

# the publisher's identity must not verify a proposal, and neither may a
# maintenance branch, the branch the proposal is written to, a foreign
# org/repo/path, or a smuggled prefix/suffix
check_proposal "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/main" reject
check_proposal "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/release/1.0.x" reject
check_proposal "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/wargamer/retune-tier-ludlow-cage-tier-feeds-feed" reject
check_proposal "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/main" reject
check_proposal "https://github.com/policy-as-versioned-ludlow/other-repo/.github/workflows/propose-tier.yml@refs/heads/main" reject
check_proposal "https://evil.example/https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/main" reject
check_proposal "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/main.evil.example" reject
check_proposal "https://githubXcom/policy-as-versioned-ludlow/ludlow/.github/workflows/propose-tier.yml@refs/heads/main" reject

echo "PASS: EXPECTED_PROPOSAL_IDENTITY_REGEXP matches only policy-as-versioned-ludlow/ludlow's propose-tier.yml on main; the release and proposal identities do not overlap."
