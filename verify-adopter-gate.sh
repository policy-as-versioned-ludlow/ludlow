#!/usr/bin/env bash
# Ticket cs-28's own offline twin. Runs the SAME code shift-left.yml runs --
# .github/scripts/adopter_gate.py's CLI, not a re-implementation -- against
# real, throwaway git repositories built here, plus the real `cosign`
# binary. Three parts:
#
#   Part A -- the identity regexp, pure and offline (same technique ticket
#   cs-14's own verify-certificate-identity-regexp.sh already proved out):
#   match/reject cases against ADOPTER_GATE_IDENTITY_REGEXP as it actually
#   sits in shift-left.yml, including the "platform workflow rename breaks
#   verification" acceptance criterion and a cross-check that this constant
#   is NOT accidentally release.yml's own (different) identity.
#
#   Part B -- the git-and-YAML mechanics, for real: throwaway "platform" and
#   "ludlow" git repos, real commits, real tags, real `git show`/`rev-parse`.
#   Proves the resolved-commit refusal, the retirement-forces-major rule,
#   the composed-major hard failure, and the "weaker than the publisher's
#   tag never lowers anything" informational path -- none of these need
#   cosign at all (a retired or unchanged version carries no evidence
#   lookup by construction; adopter_gate.py's own selfcheck already proves
#   compose()'s pure strictest-wins math against fabricated evidence dicts,
#   so this part exercises the SURROUNDING wiring -- pin diffing, git
#   reads, CLI exit codes, comment rendering -- that the selfcheck cannot).
#
#   Part C -- the real `cosign verify-blob` binary, invoked for real against
#   a deliberately-invalid bundle for a genuinely CHANGED version. Proves
#   the gate really calls cosign and really refuses when cosign refuses --
#   not a mocked "assume it would fail".
#
# What this file does NOT prove, and cannot, offline: that cosign
# verify-blob ACCEPTS a genuinely valid bundle, identity-pinned to
# platform's real cut-release.yml Actions OIDC identity. Minting one needs
# a live GitHub Actions ambient credential (Fulcio keyless signing, no
# static key). Confirmed, not assumed: `cosign sign-blob --yes` was run in
# this same sandbox and hung waiting on an interactive OIDC/browser flow --
# no ambient credential exists here. This is the same CI-only boundary
# ticket cs-13's and cs-27's own offline twins already disclose (cs-27's
# CUT_RELEASE_TEST_MODE swaps only the `cosign sign-blob` call, nothing
# else); the accept-path here is exercised in real GitHub Actions runs,
# never locally.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$HERE/.github/scripts/adopter_gate.py"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
say() { echo; echo "== $* =="; }

# ---------------------------------------------------------------------------
say "Part A: ADOPTER_GATE_IDENTITY_REGEXP, pure and offline"
# ---------------------------------------------------------------------------

REGEXP=$(grep -oE 'ADOPTER_GATE_IDENTITY_REGEXP: .*' "$HERE/.github/workflows/shift-left.yml" \
  | sed 's/^ADOPTER_GATE_IDENTITY_REGEXP: //')
[ -n "$REGEXP" ] || fail "could not extract ADOPTER_GATE_IDENTITY_REGEXP from shift-left.yml"
echo "pattern: $REGEXP"

check() { # identity, want (match|reject)
  local id="$1" want="$2" got=reject
  [[ "$id" =~ $REGEXP ]] && got=match
  [ "$got" = "$want" ] || fail "$id -> $got, want $want"
  echo "OK ($want): $id"
}

# must match: platform's own org/repo, main and a real maintenance branch shape
check "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main" match
check "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/release/1.0.x" match
check "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/release/12.34.x" match

# must reject: a foreign org (including THIS repo, ludlow itself -- the
# adopter gate must not accept its own identity for platform's evidence),
# wrong workflow path (proves "a platform workflow rename breaks
# verification" -- the acceptance criterion, exercised directly), wrong ref
# shape, prefix/suffix smuggling
check "https://github.com/policy-as-versioned-ludlow/ludlow/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-platform/other-repo/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release-v2.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/maint/1.0" reject
check "https://evil.example/https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main" reject
check "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main.evil.example" reject
check "https://githubXcom/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main" reject

# this repo's own release.yml identity (ticket cs-14, verifies LUDLOW's own
# cut-release.yml) must NOT satisfy the adopter gate's constant -- these are
# two different identities on purpose (see shift-left.yml's own comment).
LUDLOW_RELEASE_REGEXP=$(grep -oE 'EXPECTED_IDENTITY_REGEXP: .*' "$HERE/.github/workflows/release.yml" \
  | sed 's/^EXPECTED_IDENTITY_REGEXP: //')
[ "$LUDLOW_RELEASE_REGEXP" != "$REGEXP" ] || fail "adopter gate's identity regexp must not equal release.yml's own"
echo "OK: ADOPTER_GATE_IDENTITY_REGEXP differs from release.yml's own EXPECTED_IDENTITY_REGEXP"

echo "PASS: ADOPTER_GATE_IDENTITY_REGEXP matches only policy-as-versioned-platform/platform's cut-release.yml, main or release/<major>.<minor>.x; a workflow rename breaks it."

# ---------------------------------------------------------------------------
say "Part B: real git repos, real commits, real tags -- the pin/diff/compose wiring"
# ---------------------------------------------------------------------------

mkgit() {
  mkdir -p "$1" && git -C "$1" init -q -b main
  git -C "$1" config user.email t@example.invalid
  git -C "$1" config user.name t
  # throwaway test repos, no real Sigstore/SSH signing needed -- avoid this
  # machine's own global commit/tag signing config (this repo's real commits
  # are still gitsign/cosign-signed for real, elsewhere; these are fixtures).
  git -C "$1" config commit.gpgsign false
  git -C "$1" config tag.gpgsign false
}

versions_yaml() {  # $1: python list-of-dicts literal for `versions`
  cat <<YAML
apiVersion: fluxcd.controlplane.io/v1
kind: ResourceSet
metadata: { name: policy-versions, namespace: flux-system }
spec:
  inputs:
    - versions: $1
YAML
}

pin_yaml() {  # $1: tag, $2: commit
  cat <<YAML
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata: { name: platform, namespace: flux-system }
spec:
  ref: { tag: "$1", commit: "$2" }
YAML
}

commit_all() { git -C "$1" add -A && git -C "$1" commit -q -m "$2"; }
sha_of() { git -C "$1" rev-parse HEAD; }

echo "-- building a throwaway platform repo: v0.1.0 (2.0.0 + 3.0.0 live), v1.0.0 (2.0.0 retired) --"
platform="$scratch/platform"
mkgit "$platform"
mkdir -p "$platform/distribution"
versions_yaml '[{version: "2.0.0", tag: "policy/v2.0.0", commit: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, {version: "3.0.0", tag: "policy/v3.0.0", commit: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]' > "$platform/distribution/versions.yaml"
commit_all "$platform" "v0.1.0: 2.0.0 and 3.0.0 both live"
git -C "$platform" tag v0.1.0
sha_v010=$(sha_of "$platform")

versions_yaml '[{version: "3.0.0", tag: "policy/v3.0.0", commit: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]' > "$platform/distribution/versions.yaml"
commit_all "$platform" "v1.0.0: retire 2.0.0, 3.0.0 unchanged"
git -C "$platform" tag v1.0.0
sha_v100=$(sha_of "$platform")

echo "-- building the matching throwaway ludlow repo: base pins v0.1.0, head pins v1.0.0 --"
ludlow="$scratch/ludlow"
mkgit "$ludlow"
mkdir -p "$ludlow/gitops/platform"
pin_yaml "v0.1.0" "$sha_v010" > "$ludlow/gitops/platform/platform-pin.yaml"
commit_all "$ludlow" "pin platform v0.1.0"
old_ref=$(sha_of "$ludlow")

pin_yaml "v1.0.0" "$sha_v100" > "$ludlow/gitops/platform/platform-pin.yaml"
commit_all "$ludlow" "bump platform pin to v1.0.0 (renovate)"
new_ref=$(sha_of "$ludlow")

run_gate() { # old_ref new_ref out_file log_file  -> exit code, python's own stdout/stderr go to log_file
  set +e
  python3 "$GATE" --ludlow-dir "$ludlow" --platform-dir "$platform" \
    --old-ref "$1" --new-ref "$2" --out-comment "$3" \
    --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" \
    > "$4" 2>&1
  local code=$?
  set -e
  echo "$code"
}

echo
echo "B1. retirement -> composed MAJOR -> the pull request check must fail (no cosign needed: the retired version has no evidence to look up)"
code=$(run_gate "$old_ref" "$new_ref" "$scratch/b1.md" "$scratch/b1.out")
cat "$scratch/b1.out"
[ "$code" -eq 1 ] || fail "B1: expected exit 1 (refused), got $code"
grep -q "2.0.0" "$scratch/b1.md" || fail "B1: comment does not name the retired version 2.0.0"
grep -qi "retired" "$scratch/b1.md" || fail "B1: comment does not say 'retired'"
grep -q "\*\*major\*\*" "$scratch/b1.md" || fail "B1: comment does not show composed bump as major"
echo "OK: retirement of 2.0.0 correctly refused the pull request check, comment names it"

echo
echo "B2. resolved-commit mismatch -> refuse (ADR-0001's pin made load-bearing, bug #2)"
tamper="$scratch/ludlow-tamper"
cp -r "$ludlow" "$tamper"
pin_yaml "v1.0.0" "cccccccccccccccccccccccccccccccccccccccc" > "$tamper/gitops/platform/platform-pin.yaml"
commit_all "$tamper" "tamper: wrong commit for v1.0.0"
tamper_new_ref=$(sha_of "$tamper")
set +e
python3 "$GATE" --ludlow-dir "$tamper" --platform-dir "$platform" \
  --old-ref "$old_ref" --new-ref "$tamper_new_ref" --out-comment "$scratch/b2.md" \
  --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" > "$scratch/b2.out" 2>&1
b2_code=$?
set -e
cat "$scratch/b2.out"
[ "$b2_code" -eq 1 ] || fail "B2: expected exit 1 (resolved-commit mismatch refused), got $b2_code"
grep -q "resolves to" "$scratch/b2.out" || fail "B2: refusal reason does not name the resolved-commit mismatch"
echo "OK: a pin naming the wrong commit for a real tag is refused, real git rev-parse caught it"

echo
echo "B3. composed weaker than the publisher's tag (unchanged array, major tag jump) -> informational, exit 0, never lowers"
platform2="$scratch/platform2"
mkgit "$platform2"; mkdir -p "$platform2/distribution"
versions_yaml '[{version: "3.0.0", tag: "policy/v3.0.0", commit: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]' > "$platform2/distribution/versions.yaml"
commit_all "$platform2" "v0.1.0: 3.0.0 only"
git -C "$platform2" tag v0.1.0
p2_old=$(sha_of "$platform2")
commit_all_noop() { git -C "$1" commit -q --allow-empty -m "$2"; }
commit_all_noop "$platform2" "v1.0.0: no array change, unrelated platform bump"
git -C "$platform2" tag v1.0.0
p2_new=$(sha_of "$platform2")

ludlow2="$scratch/ludlow2"
mkgit "$ludlow2"; mkdir -p "$ludlow2/gitops/platform"
pin_yaml "v0.1.0" "$p2_old" > "$ludlow2/gitops/platform/platform-pin.yaml"
commit_all "$ludlow2" "pin v0.1.0"
l2_old=$(sha_of "$ludlow2")
pin_yaml "v1.0.0" "$p2_new" > "$ludlow2/gitops/platform/platform-pin.yaml"
commit_all "$ludlow2" "bump pin to v1.0.0"
l2_new=$(sha_of "$ludlow2")

set +e
python3 "$GATE" --ludlow-dir "$ludlow2" --platform-dir "$platform2" \
  --old-ref "$l2_old" --new-ref "$l2_new" --out-comment "$scratch/b3.md" \
  --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" > "$scratch/b3.out" 2>&1
b3_code=$?
set -e
cat "$scratch/b3.out"
[ "$b3_code" -eq 0 ] || fail "B3: composed weaker than declared must NOT fail the check, got exit $b3_code"
grep -qi "never lowers" "$scratch/b3.md" || fail "B3: comment does not carry the 'never lowers' informational note"
grep -q "composed (this institution) |" "$scratch/b3.md" || fail "B3: comment missing the declared-vs-composed table"
grep -q "| bump | \*\*major\*\* | \*\*none\*\* |" "$scratch/b3.md" || fail "B3: expected declared=major, composed=none in the side-by-side table"
echo "OK: composed=none against declared=major (v0.1.0 -> v1.0.0) passes, prints informational, never fails"

# ---------------------------------------------------------------------------
say "Part C: real cosign verify-blob, invoked for real, against a deliberately-invalid bundle"
# ---------------------------------------------------------------------------

echo "-- a CHANGED version whose evidence file exists but whose bundle is not a real Sigstore bundle --"
platform3="$scratch/platform3"
mkgit "$platform3"; mkdir -p "$platform3/distribution" "$platform3/computed-semver/evidence"
versions_yaml '[{version: "3.0.0", tag: "policy/v3.0.0", commit: "cccccccccccccccccccccccccccccccccccccccc"}]' > "$platform3/distribution/versions.yaml"
commit_all "$platform3" "v0.1.0: 3.0.0 (old commit field is a placeholder -- never looked up, only the CHANGED entry's commit is)"
git -C "$platform3" tag v0.1.0
p3_old=$(sha_of "$platform3")

echo '{"outcome":{"result":"passed","reason":null},"bump":{"declared":"major","computed":"major"}}' > "$platform3/computed-semver/evidence/3.0.0.json"
echo 'this is not a real cosign sigstore bundle' > "$platform3/computed-semver/evidence/3.0.0.json.bundle"
commit_all "$platform3" "v1.0.0: 3.0.0 moves to a new (still-fake) evidence commit, with an invalid bundle"
new_evidence_commit=$(sha_of "$platform3")
versions_yaml "[{version: \"3.0.0\", tag: \"policy/v3.0.0\", commit: \"$new_evidence_commit\"}]" > "$platform3/distribution/versions.yaml"
commit_all "$platform3" "v1.0.0: point the array at the evidence commit"
git -C "$platform3" tag v1.0.0
p3_new=$(sha_of "$platform3")

ludlow3="$scratch/ludlow3"
mkgit "$ludlow3"; mkdir -p "$ludlow3/gitops/platform"
pin_yaml "v0.1.0" "$p3_old" > "$ludlow3/gitops/platform/platform-pin.yaml"
commit_all "$ludlow3" "pin v0.1.0"
l3_old=$(sha_of "$ludlow3")
pin_yaml "v1.0.0" "$p3_new" > "$ludlow3/gitops/platform/platform-pin.yaml"
commit_all "$ludlow3" "bump pin to v1.0.0"
l3_new=$(sha_of "$ludlow3")

set +e
python3 "$GATE" --ludlow-dir "$ludlow3" --platform-dir "$platform3" \
  --old-ref "$l3_old" --new-ref "$l3_new" --out-comment "$scratch/c1.md" \
  --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" > "$scratch/c1.out" 2>&1
c1_code=$?
set -e
cat "$scratch/c1.out"
[ "$c1_code" -eq 1 ] || fail "C1: an invalid bundle must be refused by the REAL cosign binary, got exit $c1_code"
grep -qi "cosign verify-blob refused" "$scratch/c1.out" || fail "C1: refusal reason does not name cosign's own refusal"
echo "OK: cosign (the real binary) was invoked against the invalid bundle and refused it; the gate propagated that as a hard refusal"

echo
echo "-- a CHANGED version with no committed evidence file at all --"
platform4="$scratch/platform4"
mkgit "$platform4"; mkdir -p "$platform4/distribution"
versions_yaml '[{version: "3.0.0", tag: "policy/v3.0.0", commit: "cccccccccccccccccccccccccccccccccccccccc"}]' > "$platform4/distribution/versions.yaml"
commit_all "$platform4" "v0.1.0: seed (old commit field is a placeholder, never looked up)"
git -C "$platform4" tag v0.1.0
p4_old=$(sha_of "$platform4")
commit_all_noop "$platform4" "v1.0.0 target commit -- carries no evidence file for 3.0.0"
new_commit_no_evidence=$(sha_of "$platform4")
versions_yaml "[{version: \"3.0.0\", tag: \"policy/v3.0.0\", commit: \"$new_commit_no_evidence\"}]" > "$platform4/distribution/versions.yaml"
commit_all "$platform4" "v1.0.0: point array at a commit with no evidence"
git -C "$platform4" tag v1.0.0
p4_new=$(sha_of "$platform4")

ludlow4="$scratch/ludlow4"
mkgit "$ludlow4"; mkdir -p "$ludlow4/gitops/platform"
pin_yaml "v0.1.0" "$p4_old" > "$ludlow4/gitops/platform/platform-pin.yaml"
commit_all "$ludlow4" "pin v0.1.0"
l4_old=$(sha_of "$ludlow4")
pin_yaml "v1.0.0" "$p4_new" > "$ludlow4/gitops/platform/platform-pin.yaml"
commit_all "$ludlow4" "bump pin to v1.0.0"
l4_new=$(sha_of "$ludlow4")

set +e
python3 "$GATE" --ludlow-dir "$ludlow4" --platform-dir "$platform4" \
  --old-ref "$l4_old" --new-ref "$l4_new" --out-comment "$scratch/c2.md" \
  --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" > "$scratch/c2.out" 2>&1
c2_code=$?
set -e
cat "$scratch/c2.out"
[ "$c2_code" -eq 1 ] || fail "C2: a changed version with no committed evidence must refuse, got exit $c2_code"
grep -qi "no committed evidence" "$scratch/c2.out" || fail "C2: refusal reason does not say evidence is missing"
echo "OK: a changed version with no committed evidence file is refused before cosign is even invoked"

echo
echo "PASS: verify-adopter-gate.sh -- identity regexp (match/reject/rename-breaks-it), resolved-commit refusal,"
echo "      retirement-forces-major, composed-major fails the check, weaker-than-declared is informational-only,"
echo "      and the real cosign binary genuinely refuses an invalid bundle and a missing one -- all real git,"
echo "      real YAML, real cosign, offline. NOT exercised here (CI-only, confirmed): cosign accepting a"
echo "      genuinely valid Fulcio-signed bundle -- no ambient OIDC credential exists on this machine."
