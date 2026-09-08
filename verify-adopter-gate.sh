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
#   Part C -- a genuinely CHANGED version whose committed bundle this gate
#   cannot read, and one with no evidence committed at all. Both refuse by
#   name, BEFORE cosign is invoked: choosing which pinned trust material
#   verifies a bundle means reading the bundle, and calling cosign without
#   it is the live TUF fetch the committed root exists to prevent (ticket
#   101). That cosign itself is really called, and really refuses, is
#   proved in Part E against bytes platform actually published -- which is
#   a stronger place to prove it than a fixture this file wrote.
#
#   Part E -- platform's REAL PUBLISHED evidence, read from a real clone of
#   platform at the tag this repository actually pins, verified by the real
#   cosign binary through adopter_gate.py's OWN invocation, with a cold TUF
#   cache and every route to the network hard-blocked. A real ACCEPT and
#   three real REFUSES, all on bytes platform published.
#
# WHAT WAS DISCLOSED HERE UNTIL 2026-09-06, AND WHY IT IS GONE. This header
# used to say that it "does NOT prove, and cannot, offline: that cosign
# verify-blob ACCEPTS a genuinely valid bundle", and that "the accept-path
# here is exercised in real GitHub Actions runs, never locally". Both had
# stopped being true and nothing re-read them. A disclosed limit is an
# assertion and goes stale like any other: this estate grades its PASS lines
# and graded none of its "cannot" lines, and that sentence went on excusing a
# gap that had become a defect -- the gate could not verify ANY bundle
# platform publishes (see Part E1), and the accept path had never run in CI
# either, because diff_versions() reaches verify_evidence() only when the
# composed member set moves. Part E now proves the accept for real, offline,
# in about a second. Signing NEW evidence is still out of reach here (Fulcio
# keyless signing needs a live Actions credential; `cosign sign-blob --yes`
# hangs on the interactive flow in this sandbox, confirmed 2026-09-06) --
# but VERIFYING what platform already signed never needed one. Every limit
# left in this file is dated, or printed as a number by the run itself.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$HERE/.github/scripts/adopter_gate.py"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

# Hermetic against the operator's own git configuration (eco-system ticket 101, 2026-09-06). Every
# repository below is a throwaway fixture, and a global `core.hooksPath` hook has no business
# running in one: on 2026-09-06 this machine's hook ran out of API calls and every `git commit`
# here began failing, which is a harness that cannot run for a reason that has nothing to do with
# what it grades. The hub's fold_agreement.py had the same exposure and it was worse there -- the
# failed commit was silent and the grader reported agreement it had not observed.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

fail() { echo "FAIL: $*" >&2; exit 1; }
skip() { echo "SKIP: $*"; exit 3; }
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
say "Part C: a bundle this gate cannot read, and a missing one -- refused by name, before cosign"
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
[ "$c1_code" -eq 1 ] || fail "C1: a bundle that is neither cosign shape must be refused, got exit $c1_code"
grep -qi "is neither a legacy cosign bundle" "$scratch/c1.out" \
  || fail "C1: the refusal does not name the bundle shape as the reason"
grep -qi "refusing rather than handing cosign no trust root" "$scratch/c1.out" \
  || fail "C1: the refusal does not say why it stops here rather than calling cosign without pinned trust material"
echo "OK: a bundle whose shape this gate cannot read is refused by name, and no cosign call is made without pinned trust material"

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

# ---------------------------------------------------------------------------
say "Part D: splice_body via the REAL CLI, with backslash-bearing evidence -- the exact re.sub() hazard"
# ---------------------------------------------------------------------------
# A Kyverno/CEL match expression -- the same idiom parse_semver() uses on
# this repo's own tags -- reaching the pull request body via splice_body().
# A raw-string re.sub() replacement misreads \d as a backreference and
# raises re.PatternError on this exact input; adopter_gate.py's selfcheck
# proves the pure function survives it, this proves the real --splice-body
# CLI shift-left.yml actually invokes does too, and that a re-run replaces
# the prior span in place rather than crashing before it gets that far.

printf 'Bumps platform from v1.0.0 to v1.1.0.\n\n---\n\nRenovate config help.\n' > "$scratch/d-current-body.md"
printf '%s\n' \
  '<!-- cs-29:adopter-gate:start -->' \
  "- \`p.yaml\` -- **major** -- via \`matches(image, '^v\\\\d+\\\\.\\\\d+\\\\.\\\\d+\$')\`" \
  '<!-- cs-29:adopter-gate:end -->' \
  > "$scratch/d-section.md"
grep -q '\\d' "$scratch/d-section.md" || fail "D setup: fixture section does not actually contain a backslash-escape"

set +e
python3 "$GATE" --splice-body --current-body "$scratch/d-current-body.md" \
  --section "$scratch/d-section.md" --out-body "$scratch/d-out1.md" > "$scratch/d1.out" 2>&1
d1_code=$?
set -e
cat "$scratch/d1.out"
[ "$d1_code" -eq 0 ] || fail "D1: --splice-body crashed on backslash-bearing evidence, got exit $d1_code (this is the reported bug if it fails)"
grep -qF 'Renovate config help.' "$scratch/d-out1.md" || fail "D1: Renovate's own body content is missing after the first splice"
grep -q '\\d' "$scratch/d-out1.md" || fail "D1: the backslash-bearing expression did not survive into the spliced body"
echo "OK: first splice (append) survives backslash-bearing evidence, real CLI, exit 0"

set +e
python3 "$GATE" --splice-body --current-body "$scratch/d-out1.md" \
  --section "$scratch/d-section.md" --out-body "$scratch/d-out2.md" > "$scratch/d2.out" 2>&1
d2_code=$?
set -e
cat "$scratch/d2.out"
[ "$d2_code" -eq 0 ] || fail "D2: re-run --splice-body crashed on backslash-bearing evidence (re.PatternError: bad escape \\d is exactly this bug), got exit $d2_code"
diff -q "$scratch/d-out1.md" "$scratch/d-out2.md" > /dev/null || fail "D2: re-run over identical evidence must replace the span in place, byte-identical -- got a diff"
[ "$(grep -c 'cs-29:adopter-gate:start' "$scratch/d-out2.md")" -eq 1 ] || fail "D2: re-run must not nest or duplicate the markers"
echo "OK: re-run replaces the prior span in place, byte-identical, markers not duplicated -- real CLI, real re.sub(), backslashes and all"

# ---------------------------------------------------------------------------
say "Part E: platform's REAL PUBLISHED evidence, through this gate's own CLI, offline"
# ---------------------------------------------------------------------------
# Eco-system ticket 101, 2026-09-06. Until this part existed, no adopter gate
# in the estate had ever been observed verifying a signature platform actually
# published, and this one could not: adopter_gate.py passed --trusted-root
# with --new-bundle-format=true, and cosign v3.1.3 -- the version
# shift-left.yml installs by checksum -- answers "--trusted-root only
# supported with --new-bundle-format" to every bundle platform has published,
# because those are the LEGACY shape (base64Signature/cert/rekorBundle). The
# old Part E missed it by proving the offline property against a bundle it
# signed locally, which is in the NEW format -- a fixture whose shape happened
# to match the flag the served artefact does not have -- and by invoking
# cosign DIRECTLY rather than through the gate. Eco-system ticket 105
# (2026-09-09) moved the gate onto the --trusted-root door for EVERY bundle,
# re-encoding a legacy one locally first, so the whole committed root (every
# log, every validFor window) is what verifies; E2-E5 measure that door and
# E6 doctors the committed root one field at a time and grades a refusal on
# the trust material rather than on the network, cold and warm.
#
# So: the served artefact is platform's own committed
# computed-semver/evidence/<version>.json[.bundle] at the tag THIS repository
# pins, read out of a real clone. The operation is adopter_gate.py's own CLI,
# the one shift-left.yml runs, under this repository's own identity constant.
# Every invocation below runs with a cold TUF cache (HOME redirected) and with
# every proxy variable pointed at a closed port, so anything that needs the
# network fails instead of quietly succeeding off somebody's warm ~/.sigstore.

platform_repo="${PLATFORM_REPO:-$HERE/../platform}"
[ -d "$platform_repo/.git" ] \
  || skip "no clone of platform at $platform_repo (set PLATFORM_REPO=) -- this part verifies platform's real published evidence and there is nothing to read"

pinned_tag=$(python3 - "$HERE/gitops/platform/platform-pin.yaml" <<'PY'
import sys, yaml
for doc in yaml.safe_load_all(open(sys.argv[1])):
    if isinstance(doc, dict) and doc.get("kind") == "GitRepository":
        print((doc.get("spec") or {}).get("ref", {}).get("tag", ""))
        break
PY
)
[ -n "$pinned_tag" ] || fail "E setup: could not read the pinned platform tag out of this repository's own gitops/platform/platform-pin.yaml"
echo "this repository pins platform $pinned_tag"

e_platform="$scratch/platform-e"
git clone --local --quiet "$platform_repo" "$e_platform"
git -C "$e_platform" config advice.detachedHead false
git -C "$e_platform" rev-parse -q --verify "refs/tags/${pinned_tag}^{commit}" > /dev/null \
  || skip "the clone of platform at $platform_repo carries no tag object for ${pinned_tag}, the tag this repository pins -- it is behind the estate"
e_commit=$(git -C "$e_platform" rev-parse "refs/tags/${pinned_tag}^{commit}")
git -C "$e_platform" checkout --quiet "$pinned_tag"
git -C "$e_platform" config user.email t@example.invalid
git -C "$e_platform" config user.name t
git -C "$e_platform" config commit.gpgsign false
git -C "$e_platform" config tag.gpgsign false

# The version whose REAL signed evidence this part verifies: one that
# platform actually published a bundle for at this tag, and whose own
# computed bump is not major -- so a genuine ACCEPT can be observed as an
# ACCEPT and not read through a designed composed-major refusal. Chosen from
# the tag's own tree, never hard-coded: if platform's published set changes,
# this picks again rather than going stale.
e_version=$(python3 - "$e_platform" <<'PY'
import json, pathlib, subprocess, sys
root = pathlib.Path(sys.argv[1]) / "computed-semver" / "evidence"
picks = []
for doc in sorted(root.glob("*.json")):
    if doc.with_suffix(".json.bundle").exists():
        try:
            computed = json.loads(doc.read_text())["bump"]["computed"]
        except Exception:
            continue
        if computed != "major":
            picks.append((doc.name[:-5], computed))
print(picks[0][0] if picks else "")
PY
)
[ -n "$e_version" ] || skip "platform at ${pinned_tag} publishes no evidence document with a committed bundle whose own computed bump is below major, so an ACCEPT cannot be told apart from the designed composed-major refusal here"
e_bundle="$e_platform/computed-semver/evidence/${e_version}.json.bundle"
[ -s "$e_bundle" ] || fail "E setup: no committed bundle at computed-semver/evidence/${e_version}.json.bundle"
e_shape=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("legacy" if "base64Signature" in d else ("new" if "mediaType" in d else "unknown"))' "$e_bundle")
echo "platform's published bundle for policy ${e_version} at ${pinned_tag} is the ${e_shape} cosign bundle shape"

# The planted movement: this version ARRIVES in platform's supported array,
# so the gate must look its real evidence up and verify its real signature.
# Nothing about the evidence, the bundle or the certificate is planted -- only
# which versions the array names, which is the movement a Renovate pull
# request makes.
e_array_line=$(grep -n 'version: "' "$e_platform/distribution/versions.yaml" | head -1 | cut -d: -f1)
[ -n "$e_array_line" ] || fail "E setup: platform's distribution/versions.yaml at ${pinned_tag} names no version"
python3 - "$e_platform/distribution/versions.yaml" "$e_array_line" "$e_version" "$e_commit" <<'PY'
import sys
path, line_no, version, commit = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
lines = open(path).read().splitlines(keepends=True)
indent = " " * (len(lines[line_no - 1]) - len(lines[line_no - 1].lstrip()))
if f'version: "{version}"' in lines[line_no - 1]:
    del lines[line_no - 1]          # the version already stands: take it out of the OLD window
    line_no -= 1
open(path + ".old", "w").writelines(lines)
lines.insert(line_no, f'{indent}- {{ version: "{version}", tag: "policy/v{version}", commit: "{commit}" }}\n')
open(path + ".new", "w").writelines(lines)
PY
cp "$e_platform/distribution/versions.yaml.old" "$e_platform/distribution/versions.yaml"
rm -f "$e_platform/distribution/versions.yaml.old"
git -C "$e_platform" add -A && git -C "$e_platform" commit -q -m "planted: the window before ${e_version} arrives"
e_old_commit=$(git -C "$e_platform" rev-parse HEAD)
git -C "$e_platform" tag v9.0.0
mv "$e_platform/distribution/versions.yaml.new" "$e_platform/distribution/versions.yaml"
git -C "$e_platform" add -A && git -C "$e_platform" commit -q -m "planted: ${e_version} arrives, pointing at platform's own real evidence commit"
e_new_commit=$(git -C "$e_platform" rev-parse HEAD)
git -C "$e_platform" tag v9.1.0

e_ludlow="$scratch/ludlow-e"
mkgit "$e_ludlow"; mkdir -p "$e_ludlow/gitops/platform"
pin_yaml "v9.0.0" "$e_old_commit" > "$e_ludlow/gitops/platform/platform-pin.yaml"
commit_all "$e_ludlow" "pin the window before the arrival"
e_old_ref=$(sha_of "$e_ludlow")
pin_yaml "v9.1.0" "$e_new_commit" > "$e_ludlow/gitops/platform/platform-pin.yaml"
commit_all "$e_ludlow" "renovate: adopt the window in which ${e_version} stands"
e_new_ref=$(sha_of "$e_ludlow")

# Hard-blocked egress and a cold TUF cache, for every invocation in this
# part. HOME is redirected so no warm ~/.sigstore can stand in for the
# committed pin (adopter_gate.py also points TUF_ROOT at an empty directory
# it owns, which is the belt to this brace); the proxy variables point at a
# closed port, which is a deterministic failure that does not depend on this
# machine's firewall or DNS.
BLOCKED_PROXY="http://127.0.0.1:1"
# NO_PROXY is CLEARED, not just left alone (eco-system ticket 101 review, F2, 2026-09-06).
# Measured: with an ambient `NO_PROXY=*` exported, Go bypasses the closed port entirely, cosign
# reaches Sigstore's CDN, and this scenario prints exit 0 -- "no network needed" for a run that
# had just used the network. A measurement that fails in the REASSURING direction is worse than
# no measurement, because nobody looks behind a green one. The lowercase spellings are set too,
# because Go reads those as well.
offline() { HOME="$scratch/e-home" TUF_ROOT="$scratch/e-tuf" \
            HTTPS_PROXY="$BLOCKED_PROXY" HTTP_PROXY="$BLOCKED_PROXY" ALL_PROXY="socks5://127.0.0.1:1" \
            https_proxy="$BLOCKED_PROXY" http_proxy="$BLOCKED_PROXY" all_proxy="socks5://127.0.0.1:1" \
            NO_PROXY="" no_proxy="" timeout 60 "$@"; }
mkdir -p "$scratch/e-home" "$scratch/e-tuf"

run_gate_e() { # out_prefix identity_regexp platform_dir -> exit code
  set +e
  offline python3 "$GATE" --ludlow-dir "$e_ludlow" --platform-dir "$3" \
    --old-ref "$e_old_ref" --new-ref "$e_new_ref" --out-comment "$scratch/$1.md" \
    --identity-regexp "$2" --issuer "https://token.actions.githubusercontent.com" \
    > "$scratch/$1.out" 2>&1
  local code=$?
  set -e
  echo "$code"
}

echo
echo "-- E1: the invocation this gate shipped until 2026-09-06 -- --trusted-root with --new-bundle-format=true -- against platform's REAL published bundle --"
# Kept as a live measurement rather than a sentence, because the sentence is
# exactly what went stale last time. If a future cosign accepts this pairing
# against a legacy bundle, this fails and says so, and remedy 3 in eco-system
# ticket 101 becomes available.
set +e
e1_out=$(offline cosign verify-blob --bundle="$e_bundle" \
  --trusted-root="$HERE/.github/scripts/trusted_root.json" --new-bundle-format=true \
  --certificate-identity-regexp="$REGEXP" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  "$e_platform/computed-semver/evidence/${e_version}.json" 2>&1)
e1_code=$?
set -e
echo "$e1_out"
if [ "$e_shape" = "legacy" ]; then
  [ "$e1_code" -ne 0 ] || fail "E1: cosign now ACCEPTS --trusted-root against a legacy bundle -- the ticket 101 finding no longer holds and this gate should be simplified back onto it"
  echo "$e1_out" | grep -q -- "--trusted-root only supported with --new-bundle-format" \
    || fail "E1: the shipped-until-2026-09-06 invocation failed for a reason this part does not recognise: $e1_out"
  echo "OK: measured, not asserted -- the pre-2026-09-06 invocation still refuses platform's real published bundle on the FLAG, before it looks at the signature (cosign $(cosign version 2>/dev/null | awk '/GitVersion/{print $2}'))"
else
  echo "OK: platform now publishes ${e_shape}-format bundles, so the pre-2026-09-06 invocation is no longer wrong for the served artefact (exit ${e1_code})"
fi

echo
echo "-- E2: the REAL ACCEPT -- platform's real published evidence for policy ${e_version}, through adopter_gate.py's own CLI, cold TUF cache, egress blocked --"
e2_code=$(run_gate_e e2 "$REGEXP" "$e_platform")
cat "$scratch/e2.out"
[ "$e2_code" -eq 0 ] || fail "E2: the gate did not accept platform's real published evidence for ${e_version} (exit $e2_code) -- this is the ticket 101 defect if the reason names a flag"
grep -q "PASS: declared=" "$scratch/e2.out" || fail "E2: the gate did not reach its own PASS line"
grep -q "$e_version" "$scratch/e2.md" || fail "E2: the rendered evidence does not name policy ${e_version}"
grep -qiE "tuf|dial tcp|connection refused|trusted-root only supported" "$scratch/e2.out" \
  && fail "E2: the run reached (or tried to reach) the network, or refused on a flag -- not an offline verification of the served artefact"
echo "OK: real cosign ACCEPTED platform's own published signature for policy ${e_version} at ${pinned_tag}, under this repository's own identity constant, with a cold TUF cache and egress blocked -- and the gate adopted, exit 0"
echo "    (path, stated rather than implied: E2-E4 invoke the gate WITHOUT --composed-base-ref/--composed-head-ref,"
echo "     so they reach verify_evidence() through read_versions() -- platform's own distribution/versions.yaml array"
echo "     -- and not through versions_from_composed_evidence(), which is the path shift-left.yml passes. The two"
echo "     paths differ only in where the member set is read; the evidence lookup, the cosign invocation and the"
echo "     identity constant below them are the same code. The WORKFLOW'S path, flags and all, is what the hub's"
echo "     verify/real-signature/verify-a-real-signature-is-checked.sh runs, reading them out of shift-left.yml"
echo "     itself -- so between the two, both paths into this gate are graded. Eco-system ticket 101 review, F4.)"

echo
echo "-- E3: the REAL REFUSE -- the same real bundle with one signature byte changed --"
e3_platform="$scratch/platform-e3"
cp -r "$e_platform" "$e3_platform"
python3 - "$e3_platform/computed-semver/evidence/${e_version}.json.bundle" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path))
if "base64Signature" in doc:
    s = doc["base64Signature"]
    doc["base64Signature"] = ("B" if s[0] != "B" else "C") + s[1:]
else:
    sig = doc["messageSignature"]["signature"]
    doc["messageSignature"]["signature"] = ("B" if sig[0] != "B" else "C") + sig[1:]
json.dump(doc, open(path, "w"))
PY
git -C "$e3_platform" add -A && git -C "$e3_platform" commit -q -m "tamper: one byte of the real signature"
e3_evidence_commit=$(git -C "$e3_platform" rev-parse HEAD)
# The gate reads a version's evidence at the commit THAT VERSION'S OWN ARRAY
# ENTRY names, not at the pin's head commit -- so the planted entry has to
# point at the tampered commit, or the gate would read the untouched bytes
# and this would prove nothing. (It did exactly that on the first run here.)
python3 - "$e3_platform/distribution/versions.yaml" "$e_commit" "$e3_evidence_commit" <<'PY2'
import sys
path, old_commit, new_commit = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read()
assert old_commit in text, "the planted array entry no longer names the evidence commit"
open(path, "w").write(text.replace(old_commit, new_commit))
PY2
git -C "$e3_platform" add -A && git -C "$e3_platform" commit -q -m "planted: point the arriving entry at the tampered evidence commit"
git -C "$e3_platform" tag -f v9.1.0 > /dev/null 2>&1
e3_new_commit=$(git -C "$e3_platform" rev-parse HEAD)
# The pin has to name the tampered commit, or the gate refuses on the pin
# rather than on the signature -- and a refusal about a pin would prove
# nothing about cosign.
e3_ludlow="$scratch/ludlow-e3"
cp -r "$e_ludlow" "$e3_ludlow"
pin_yaml "v9.1.0" "$e3_new_commit" > "$e3_ludlow/gitops/platform/platform-pin.yaml"
commit_all "$e3_ludlow" "renovate: adopt the tampered window"
e3_new_ref=$(sha_of "$e3_ludlow")
set +e
offline python3 "$GATE" --ludlow-dir "$e3_ludlow" --platform-dir "$e3_platform" \
  --old-ref "$e_old_ref" --new-ref "$e3_new_ref" --out-comment "$scratch/e3.md" \
  --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" \
  > "$scratch/e3.out" 2>&1
e3_code=$?
set -e
cat "$scratch/e3.out"
[ "$e3_code" -eq 1 ] || fail "E3: a tampered signature on platform's real bundle must refuse, got exit $e3_code"
grep -qi "cosign verify-blob refused" "$scratch/e3.out" || fail "E3: the refusal does not name cosign's own refusal"
grep -qi "signature\|verif" "$scratch/e3.out" || fail "E3: the refusal is not about the signature"
grep -qi "trusted-root only supported" "$scratch/e3.out" \
  && fail "E3: the refusal is about a command line, not about a signature -- the ticket 101 defect"
echo "OK: real cosign REFUSED the same real bundle with one signature byte changed, offline, and the gate propagated it as a refusal about the SIGNATURE"

echo
echo "-- E4: the identity pin is load-bearing against a real Fulcio certificate, not just against a string --"
e4_code=$(run_gate_e e4 '^https://github\.com/evil-org/platform/\.github/workflows/cut-release\.yml@refs/heads/main$' "$e_platform")
cat "$scratch/e4.out"
[ "$e4_code" -eq 1 ] || fail "E4: a foreign identity regexp must refuse platform's real evidence, got exit $e4_code"
grep -qi "cosign verify-blob refused" "$scratch/e4.out" || fail "E4: the refusal does not name cosign's own refusal"
grep -qiE "none of the expected identities matched|no matching CertificateIdentity found" "$scratch/e4.out" \
  || fail "E4: the refusal does not name an identity mismatch -- it may have failed for some other reason"
echo "OK: the same real, valid bundle is REFUSED when the identity constant names a foreign publisher -- the certificate is really being read"

echo
echo "-- E5: the contrast -- the same real bundle with NO pinned trust material, cold cache, egress blocked --"
# What the pin buys, measured rather than claimed: with a cold TUF cache and
# no network, an unpinned verification of the very same bytes fails on the
# trust root. It PASSES on a laptop with a warm ~/.sigstore, which is exactly
# why the cache is cold here.
set +e
e5_out=$(offline cosign verify-blob --bundle="$e_bundle" \
  --certificate-identity-regexp="$REGEXP" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" \
  "$e_platform/computed-semver/evidence/${e_version}.json" 2>&1)
e5_code=$?
set -e
echo "$e5_out"
# The NUMBER, printed, not only asserted: ticket 101 and ticket 105 both cite this line as the
# exit code ludlow's harness prints on every run, the way driftwood's and tuppence's scenario G
# do, and a harness that only asserts non-zero prints no number anyone can quote.
echo "the same real bundle (policy ${e_version}) WITHOUT the committed trust material, cold TUF cache, every proxy pointed at a closed port: exit ${e5_code}"
[ "$e5_code" -ne 0 ] || fail "E5: an unpinned verification succeeded with a cold TUF cache and blocked egress -- the cache is not actually cold, so E2's offline claim is not being proved"
echo "$e5_out" | grep -qiE "tuf|dial tcp|connection refused" \
  || fail "E5: the unpinned verification failed for a reason that is not the network: $e5_out"
echo "OK: without the committed trust material the identical bytes cannot be verified offline at all -- the pin is what makes E2 offline, and it is measured on this run, not asserted"

echo
echo "-- E6: the pin is load-bearing -- a wrong, corrupt, retired or absent trust root REFUSES, cold and warm --"
# The pin is load-bearing (eco-system ticket 105). Each case copies this repository's own gate
# beside a DOCTORED copy of its committed trusted_root.json -- one field changed, named -- and
# runs it against platform's REAL, untampered bundle with a cold TUF cache and every proxy
# pointed at a closed port. Every case must REFUSE, and refuse on the trust material, never on
# the network: a refusal that mentions a TUF fetch would mean the gate went looking for a root
# it was not given, which is the fallback the pin exists to rule out. `genuine` runs the same
# copied gate with the real root and must ACCEPT, so that a broken copy cannot make every other
# case a vacuous refusal.
doctor_root() {  # $1 case, $2 source trusted_root.json, $3 destination
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
case, src, dst = sys.argv[1:]
root = json.load(open(src))
ct_current = next(log for log in root["ctlogs"] if "end" not in log["publicKey"]["validFor"])
if case == "genuine":
    pass
elif case == "wrong-rekor-key":            # the Rekor log id stays; its key is the CT log's (same key type, so the root loads and the SET check is what refuses)
    for log in root["tlogs"]:
        if log["publicKey"].get("keyDetails") == ct_current["publicKey"].get("keyDetails"):
            log["publicKey"]["rawBytes"] = ct_current["publicKey"]["rawBytes"]
elif case == "corrupt-rekor-key":          # not a key at all
    for log in root["tlogs"]:
        log["publicKey"]["rawBytes"] = "AAAA"
elif case == "wrong-ct-key":               # the CT log id stays; its key is Rekor's
    for log in root["ctlogs"]:
        log["publicKey"]["rawBytes"] = root["tlogs"][0]["publicKey"]["rawBytes"]
elif case == "wrong-fulcio-root":          # every CA chain replaced by the timestamp authority's
    tsa = root["timestampAuthorities"][0]["certChain"]
    root["certificateAuthorities"] = [dict(ca, certChain=tsa) for ca in root["certificateAuthorities"]]
elif case == "ct-window-closed":           # the current CT key retired before the artefact was signed
    ct_current["publicKey"]["validFor"]["end"] = "2026-01-01T00:00:00Z"
else:
    raise SystemExit(f"unknown case {case}")
json.dump(root, open(dst, "w"))
PY
}

e6_root="$HERE/.github/scripts/trusted_root.json"
attack() {  # $1 case, $2 "cold"|"warm" -> exit code on stdout, output in $scratch/e6-<case>-<home>.out
  local dir="$scratch/gate-$1"; mkdir -p "$dir"; cp "$GATE" "$dir/adopter_gate.py"
  [ "$1" = absent-root ] || doctor_root "$1" "$e6_root" "$dir/trusted_root.json"
  set +e
  if [ "$2" = warm ]; then
    HOME="$HOME" TUF_ROOT="$scratch/e-tuf" \
      HTTPS_PROXY="$BLOCKED_PROXY" HTTP_PROXY="$BLOCKED_PROXY" ALL_PROXY="socks5://127.0.0.1:1" \
      https_proxy="$BLOCKED_PROXY" http_proxy="$BLOCKED_PROXY" all_proxy="socks5://127.0.0.1:1" \
      NO_PROXY="" no_proxy="" timeout 60 python3 "$dir/adopter_gate.py" --ludlow-dir "$e_ludlow" --platform-dir "$e_platform" \
      --old-ref "$e_old_ref" --new-ref "$e_new_ref" --out-comment "$scratch/e6-$1-$2.md" \
      --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" > "$scratch/e6-$1-$2.out" 2>&1
  else
    offline python3 "$dir/adopter_gate.py" --ludlow-dir "$e_ludlow" --platform-dir "$e_platform" \
      --old-ref "$e_old_ref" --new-ref "$e_new_ref" --out-comment "$scratch/e6-$1-$2.md" \
      --identity-regexp "$REGEXP" --issuer "https://token.actions.githubusercontent.com" > "$scratch/e6-$1-$2.out" 2>&1
  fi
  local code=$?
  set -e
  echo "$code"
}
e6_ok=$(attack genuine cold)
[ "$e6_ok" -eq 0 ] || fail "E6: the copied gate with the GENUINE root did not accept (exit $e6_ok), so nothing below would mean anything: $(tail -1 "$scratch/e6-genuine-cold.out")"
echo "OK: E6[genuine] -- the copied gate with the real committed root ACCEPTS, cold (exit 0); the copy mechanism is sound"
for case in absent-root wrong-rekor-key corrupt-rekor-key wrong-ct-key wrong-fulcio-root ct-window-closed; do
  for home in cold warm; do
    code=$(attack "$case" "$home")
    tail_line=$(tail -1 "$scratch/e6-$case-$home.out")
    [ "$code" -ne 0 ] || fail "E6[$case,$home]: the gate ACCEPTED platform's bundle with a doctored trust root -- the pin is not load-bearing"
    if [ "$case" = absent-root ]; then
      grep -q "no committed Sigstore trust root" "$scratch/e6-$case-$home.out" \
        || fail "E6[$case,$home]: the refusal does not name the absent root: $tail_line"
    else
      grep -qi "cosign verify-blob refused" "$scratch/e6-$case-$home.out" \
        || fail "E6[$case,$home]: the refusal is not cosign's own: $tail_line"
    fi
    grep -qiE "tuf: |dial tcp|connection refused" "$scratch/e6-$case-$home.out" \
      && fail "E6[$case,$home]: the refusal mentions the network -- the gate went looking for a root it was not given: $tail_line"
    echo "OK: E6[$case,$home] -- REFUSED, exit ${code}, on the trust material and not the network: $(echo "$tail_line" | cut -c1-150)"
  done
done
echo "    (warm = this machine's own HOME, whose ~/.sigstore is warm on a laptop that has ever run cosign online and cold on a CI runner; either way the doctored root, not a cached one, is what refused)"

echo
echo "PASS: verify-adopter-gate.sh -- identity regexp (match/reject/rename-breaks-it), resolved-commit refusal,"
echo "      retirement-forces-major, composed-major fails the check, weaker-than-declared is informational-only,"
echo "      a bundle shape this gate cannot read is refused by name and a missing evidence file before that,"
echo "      --splice-body survives backslash-bearing evidence across a first run and a re-run without crashing"
echo "      or duplicating markers, and -- against platform's REAL PUBLISHED evidence at the tag this repository"
echo "      pins, through adopter_gate.py's own CLI, with a cold TUF cache and egress hard-blocked -- real cosign"
echo "      ACCEPTS platform's own signature (E2, exit 0), REFUSES the same bundle with one signature byte changed"
echo "      (E3), REFUSES it under a foreign identity constant (E4), cannot verify it at all without the committed"
echo "      trust material (E5), still refuses the pre-2026-09-06 --trusted-root invocation on the flag (E1), and"
echo "      REFUSES on the trust material and never on the network when the committed root is wrong, corrupt,"
echo "      retired or absent, cold and warm (E6, eco-system ticket 105)."
echo "      Out of reach here and dated 2026-09-06: SIGNING new evidence (Fulcio keyless needs a live Actions"
echo "      credential). Verifying what platform already signed is not, and is proved above."
