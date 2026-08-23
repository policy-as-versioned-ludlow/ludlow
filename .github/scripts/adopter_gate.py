#!/usr/bin/env python3
"""adopter_gate.py -- ticket cs-28: the institution's own adopter gate.

Runs from shift-left.yml, on a pull request that touches (or might touch)
gitops/platform/platform-pin.yaml -- typically a Renovate bump PR. Does NOT
recompute the publisher's classification (spec.md, "The adopter computes its
own composed bump and does not recompute the publisher's" -- "a second
answer to the same question has no tie-breaker"). Instead it:

  1. Reads the pin this PR is proposing (PR head) and the pin it replaces
     (PR base), both from THIS repo's own gitops/platform/platform-pin.yaml
     -- no discovery endpoint, ever.
  2. Verifies platform's checked-out tag resolves to the pinned `commit`
     field exactly (bug #2 in spec.md's "Two live bugs" note) -- refuses
     otherwise, which is what makes ADR-0001's pin load-bearing rather than
     decorative.
  3. Diffs distribution/versions.yaml (platform's own array of currently-
     supported policy versions) between the OLD and NEW pinned commits. A
     version present in the old array and absent from the new one has
     retired -- that reaches this institution as a MAJOR, unconditionally,
     with no evidence to check (spec.md, "the window as it stood before this
     release ... makes a retirement classify as major with no special
     case"). A version newly present, or whose `commit` field moved, is
     "changed" -- ITS bump comes from ITS OWN verified evidence document
     (cs-27), never recomputed here.
  4. For every changed version, finds platform's committed evidence file and
     cosign bundle (cs-27's own layout: computed-semver/evidence/<version>.
     json[.bundle]) and verifies the bundle with `cosign verify-blob`,
     identity-pinned against EXPECTED_IDENTITY_REGEXP -- a constant this
     repo holds itself (see shift-left.yml's own copy; the identity is NOT
     read from anything platform supplies at verification time). Offline:
     the bundle cosign sign-blob produced carries its own Rekor inclusion
     proof, exactly the pattern release.yml already uses for the release
     tag's own gitsign signature.
  5. Composes: the strictest bump across every retirement (major) and every
     changed version's own verified `bump.computed` -- cross-party
     composition is out of scope (spec.md, "Out of Scope"; see also
     .scratch/policy-composition/map.md); this repo pins exactly one
     policy-bearing party (platform) as of this ticket, so "composed" here
     is the strictest-wins fold over ONE party's own array delta, not
     N-party composition machinery.
  6. A composed MAJOR fails the pull request (real, non-zero exit -- this is
     wired as a required status check, not a print). A composed bump weaker
     than "the publisher's tag" (the semver-literal jump on platform-pin.
     yaml's own bare tag, e.g. v0.1.0 -> v1.0.0 is itself a major literal
     jump) prints and never lowers anything -- a local, weaker reading never
     talks the institution down from what the tag's own number already
     promises (spec.md: "a local view cannot weaken a published promise").

Also renders the verified evidence into a PR-comment-shaped Markdown
document (ticket cs-29) -- see shift-left.yml's own header comment for why
this ships as a PR COMMENT and not a body edit.

Usage:
    adopter_gate.py --ludlow-dir DIR --platform-dir DIR \\
        --old-ref REF --new-ref REF --out-comment FILE \\
        [--identity-regexp REGEXP] [--issuer ISSUER]

    adopter_gate.py --selfcheck   # runnable asserts, real git, no cosign/network
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# The institution's own expected-identity constant for PLATFORM's evidence
# signature -- verifying evidence signed by platform's cut-release.yml, not
# ludlow's own (that is release.yml's job, ticket cs-14, a different
# constant entirely). Kept identical to shift-left.yml's own copy of this
# same literal; the workflow always passes --identity-regexp explicitly from
# its own env var, so the YAML is the one place of truth -- this default
# only serves callers (tests, local runs) that invoke the script directly.
EXPECTED_IDENTITY_REGEXP = (
    r"^https://github\.com/policy-as-versioned-platform/platform/"
    r"\.github/workflows/cut-release\.yml@refs/heads/(main|release/[0-9]+\.[0-9]+\.x)$"
)
EXPECTED_ISSUER = "https://token.actions.githubusercontent.com"

RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}
RANK_NAME = {v: k for k, v in RANK.items()}


class Refused(Exception):
    """Raised to stop the gate and refuse the pull request."""


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, **kw)


def git_show(repo_dir: Path, ref: str, path: str) -> str | None:
    """The content of `path` at `ref`, or None if it does not exist there.
    Never touches the working tree -- every read is an object-database
    lookup, so nothing here depends on what happens to be checked out."""
    r = _run(["git", "-C", str(repo_dir), "show", f"{ref}:{path}"])
    return r.stdout if r.returncode == 0 else None


def resolve_commit(repo_dir: Path, ref: str) -> str | None:
    r = _run(["git", "-C", str(repo_dir), "rev-parse", f"{ref}^{{commit}}"])
    return r.stdout.strip() if r.returncode == 0 else None


def read_pin(ludlow_dir: Path, ref: str) -> dict:
    """gitops/platform/platform-pin.yaml's GitRepository, at `ref`. The two
    live bugs this ticket fixes both start here: the tag under review is
    whatever this file names at the pull request HEAD, never a default
    branch, and the commit it names is what gets verified below, never
    trusted blind."""
    text = git_show(ludlow_dir, ref, "gitops/platform/platform-pin.yaml")
    if text is None:
        raise Refused(f"gitops/platform/platform-pin.yaml not found at {ref}")
    doc = next(
        (d for d in yaml.safe_load_all(text) if d and d.get("kind") == "GitRepository"
         and d.get("metadata", {}).get("name") == "platform"),
        None,
    )
    if doc is None:
        raise Refused(f"no platform GitRepository object in platform-pin.yaml at {ref}")
    ref_block = doc["spec"]["ref"]
    tag, commit = ref_block.get("tag"), ref_block.get("commit")
    if not tag or not commit:
        raise Refused(f"platform-pin.yaml at {ref} is missing spec.ref.tag or spec.ref.commit")
    return {"tag": tag, "commit": commit}


def parse_semver(tag: str) -> tuple[int, int, int]:
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    if not m:
        raise Refused(f"platform-pin.yaml tag {tag!r} is not a plain vX.Y.Z tag")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def declared_bump(old_tag: str, new_tag: str) -> str:
    """The semver-literal jump on platform-pin.yaml's own bare tag -- "the
    publisher's tag" in spec.md's sense. This is NOT computed-semver
    classification (platform's own bare v* line is explicitly outside
    cs-27's gate -- it names no element of the policy array); it is just
    the leftmost-changed-component reading of two version strings this
    institution already holds, same rule as semver 2.0.0 always has."""
    old, new = parse_semver(old_tag), parse_semver(new_tag)
    if new <= old:
        raise Refused(f"platform pin did not advance: {old_tag} -> {new_tag}")
    for i, name in enumerate(("major", "minor", "patch")):
        if new[i] != old[i]:
            return name
    raise Refused(f"platform pin tags equal after parsing: {old_tag} -> {new_tag}")  # unreachable


def read_versions(platform_dir: Path, commit: str) -> list[dict]:
    """distribution/versions.yaml's array, at `commit` -- the currently-
    supported policy versions as platform's own release declared them at
    that exact, already-pinned point. Reading a fixed commit's committed
    tree is not discovery: the commit is already named by this repo's own
    pin, offline and immutable."""
    text = git_show(platform_dir, commit, "distribution/versions.yaml")
    if text is None:
        raise Refused(f"distribution/versions.yaml not found in platform at {commit}")
    doc = yaml.safe_load(text)
    return doc["spec"]["inputs"][0]["versions"]


def diff_versions(old: list[dict], new: list[dict]) -> tuple[list[str], list[dict]]:
    old_by_v = {e["version"]: e for e in old}
    new_by_v = {e["version"]: e for e in new}
    retired = sorted(v for v in old_by_v if v not in new_by_v)
    changed = sorted(
        (e for v, e in new_by_v.items() if v not in old_by_v or e.get("commit") != old_by_v[v].get("commit")),
        key=lambda e: e["version"],
    )
    return retired, changed


def verify_evidence(platform_dir: Path, commit: str, version: str,
                     identity_regexp: str, issuer: str, workdir: Path) -> dict:
    """Fetch platform's committed evidence + cosign bundle for `version` at
    `commit` (cs-27's layout) and verify the bundle offline, identity-
    pinned. Raises Refused on anything short of a verified, passed
    evidence document -- there is no "verification unavailable, proceed
    anyway" path."""
    evidence_text = git_show(platform_dir, commit, f"computed-semver/evidence/{version}.json")
    bundle_text = git_show(platform_dir, commit, f"computed-semver/evidence/{version}.json.bundle")
    if evidence_text is None or bundle_text is None:
        raise Refused(
            f"policy {version}: no committed evidence/bundle at "
            f"computed-semver/evidence/{version}.json[.bundle] for commit {commit}"
        )
    evidence_path = workdir / f"{version}.json"
    bundle_path = workdir / f"{version}.json.bundle"
    evidence_path.write_text(evidence_text)
    bundle_path.write_text(bundle_text)

    result = _run([
        "cosign", "verify-blob",
        f"--bundle={bundle_path}",
        f"--certificate-identity-regexp={identity_regexp}",
        f"--certificate-oidc-issuer={issuer}",
        str(evidence_path),
    ])
    if result.returncode != 0:
        raise Refused(
            f"policy {version}: cosign verify-blob refused the evidence signature "
            f"({result.stderr.strip() or result.stdout.strip()})"
        )

    doc = json.loads(evidence_text)
    if doc.get("outcome", {}).get("result") != "passed":
        raise Refused(
            f"policy {version}: verified evidence itself does not record outcome=passed "
            f"({doc.get('outcome')})"
        )
    return doc


def compose(retired: list[str], changed: list[dict], platform_dir: Path,
            identity_regexp: str, issuer: str, workdir: Path) -> tuple[str, list[dict]]:
    """The strictest-wins fold: every retirement is major, every changed
    version's bump is its own verified evidence's computed bump, never
    recomputed. Raises Refused (naming every failing version, not just the
    first) if any changed version's evidence fails to verify."""
    results: list[dict] = []
    failures: list[str] = []
    rank = 0

    for v in retired:
        results.append({"version": v, "kind": "retired", "bump": "major", "evidence": None})
        rank = max(rank, RANK["major"])

    for e in changed:
        version = e["version"]
        try:
            doc = verify_evidence(platform_dir, e["commit"], version, identity_regexp, issuer, workdir)
        except Refused as exc:
            failures.append(str(exc))
            continue
        computed = doc["bump"]["computed"] or "none"
        results.append({"version": version, "kind": "changed", "bump": computed, "evidence": doc})
        rank = max(rank, RANK.get(computed, 0))

    if failures:
        raise Refused("; ".join(failures))

    return RANK_NAME[rank], results


def render_comment(old_pin: dict, new_pin: dict, declared: str, composed: str,
                    results: list[dict], note: str | None) -> str:
    """The evidence, rendered for a human reviewer (ticket cs-29). Declared
    vs. computed side by side, per-policy verdict movement naming entries
    and expressions, counts and the not-looked-at list, each hole marked
    new/carried_over/closed with its stable id, derived limits open and
    closed with counts, the per-institution matrix, the corpus checksum and
    generator_version. No coverage percentage anywhere -- every coverage
    number below is a plain count, never divided into a ratio."""
    lines = [
        "### computed-semver adopter gate",
        "",
        f"platform pin: `{old_pin['tag']}` -> `{new_pin['tag']}`",
        "",
        "| | declared (publisher's tag) | composed (this institution) |",
        "|---|---|---|",
        f"| bump | **{declared}** | **{composed}** |",
        "",
    ]
    if note:
        lines += [f"> {note}", ""]

    if not results:
        lines.append("No change to the pinned policy version array (`distribution/versions.yaml`).")
        return "\n".join(lines) + "\n"

    for r in results:
        version, kind, bump = r["version"], r["kind"], r["bump"]
        if kind == "retired":
            lines += [
                f"#### policy `{version}` -- retired",
                "",
                "Present in the old window, absent from the new one. Composed bump: **major**, "
                "unconditionally -- no evidence to verify for a version that is gone.",
                "",
            ]
            continue

        doc = r["evidence"]
        lines += [f"#### policy `{version}`", ""]
        lines += [
            "| | declared | computed |",
            "|---|---|---|",
            f"| bump | {doc['bump']['declared']} | **{doc['bump']['computed']}** |",
            "",
        ]

        lines.append("**Per-policy verdict movement:**")
        if doc["movement"]:
            for m in doc["movement"]:
                entries = ", ".join(m["entries"]) or "(structural, no fixture moved)"
                exprs = "; ".join(m["expressions"]) or "n/a"
                lines.append(f"- `{m['policy']}` -- **{m['verdict']}** -- entries: {entries} -- via `{exprs}`")
        else:
            lines.append("- (none recorded)")
        lines.append("")

        c = doc["counts"]
        cov = doc["coverage"]
        lines += [
            f"**Counts:** old={c['old']} new={c['new']} union={c['union']} "
            f"-- coverage cells={cov['cells']} pairs={cov['pairs']} pairwise_gap={cov['pairwise_gap']}",
            "",
        ]

        lines.append("**Not-looked-at (holes):**")
        if doc["not_looked_at"]:
            for h in doc["not_looked_at"]:
                lines.append(
                    f"- `{h['id']}` [{h['status']}] tier={h['tier']} name={h.get('name')} "
                    f"expr=`{h['expression']}`"
                )
        else:
            lines.append("- (none)")
        lines.append("")

        lines.append("**Derived limits:**")
        for lim in doc["limits"]:
            lines.append(f"- {lim['name']} ({lim['status']}, count={lim['count']}) -- {lim['description']}")
        lines.append("")

        lines.append("**Per-institution matrix:**")
        if doc["matrix"]:
            for inst, cell in sorted(doc["matrix"].items()):
                lines.append(f"- {inst}: pinned={cell['pinned_version']} computed_bump={cell['computed_bump']}")
        else:
            lines.append("- (none recorded)")
        lines.append("")

        lines.append(f"**Corpus checksum:** `{doc['corpus_checksum']}` -- **generator_version:** `{doc['generator_version']}`")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_refusal_comment(reason: str, old_pin: dict | None, new_pin: dict | None) -> str:
    lines = ["### computed-semver adopter gate -- REFUSED", "", f"> {reason}", ""]
    if old_pin and new_pin:
        lines.insert(2, f"platform pin: `{old_pin['tag']}` -> `{new_pin['tag']}`")
    return "\n".join(lines) + "\n"


def run(ludlow_dir: Path, platform_dir: Path, old_ref: str, new_ref: str,
        identity_regexp: str, issuer: str) -> tuple[int, str]:
    """Returns (exit_code, comment_markdown). Never raises -- every failure
    mode becomes a refusal comment and exit 1, so the caller always has
    something to post."""
    old_pin = new_pin = None
    try:
        old_pin = read_pin(ludlow_dir, old_ref)
        new_pin = read_pin(ludlow_dir, new_ref)

        resolved = resolve_commit(platform_dir, new_pin["tag"])
        if resolved != new_pin["commit"]:
            raise Refused(
                f"platform tag {new_pin['tag']!r} resolves to {resolved!r}, "
                f"but platform-pin.yaml pins commit {new_pin['commit']!r} -- refusing "
                f"(ADR-0001's pin is load-bearing, not decorative)"
            )

        if old_pin["tag"] == new_pin["tag"]:
            return 0, render_comment(old_pin, new_pin, "none", "none", [], "platform pin unchanged in this PR.")

        declared = declared_bump(old_pin["tag"], new_pin["tag"])
        old_versions = read_versions(platform_dir, old_pin["commit"])
        new_versions = read_versions(platform_dir, new_pin["commit"])
        retired, changed = diff_versions(old_versions, new_versions)

        with tempfile.TemporaryDirectory() as td:
            composed, results = compose(retired, changed, platform_dir, identity_regexp, issuer, Path(td))

        note = None
        if RANK[composed] < RANK[declared]:
            note = (
                f"composed bump ({composed}) is weaker than the publisher's tag bump "
                f"({declared}, {old_pin['tag']} -> {new_pin['tag']}) -- informational only, "
                f"never lowers what this institution treats as the obligation."
            )
        comment = render_comment(old_pin, new_pin, declared, composed, results, note)

        if composed == "major":
            print(f"REFUSE: composed bump is major -- {[r['version'] for r in results if r['bump']=='major']}")
            return 1, comment
        if note:
            print(f"INFO: {note}")
        print(f"PASS: declared={declared} composed={composed}")
        return 0, comment

    except Refused as exc:
        print(f"REFUSE: {exc}")
        return 1, write_refusal_comment(str(exc), old_pin, new_pin)


def selfcheck() -> None:
    """Real git, no cosign, no network: proves the parsing/diff/compose
    math actually detects what it claims to, using fabricated (unsigned)
    evidence dicts fed straight into compose()'s own pure logic -- cosign
    wiring itself is proved separately (see verify-adopter-gate.sh, which
    runs the real binary against a deliberately-invalid bundle)."""

    def fake_doc(computed: str) -> dict:
        return {
            "outcome": {"result": "passed", "reason": None},
            "bump": {"declared": computed, "computed": computed},
            "movement": [{"policy": "p.yaml", "verdict": computed, "entries": ["e1"], "expressions": ["x==1"], "detail": ""}],
            "counts": {"old": 1, "new": 1, "union": 1},
            "generator_version": "test-1",
            "corpus_checksum": "sha256:test",
            "coverage": {"cells": 1, "pairs": 1, "pairwise_gap": 0},
            "not_looked_at": [],
            "limits": [],
            "matrix": {},
        }

    # 1. declared_bump: real leftmost-component semver-literal reading.
    assert declared_bump("v0.1.0", "v1.0.0") == "major"
    assert declared_bump("v1.0.0", "v1.1.0") == "minor"
    assert declared_bump("v1.0.0", "v1.0.1") == "patch"
    try:
        declared_bump("v1.0.0", "v1.0.0")
        assert False, "equal tags must refuse"
    except Refused:
        pass

    # 2. diff_versions: retirement detected, unchanged entries not re-flagged.
    old = [{"version": "2.0.0", "commit": "aaa"}, {"version": "3.0.0", "commit": "bbb"}]
    new = [{"version": "3.0.0", "commit": "bbb"}, {"version": "3.1.0", "commit": "ccc"}]
    retired, changed = diff_versions(old, new)
    assert retired == ["2.0.0"], retired
    assert [c["version"] for c in changed] == ["3.1.0"], changed

    # 3. compose: a retirement alone composes to major, with no evidence lookup.
    class _Boom:
        def __call__(self, *a, **k):
            raise AssertionError("verify_evidence must not be called for a pure retirement")

    import unittest.mock as mock
    with mock.patch("__main__.verify_evidence", _Boom()):
        composed, results = compose(["2.0.0"], [], Path("/nonexistent"), "x", "y", Path("/tmp"))
    assert composed == "major", composed
    assert results == [{"version": "2.0.0", "kind": "retired", "bump": "major", "evidence": None}]

    # 4. compose: strictest-wins across a retirement (major) and a changed
    #    minor -- major must win even though it sorts first alphabetically.
    with mock.patch("__main__.verify_evidence", return_value=fake_doc("minor")):
        composed, results = compose(["2.0.0"], [{"version": "3.1.0", "commit": "ccc"}],
                                     Path("/nonexistent"), "x", "y", Path("/tmp"))
    assert composed == "major", composed
    assert {r["version"]: r["bump"] for r in results} == {"2.0.0": "major", "3.1.0": "minor"}

    # 5. compose: a changed version alone, patch-classified -> composed patch.
    with mock.patch("__main__.verify_evidence", return_value=fake_doc("patch")):
        composed, results = compose([], [{"version": "3.1.0", "commit": "ccc"}],
                                     Path("/nonexistent"), "x", "y", Path("/tmp"))
    assert composed == "patch", composed

    # 6. compose: a verification failure refuses (names the version), never
    #    silently drops the version and computes a weaker bump instead.
    def _refuse(*a, **k):
        raise Refused("policy 3.1.0: cosign verify-blob refused the evidence signature (fabricated)")

    with mock.patch("__main__.verify_evidence", side_effect=_refuse):
        try:
            compose([], [{"version": "3.1.0", "commit": "ccc"}], Path("/nonexistent"), "x", "y", Path("/tmp"))
            assert False, "a verification failure must refuse, not silently pass"
        except Refused as exc:
            assert "3.1.0" in str(exc), exc

    print("PASS: adopter_gate.py selfcheck (declared_bump, diff_versions, compose -- retirement=major, "
          "strictest-wins, verification-failure-refuses)")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--ludlow-dir", type=Path)
    ap.add_argument("--platform-dir", type=Path)
    ap.add_argument("--old-ref")
    ap.add_argument("--new-ref")
    ap.add_argument("--out-comment", type=Path)
    ap.add_argument("--identity-regexp", default=EXPECTED_IDENTITY_REGEXP)
    ap.add_argument("--issuer", default=EXPECTED_ISSUER)
    args = ap.parse_args(argv)

    if args.selfcheck:
        selfcheck()
        return 0

    missing = [n for n in ("ludlow_dir", "platform_dir", "old_ref", "new_ref", "out_comment")
               if getattr(args, n) is None]
    if missing:
        ap.error(f"missing required arguments: {', '.join('--' + m.replace('_','-') for m in missing)}")

    code, comment = run(args.ludlow_dir, args.platform_dir, args.old_ref, args.new_ref,
                         args.identity_regexp, args.issuer)
    args.out_comment.write_text(comment)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
