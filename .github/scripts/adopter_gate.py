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
     the bundle cosign sign-blob produced carries its own certificate,
     signature and Rekor inclusion proof, but verifying THOSE still needs
     the Sigstore trust roots (the Fulcio CA, the Rekor/CT log keys) --
     without them cosign fetches a live TUF root over the network. This
     repo pins that root too, the same shape release.yml's gitsign check
     already pins Rekor offline: TRUSTED_ROOT_PATH below, a trusted_root.
     json committed next to this script (`cosign initialize` once, then
     copy $HOME/.sigstore/root/*/targets/trusted_root.json here), passed
     as --trusted-root. Refresh it the way any pinned trust material is
     refreshed -- deliberately, by committing a new copy -- never by
     letting cosign reach out live.
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

Also renders the verified evidence into a Markdown document (ticket cs-29)
and wraps it between SECTION_START/SECTION_END HTML-comment markers --
shift-left.yml locates that pair inside the pull request's own CURRENT body
(fetched fresh at the top of the step, so it always reads whatever Renovate
most recently wrote) and replaces the span between them, or appends the
whole marked section if the markers aren't present yet. This lands the
evidence IN THE PULL REQUEST BODY ITSELF, literally, as ticket cs-29's own
title and first acceptance-criterion line require -- not a PR comment. A
comment was this ticket's first cut; a reviewer flagged that as not
satisfying the ticket's own words, so this now edits the body for real. It
is safe against Renovate's own re-runs for the same reason a comment would
have been: shift-left.yml is triggered BY a `pull_request` event, which only
fires after Renovate has already finished writing its own body content for
that push -- the step always splices onto text Renovate already settled on,
never races it.

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

# The pinned Sigstore trust root (Fulcio CA, Rekor/CT log keys) -- committed
# next to this script so `cosign verify-blob` never falls back to a live TUF
# fetch. Regenerate with `cosign initialize` then copy the fetched
# $HOME/.sigstore/root/*/targets/trusted_root.json over this file; that is a
# deliberate, reviewed commit, same as any other pin in this repo.
TRUSTED_ROOT_PATH = Path(__file__).resolve().parent / "trusted_root.json"

RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}
RANK_NAME = {v: k for k, v in RANK.items()}

# HTML-comment markers shift-left.yml greps out of the pull request's own
# CURRENT body to find (and replace) the span this gate owns, or append it
# if this is the first run on this PR. Never rendered by GitHub (an HTML
# comment), so they don't clutter what the reviewer sees.
SECTION_START = "<!-- cs-29:adopter-gate:start -->"
SECTION_END = "<!-- cs-29:adopter-gate:end -->"


def wrap_section(markdown: str) -> str:
    """The rendered evidence (or refusal), wrapped for splicing into the
    pull request body between SECTION_START/SECTION_END. Kept as a thin
    wrapper around render_comment/write_refusal_comment, which stay pure and
    unaware of where their output ends up -- selfcheck exercises them
    directly without needing to strip markers back out."""
    return f"{SECTION_START}\n{markdown.rstrip()}\n{SECTION_END}\n"


SECTION_PATTERN = re.compile(re.escape(SECTION_START) + r".*?" + re.escape(SECTION_END), re.DOTALL)


def splice_body(current_body: str, section: str) -> str:
    """`section` is already wrap_section()'d output. Replaces a prior span
    between the markers in-place (a re-run on the same pull request), or
    appends the whole marked section after whatever's there (the first run
    on this PR -- typically Renovate's own body). Pure string logic, no I/O,
    so shift-left.yml's own step is just "fetch, splice, write back" with no
    embedded multi-line script of its own -- see --splice-body below."""
    if SECTION_PATTERN.search(current_body):
        # A callable replacement, never a raw string: re.sub() treats a
        # string replacement's backslashes as backreferences/escapes
        # (\d, \1, ...), and evidence content routinely carries a Kyverno/
        # CEL match expression like `matches(image, '^v\d+\.\d+\.\d+$')` --
        # exactly the pattern parse_semver() above uses on this repo's own
        # tags. A lambda sidesteps that interpretation entirely; the
        # replacement text lands verbatim, whatever it contains.
        return SECTION_PATTERN.sub(lambda _m: section.rstrip(), current_body)
    # No COMPLETE start...end pair. GitHub caps PR body length; ticket 29's
    # own acceptance criteria mandate rendering a lot (full per-policy
    # movement, the whole not-looked-at list, every hole, derived limits,
    # the per-institution matrix), so a long enough render can get the body
    # truncated by GitHub mid-section -- SECTION_START saved, SECTION_END
    # never reaches the saved body. Treat an unpaired SECTION_START (found,
    # with no END anywhere after it) the same as a complete pair: replace
    # from that orphaned START to the end of the body, rather than
    # appending past it and accumulating a duplicate/orphaned span on every
    # future run forever.
    start_idx = current_body.find(SECTION_START)
    if start_idx != -1:
        prefix = current_body[:start_idx].rstrip()
        sep = "\n\n" if prefix else ""
        return prefix + sep + section
    sep = "\n\n" if current_body.strip() else ""
    return current_body.rstrip() + sep + section


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
    try:
        doc = next(
            (d for d in yaml.safe_load_all(text) if d and d.get("kind") == "GitRepository"
             and d.get("metadata", {}).get("name") == "platform"),
            None,
        )
    except yaml.YAMLError as exc:
        raise Refused(f"platform-pin.yaml at {ref} is not valid YAML: {exc}") from exc
    if doc is None:
        raise Refused(f"no platform GitRepository object in platform-pin.yaml at {ref}")
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        raise Refused(f"platform-pin.yaml at {ref}: GitRepository object has no spec")
    ref_block = spec.get("ref")
    if not isinstance(ref_block, dict):
        raise Refused(f"platform-pin.yaml at {ref}: GitRepository spec has no ref")
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
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise Refused(f"platform's distribution/versions.yaml at {commit} is not valid YAML: {exc}") from exc
    try:
        versions = doc["spec"]["inputs"][0]["versions"]
    except (KeyError, IndexError, TypeError) as exc:
        raise Refused(
            f"platform's distribution/versions.yaml at {commit} is malformed "
            f"(expected spec.inputs[0].versions): {exc}"
        ) from exc
    if not isinstance(versions, list):
        raise Refused(f"platform's distribution/versions.yaml at {commit}: spec.inputs[0].versions is not a list")
    return versions


def versions_from_composed_evidence(ludlow_dir: Path, ref: str) -> list[dict]:
    """ADR-0011 (policy-composition ticket 18): 'the adopter gate reads the
    composed artefact as its subject.' The set of live policy versions THIS
    institution's own signed composed/evidence.json records as members, at
    `ref` (a commit-ish in ludlow's own repo -- ticket 18's compose-check
    job keeps that file fresh and byte-verified on every pull request).
    Returned in read_versions()'s own shape (a list of {"version", "commit"})
    so diff_versions() needs no change at all; `commit` is always the literal
    string "HEAD" here -- composition.py's evidence document has no notion
    of a per-version source commit, and verify_evidence() needs SOME ref to
    read platform's evidence file at, which is whatever this run already has
    platform_dir checked out to (the pull request's own new pin tag). Two
    "HEAD" values compare equal in diff_versions()'s own "changed" test
    (`e.get("commit") != old_by_v[v].get("commit")`), so a version present
    at both ends is never spuriously flagged, and only a genuinely new
    version (absent from old_by_v) is classified "changed". A platform-
    machinery member (the orphan guard, the governed-namespace guard)
    carries no `version` -- excluded, same as distribution/versions.yaml's
    own array never lists it either."""
    text = git_show(ludlow_dir, ref, "composed/evidence.json")
    if text is None:
        raise Refused(f"composed/evidence.json not found in ludlow's own repo at {ref}")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"composed/evidence.json at {ref} is not valid JSON: {exc}") from exc
    return [{"version": m["version"], "commit": "HEAD"}
            for m in doc.get("members", []) if m.get("version") is not None]


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

    if not TRUSTED_ROOT_PATH.is_file():
        raise Refused(
            f"policy {version}: no committed Sigstore trust root at {TRUSTED_ROOT_PATH} -- "
            "refusing rather than letting cosign fall back to a live TUF fetch"
        )

    result = _run([
        "cosign", "verify-blob",
        f"--bundle={bundle_path}",
        f"--trusted-root={TRUSTED_ROOT_PATH}",
        "--new-bundle-format=true",  # required by cosign to honor --trusted-root at all
        f"--certificate-identity-regexp={identity_regexp}",
        f"--certificate-oidc-issuer={issuer}",
        str(evidence_path),
    ])
    if result.returncode != 0:
        raise Refused(
            f"policy {version}: cosign verify-blob refused the evidence signature "
            f"({result.stderr.strip() or result.stdout.strip()})"
        )

    try:
        doc = json.loads(evidence_text)
    except json.JSONDecodeError as exc:
        raise Refused(
            f"policy {version}: evidence at computed-semver/evidence/{version}.json "
            f"(commit {commit}) is not valid JSON: {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise Refused(
            f"policy {version}: evidence at computed-semver/evidence/{version}.json "
            f"(commit {commit}) is not a JSON object"
        )
    outcome = doc.get("outcome")
    # Ticket 43 (18 Answers 1 and 2): `degraded` is a published outcome, not a
    # refusal. The publisher's declared bump was weaker than the computed one,
    # so it published under a prerelease suffix at tier quarantine. The
    # publisher's tier is a signed FACT here, never a floor this institution
    # must take: refusing it would be a gate under another name, and the
    # publisher would be setting a cage inside this repository. It is carried
    # through and priced under this institution's own perspective.
    #   ponytail: carried, named, and NOT yet priced -- the priced hole in
    #   composed prices[] is ticket 25's single prices[] pass. Until that
    #   lands, a degraded parent is a recorded, visible fact in this gate's
    #   own output, which is strictly more than the refusal it replaces.
    if not isinstance(outcome, dict) or outcome.get("result") not in ("passed", "degraded"):
        raise Refused(
            f"policy {version}: verified evidence itself does not record outcome=passed "
            f"or outcome=degraded ({outcome!r})"
        )
    if outcome.get("result") == "degraded":
        print(f"note: policy {version} was published DEGRADED at tier "
              f"{doc.get('degraded', {}).get('tier')} -- a signed fact ludlow prices, "
              f"not a floor the publisher sets here.")
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
        identity_regexp: str, issuer: str,
        composed_base_ref: str | None = None, composed_head_ref: str | None = None) -> tuple[int, str]:
    """Returns (exit_code, comment_markdown). Never raises -- every failure
    mode becomes a refusal comment and exit 1, so the caller always has
    something to post. This institution does not control platform's YAML/
    JSON shape staying exactly as read_pin/read_versions/verify_evidence
    expect it forever, so besides those functions' own specific, named
    Refused guards, the broadened except below is a safety net: any
    KeyError/IndexError/TypeError/json.JSONDecodeError/yaml.YAMLError that
    still escapes (e.g. from render_comment's own indexing into platform's
    evidence document, once compose() has already verified its signature)
    becomes a refusal naming the exception, never an unhandled traceback
    out of a required status check."""
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
        # ADR-0011 (ticket 18): "the composed bump is computed after
        # composition." When composed_base_ref/composed_head_ref are given,
        # read added/retired from ludlow's OWN signed composed/evidence.json
        # member set at those two commits, not platform's raw
        # distribution/versions.yaml array directly. Falls back to the
        # pre-ADR-0011 array-read path otherwise (kept for --selfcheck's own
        # narrower fixtures and any caller not yet passing them).
        if composed_base_ref is not None and composed_head_ref is not None:
            old_versions = versions_from_composed_evidence(ludlow_dir, composed_base_ref)
            new_versions = versions_from_composed_evidence(ludlow_dir, composed_head_ref)
        else:
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
    except OSError as exc:
        # A missing/broken local tool (verify_evidence's `cosign` subprocess call is
        # the one reachable case: FileNotFoundError if cosign isn't on PATH) -- not
        # malformed platform data, so it gets its own honest wording rather than the
        # "platform's data was malformed" reason below. shift-left.yml's own cosign
        # install step already fails first in the real wired CI (checksummed, no
        # `set +e`), so this is a defence-in-depth guard for direct/future
        # invocation, not the primary line of defence.
        reason = (
            f"a local tool this gate depends on could not be run "
            f"({type(exc).__name__}: {exc}) -- refusing rather than crashing"
        )
        print(f"REFUSE: {reason}")
        return 1, write_refusal_comment(reason, old_pin, new_pin)
    except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        reason = (
            f"platform's data was malformed in a way this gate did not specifically "
            f"anticipate ({type(exc).__name__}: {exc}) -- refusing rather than crashing"
        )
        print(f"REFUSE: {reason}")
        return 1, write_refusal_comment(reason, old_pin, new_pin)


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

    # 7. wrap_section: the markers actually bracket the content, verbatim,
    #    so shift-left.yml's own splice step has an exact span to find.
    wrapped = wrap_section("some *markdown*\n")
    assert wrapped.startswith(SECTION_START + "\n"), wrapped
    assert wrapped.rstrip().endswith(SECTION_END), wrapped
    assert "some *markdown*" in wrapped, wrapped

    # 8. splice_body: first run appends after Renovate's own content; a
    #    re-run on the same PR replaces the prior span in place, verbatim,
    #    and never touches anything outside the markers.
    renovate_body = "Bumps platform from v1.0.0 to v1.1.0.\n\n---\n\nRenovate config help."
    first = splice_body(renovate_body, wrap_section("run 1 evidence"))
    assert renovate_body in first and "run 1 evidence" in first, first
    assert first.count(SECTION_START) == 1, first

    second = splice_body(first, wrap_section("run 2 evidence, superseding run 1"))
    assert "run 1 evidence" not in second, second
    assert "run 2 evidence, superseding run 1" in second, second
    assert renovate_body in second, second  # Renovate's own content, untouched across re-runs
    assert second.count(SECTION_START) == 1, second

    empty_first = splice_body("", wrap_section("only evidence, no prior body"))
    assert empty_first.startswith(SECTION_START), empty_first  # no spurious leading blank lines

    # 8b. splice_body: a re-run whose evidence carries backslashes -- a real
    #     Kyverno/CEL match expression, exactly the idiom parse_semver() uses
    #     on this repo's own tags -- must not be interpreted as re.sub()
    #     backreferences/escapes (a raw-string replacement would raise
    #     re.PatternError: bad escape \d on this exact input). The backslash
    #     content must survive verbatim, and a SECOND re-run over it (the
    #     replacement itself now containing markers) must still replace in
    #     place, not choke on its own prior output.
    backslashy = (
        r"- `p.yaml` -- **major** -- via `matches(image, '^v\d+\.\d+\.\d+$')`"
    )
    with_backslashes = splice_body(renovate_body, wrap_section(backslashy))
    assert backslashy in with_backslashes, with_backslashes
    assert with_backslashes.count(SECTION_START) == 1, with_backslashes
    rerun_over_backslashes = splice_body(with_backslashes, wrap_section("run 2, still no crash"))
    assert backslashy not in rerun_over_backslashes, rerun_over_backslashes
    assert "run 2, still no crash" in rerun_over_backslashes, rerun_over_backslashes
    assert rerun_over_backslashes.count(SECTION_START) == 1, rerun_over_backslashes

    # 8c. splice_body: an ORPHANED SECTION_START with no matching END -- the
    #     shape GitHub's PR-body length cap leaves behind when a long enough
    #     evidence render (ticket 29's own acceptance criteria mandate a lot
    #     of content: full per-policy movement, the whole not-looked-at
    #     list, every hole, derived limits, the per-institution matrix) gets
    #     truncated by GitHub mid-section on a prior run. Confirm first that
    #     the PAIRED regex genuinely cannot see it (that's the bug: without
    #     the orphaned-START fallback, splice_body would silently APPEND a
    #     fresh section past the truncated one instead of replacing it, and
    #     the body would accumulate a duplicate/orphaned span on every
    #     future run forever -- never diffable again, ticket 29's own
    #     criterion). Then prove the fixed splice_body repairs it: replaces
    #     in place, doesn't duplicate, doesn't lose Renovate's own content.
    truncated_evidence = "evidence that never reached its own closing marker"
    truncated_body = renovate_body + "\n\n" + SECTION_START + "\n" + truncated_evidence
    assert SECTION_PATTERN.search(truncated_body) is None, (
        "setup: the paired start...end regex must NOT find a complete span in a "
        "truncated body -- otherwise this test isn't reproducing truncation at all"
    )

    repaired = splice_body(truncated_body, wrap_section("recovered evidence, run 2"))
    assert repaired.count(SECTION_START) == 1, repaired  # not duplicated/stacked
    assert truncated_evidence not in repaired, repaired  # orphaned span replaced, not appended-past
    assert "recovered evidence, run 2" in repaired, repaired
    assert renovate_body in repaired, repaired  # Renovate's own content, still untouched
    assert repaired.rstrip().endswith(SECTION_END), repaired  # well-formed again after repair

    # A second truncation-then-repair cycle must not re-accumulate either --
    # the orphaned-START fallback has to keep working on whatever the LAST
    # run left behind, not just a body truncated exactly once.
    re_truncated = repaired.split(SECTION_END)[0] + "\nsomehow truncated again"
    assert SECTION_PATTERN.search(re_truncated) is None, "setup: second truncation must also break the pair"
    re_repaired = splice_body(re_truncated, wrap_section("recovered evidence, run 3"))
    assert re_repaired.count(SECTION_START) == 1, re_repaired
    assert "recovered evidence, run 3" in re_repaired, re_repaired
    assert renovate_body in re_repaired, re_repaired

    # 9. read_pin: a real git repo whose platform-pin.yaml's GitRepository
    #    object is missing spec.ref entirely -- platform/Renovate's own YAML
    #    shape is not this institution's to guarantee forever (bug #2).
    #    Before the fix this was a bare `doc["spec"]["ref"]` KeyError,
    #    uncaught by run()'s Refused-only except. Must refuse with a clear,
    #    specific message, never an unhandled traceback.
    def _git(repo: Path, *args: str) -> None:
        r = _run(["git", "-C", str(repo), *args])
        assert r.returncode == 0, f"git {args} failed: {r.stderr}"

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.invalid")
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "gitops" / "platform").mkdir(parents=True)
        (repo / "gitops" / "platform" / "platform-pin.yaml").write_text(
            "apiVersion: source.toolkit.fluxcd.io/v1\n"
            "kind: GitRepository\n"
            "metadata: { name: platform, namespace: flux-system }\n"
            "spec: {}\n"  # missing ref entirely -- the malformed shape
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "malformed pin, no spec.ref")
        try:
            read_pin(repo, "HEAD")
            assert False, "a pin with no spec.ref must refuse, not silently return or crash"
        except Refused as exc:
            assert "ref" in str(exc), exc
        except Exception as exc:  # this IS bug #2 if it happens
            assert False, f"read_pin raised {type(exc).__name__} instead of Refused: {exc}"

        # run() end-to-end over the same malformed pin: exit 1, a refusal
        # comment, never a raised exception out of the top level.
        code, comment = run(repo, repo, "HEAD", "HEAD", EXPECTED_IDENTITY_REGEXP, EXPECTED_ISSUER)
        assert code == 1, code
        assert "REFUSED" in comment, comment

    # 10. read_versions: distribution/versions.yaml missing spec.inputs
    #     entirely -- same reasoning, platform's own file, not this
    #     institution's to guarantee forever. Before the fix this was a
    #     bare `doc["spec"]["inputs"][0]["versions"]` KeyError.
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.invalid")
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "distribution").mkdir(parents=True)
        (repo / "distribution" / "versions.yaml").write_text(
            "apiVersion: fluxcd.controlplane.io/v1\n"
            "kind: ResourceSet\n"
            "metadata: { name: policy-versions, namespace: flux-system }\n"
            "spec: {}\n"  # missing inputs entirely
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "malformed versions.yaml, no spec.inputs")
        commit = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()
        try:
            read_versions(repo, commit)
            assert False, "versions.yaml missing spec.inputs must refuse, not crash"
        except Refused as exc:
            assert "versions.yaml" in str(exc), exc
        except Exception as exc:  # this IS bug #2 if it happens
            assert False, f"read_versions raised {type(exc).__name__} instead of Refused: {exc}"

    # 11. verify_evidence: platform's committed evidence file is not valid
    #     JSON at all -- reachable in principle (a hand-edited or corrupted
    #     evidence commit), previously a bare `json.loads()` JSONDecodeError.
    #     cosign itself is faked (returns success) so this test exercises
    #     ONLY the JSON-parsing guard added for bug #2, not cosign wiring
    #     (already proved for real in verify-adopter-gate.sh Part C).
    real_run = _run

    def fake_run(args, **kw):
        if args and args[0] == "cosign":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return real_run(args, **kw)

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.invalid")
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "computed-semver" / "evidence").mkdir(parents=True)
        (repo / "computed-semver" / "evidence" / "3.0.0.json").write_text("{not valid json")
        (repo / "computed-semver" / "evidence" / "3.0.0.json.bundle").write_text("irrelevant -- cosign is faked below")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "malformed evidence JSON")
        commit = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()

        with mock.patch("__main__._run", side_effect=fake_run), tempfile.TemporaryDirectory() as wd:
            try:
                verify_evidence(repo, commit, "3.0.0", "x", "y", Path(wd))
                assert False, "malformed evidence JSON must refuse, not silently pass or crash"
            except Refused as exc:
                assert "3.0.0" in str(exc) and "JSON" in str(exc), exc
            except Exception as exc:  # this IS bug #2 if it happens
                assert False, f"verify_evidence raised {type(exc).__name__} instead of Refused: {exc}"

    # 12. run(): a raw, unanticipated exception from deep inside the happy
    #     path (simulating a shape this gate's specific guards did not
    #     foresee -- e.g. render_comment indexing into an evidence field
    #     platform's JSON doesn't carry) must still come back as exit 1 with
    #     a refusal, never propagate out of run() uncaught. This is run()'s
    #     own docstring claim ("never raises"), now genuinely true for more
    #     than just Refused -- the safety-net except clause, not a specific
    #     guard, is what catches this one.
    with tempfile.TemporaryDirectory() as td:
        platform_repo = Path(td) / "platform"
        ludlow_repo = Path(td) / "ludlow"
        for repo in (platform_repo, ludlow_repo):
            repo.mkdir()
            _git(repo, "init", "-q", "-b", "main")
            _git(repo, "config", "user.email", "t@example.invalid")
            _git(repo, "config", "user.name", "t")
            _git(repo, "config", "commit.gpgsign", "false")
            _git(repo, "config", "tag.gpgsign", "false")

        (platform_repo / "distribution").mkdir()
        (platform_repo / "distribution" / "versions.yaml").write_text(
            "apiVersion: fluxcd.controlplane.io/v1\nkind: ResourceSet\n"
            "metadata: { name: policy-versions, namespace: flux-system }\n"
            "spec: { inputs: [{ versions: [] }] }\n"
        )
        _git(platform_repo, "add", "-A")
        _git(platform_repo, "commit", "-q", "-m", "v0.1.0")
        _git(platform_repo, "tag", "v0.1.0")
        p_old = _run(["git", "-C", str(platform_repo), "rev-parse", "HEAD"]).stdout.strip()
        _git(platform_repo, "commit", "-q", "--allow-empty", "-m", "v1.0.0")
        _git(platform_repo, "tag", "v1.0.0")
        p_new = _run(["git", "-C", str(platform_repo), "rev-parse", "HEAD"]).stdout.strip()

        (ludlow_repo / "gitops" / "platform").mkdir(parents=True)

        def write_pin(tag: str, commit: str) -> None:
            (ludlow_repo / "gitops" / "platform" / "platform-pin.yaml").write_text(
                "apiVersion: source.toolkit.fluxcd.io/v1\nkind: GitRepository\n"
                "metadata: { name: platform, namespace: flux-system }\n"
                f'spec: {{ ref: {{ tag: "{tag}", commit: "{commit}" }} }}\n'
            )

        write_pin("v0.1.0", p_old)
        _git(ludlow_repo, "add", "-A")
        _git(ludlow_repo, "commit", "-q", "-m", "pin v0.1.0")
        l_old = _run(["git", "-C", str(ludlow_repo), "rev-parse", "HEAD"]).stdout.strip()
        write_pin("v1.0.0", p_new)
        _git(ludlow_repo, "add", "-A")
        _git(ludlow_repo, "commit", "-q", "-m", "bump pin to v1.0.0")
        l_new = _run(["git", "-C", str(ludlow_repo), "rev-parse", "HEAD"]).stdout.strip()

        with mock.patch("__main__.declared_bump", side_effect=KeyError("simulated_unanticipated_field")):
            code, comment = run(ludlow_repo, platform_repo, l_old, l_new,
                                 EXPECTED_IDENTITY_REGEXP, EXPECTED_ISSUER)
        assert code == 1, code
        assert "REFUSED" in comment, comment
        assert "KeyError" in comment, comment

    # 13. ADR-0011 (ticket 18): versions_from_composed_evidence + run()'s
    #     composed_base_ref/composed_head_ref path -- a REAL two-commit
    #     ludlow repo, no policy diff anywhere (only composed/evidence.json's
    #     own member set changes between the two commits), proving a version
    #     retired from the composed set classifies major end to end.
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.invalid")
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "commit.gpgsign", "false")
        (repo / "composed").mkdir()

        def write_evidence(versions: list[str]) -> None:
            doc = {"members": [{"name": f"member-{v}", "version": v} for v in versions]
                              + [{"name": "policy-version-orphan-guard", "version": None}]}
            (repo / "composed" / "evidence.json").write_text(json.dumps(doc))

        write_evidence(["2.0.0", "3.0.0"])
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base: 2.0.0, 3.0.0 live")
        base_sha = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()

        write_evidence(["3.0.0"])  # 2.0.0 retired, nothing added
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "head: 2.0.0 retired, no policy diff")
        head_sha = _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).stdout.strip()

        old_v = versions_from_composed_evidence(repo, base_sha)
        new_v = versions_from_composed_evidence(repo, head_sha)
        assert {e["version"] for e in old_v} == {"2.0.0", "3.0.0"}, old_v
        assert {e["version"] for e in new_v} == {"3.0.0"}, new_v

        retired, changed = diff_versions(old_v, new_v)
        assert retired == ["2.0.0"], retired
        assert changed == [], changed  # 3.0.0 survives with the same ("HEAD") commit -- not re-flagged

        with mock.patch("__main__.verify_evidence", _Boom()):
            composed, results = compose(retired, changed, Path("/nonexistent"), "x", "y", Path("/tmp"))
        assert composed == "major", composed
        assert results == [{"version": "2.0.0", "kind": "retired", "bump": "major", "evidence": None}]

    print("OK: versions_from_composed_evidence + diff_versions/compose, a version retired from "
          "the composed artefact's own member set classifies major with no policy diff anywhere "
          "in ludlow's own repo -- ADR-0011's 'the composed bump is computed after composition', "
          "proved end to end")

    print("PASS: adopter_gate.py selfcheck (declared_bump, diff_versions, compose -- retirement=major, "
          "strictest-wins, verification-failure-refuses, wrap_section brackets the markers, "
          "splice_body appends on a first run and replaces in place on a re-run without touching "
          "Renovate's own content, survives backslash-bearing evidence across two consecutive "
          "re-runs without re.sub() misreading it as a backreference, and repairs an ORPHANED "
          "SECTION_START -- a GitHub PR-body-truncation shape -- in place across repeated "
          "truncate/repair cycles instead of accumulating duplicate spans (bug #1); read_pin, "
          "read_versions and verify_evidence each refuse with a specific message instead of "
          "crashing on platform-shaped YAML/JSON this institution does not control, and run()'s "
          "safety net catches even an unanticipated exception type and still returns a refusal, "
          "never an unhandled traceback (bug #2))")


PARTY = "ludlow"

# --------------------------------------------------------------------------
# Ticket 43 (ticket 18 Answer 4): the per-institution matrix row, computed
# HERE, by the adopter.
#
# The publisher's `matrix` is empty and says so: NORTH-STAR §2 forbids
# platform reading this repository, and a hub-maintained pins file is the
# central catalogue ticket 04 refused. So the row about ludlow's own pin is
# computed by ludlow, running platform's PUBLISHED computed-semver package
# against ludlow's OWN claimed policy versions, with ludlow's OWN workloads
# added to the generated corpus, and lands in ludlow's own composed
# evidence.
#
# This is not "recomputing the publisher's answer" (ADR-0011 still holds):
# the publisher's number is the strictest band across its whole window, and
# this is the band for ONE pin -- the one this institution is actually
# running. Two different questions, and only the adopter can ask the second,
# because only the adopter knows what it claims and what it runs.
# --------------------------------------------------------------------------
CLAIM_LABEL = "policy-as-versioned.dev/policy-version"
GOVERNED_LABEL = "policy-as-versioned.dev/governed"


def _docs(path: Path) -> list[dict]:
    try:
        return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]
    except (yaml.YAMLError, UnicodeDecodeError):
        return []


def claimed_versions(adopter_dir: Path) -> dict[str, list[Path]]:
    """Every policy version THIS repository's own manifests claim, and the
    workload files claiming it. Read here, never from the publisher: the row
    is about what this institution actually runs. `composed/` is skipped --
    those are the rendered policy bodies, not workloads."""
    claims: dict[str, list[Path]] = {}
    for path in sorted(adopter_dir.rglob("*.yaml")):
        if ".git" in path.parts or "composed" in path.parts:
            continue
        for doc in _docs(path):
            if doc.get("kind") != "Pod":
                continue
            version = ((doc.get("metadata") or {}).get("labels") or {}).get(CLAIM_LABEL)
            if version:
                claims.setdefault(str(version), []).append(path)
    return claims


def governed_namespace(adopter_dir: Path) -> dict | None:
    """This institution's own governed Namespace manifest -- the object that
    declares the cage tier (ADR-0022). It rides beside every extra corpus
    entry as the `.ns.yaml` sibling cage_engine.namespace_for reads, so the
    workload is classified in the cage it really runs in, not in the
    unlabelled default."""
    for path in sorted(adopter_dir.rglob("*.yaml")):
        if ".git" in path.parts:
            continue
        for doc in _docs(path):
            if doc.get("kind") == "Namespace" and \
                    ((doc.get("metadata") or {}).get("labels") or {}).get(GOVERNED_LABEL) == "true":
                return doc
    return None


def matrix_row(platform_dir: Path, adopter_dir: Path, party: str = PARTY) -> dict:
    """One row per policy version this institution claims: the bump IT takes
    moving from its own pin to the version the publisher's array now
    declares, computed with the published package over the published corpus
    plus this institution's own workloads."""
    sys.path.insert(0, str(Path(platform_dir) / "computed-semver"))
    import comparison_window          # noqa: E402  -- the PUBLISHED package
    import corpus_generator           # noqa: E402

    dist = Path(platform_dir) / "distribution"
    array = [str(e["version"])
             for e in corpus_generator._orphan_guard.elements(dist / "versions.yaml")]
    if not array:
        raise SystemExit("FAIL: platform's versions.yaml declares no versions")
    declared = max(array, key=comparison_window.parse_semver)
    tree_for = lambda v: dist / "policies" / f"v{v}"          # noqa: E731
    ns = governed_namespace(Path(adopter_dir))

    rows: dict[str, dict] = {}
    for version, workloads in sorted(claimed_versions(Path(adopter_dir)).items(),
                                      key=lambda kv: comparison_window.parse_semver(kv[0])):
        relative = [str(w.relative_to(adopter_dir)) for w in workloads]
        if version not in array:
            rows[version] = {
                "pinned_version": version, "computed_bump": None, "movement": [],
                "extra_corpus_entries": relative,
                "note": (f"{version} is not in the publisher's declared version array "
                         f"({', '.join(array)}) -- it is retired or was never published, so there "
                         f"is no line to classify. This institution is claiming a version nothing "
                         f"serves; that is the row, not a missing row."),
            }
            continue
        if comparison_window.parse_semver(version) >= comparison_window.parse_semver(declared):
            rows[version] = {
                "pinned_version": version, "computed_bump": "none", "movement": [],
                "extra_corpus_entries": relative,
                "note": f"already on the newest declared version ({declared}) -- nothing to move to",
            }
            continue

        corpus_dir = Path(tempfile.mkdtemp(prefix=f"matrix-{party}-{version}-"))
        manifest = corpus_generator.build_manifest(
            tree_for(version), tree_for(declared), inside_pin=declared, out_dir=corpus_dir)
        pods = [corpus_dir / rec["file"]
                for rec in manifest["populations"]["generated-spine"]["entries"]]
        # This institution's OWN workloads, added to the generated corpus as
        # extra entries -- each beside a copy of its real governed Namespace,
        # so the cage that classifies it is the cage it actually runs in.
        for i, workload in enumerate(workloads):
            for j, doc in enumerate(d for d in _docs(workload) if d.get("kind") == "Pod"):
                own = corpus_dir / f"own-{i}-{j}.yaml"
                own.write_text(yaml.safe_dump(doc, sort_keys=True))
                if ns is not None:
                    own.with_name(own.stem + ".ns.yaml").write_text(yaml.safe_dump(ns, sort_keys=True))
                pods.append(own)

        window = comparison_window.ComparisonWindow(
            old_window=[version], new_window=array, subject_tree_for=tree_for,
            institution_pins={party: version})
        outcome = comparison_window.evaluate(window, declared, tree_for(declared), pods)
        if outcome.pairing_failure is not None:
            rows[version] = {"pinned_version": version, "computed_bump": None, "movement": [],
                             "extra_corpus_entries": relative,
                             "note": f"pairing failure: {outcome.pairing_failure}"}
            continue
        row = dict(outcome.matrix[party])
        row["extra_corpus_entries"] = relative
        row["corpus_checksum"] = manifest["populations"]["generated-spine"]["checksum"]
        rows[version] = row

    return {
        "party": party,
        "declared_by_publisher": declared,
        "computed_by": "the adopter, with platform's published computed-semver package "
                       "(ticket 18 Answer 4) -- the publisher's own matrix is empty on purpose",
        "generator_version": corpus_generator.GENERATOR_VERSION,
        "rows": rows,
    }


def write_matrix_row(platform_dir: Path, adopter_dir: Path, party: str = PARTY) -> dict:
    """Compute the row and land it in this institution's own composed
    evidence, under `semver_matrix`.
      ponytail: composition.py rewrites composed/evidence.json wholesale on a
      re-compose, so this is re-run after one (shift-left.yml runs it after
      the compose step). Upgrade path: composition carries the key through.
    """
    row = matrix_row(platform_dir, adopter_dir, party)
    evidence_path = Path(adopter_dir) / "composed" / "evidence.json"
    document = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
    document["semver_matrix"] = row
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(document, indent=2))
    return row


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--matrix-row", action="store_true",
                     help="ticket 43 (18 Answer 4): compute THIS institution's per-institution "
                          "matrix row with platform's published computed-semver package, over its "
                          "own claimed versions and its own workloads, and land it in "
                          "composed/evidence.json (needs --platform-dir, --ludlow-dir)")
    ap.add_argument("--print-only", action="store_true",
                     help="with --matrix-row: print the row without writing composed/evidence.json")
    ap.add_argument("--splice-body", action="store_true",
                     help="splice mode (ticket cs-29): merge --section into --current-body "
                          "between the SECTION_START/SECTION_END markers, write --out-body. "
                          "Does none of the gate's own work -- shift-left.yml's own step "
                          "provides --current-body fresh from `gh pr view` each run.")
    ap.add_argument("--current-body", type=Path)
    ap.add_argument("--section", type=Path)
    ap.add_argument("--out-body", type=Path)
    ap.add_argument("--ludlow-dir", type=Path)
    ap.add_argument("--platform-dir", type=Path)
    ap.add_argument("--old-ref")
    ap.add_argument("--new-ref")
    ap.add_argument("--composed-base-ref", default=None,
                     help="ADR-0011: ludlow's own commit-ish for composed/evidence.json 'before'")
    ap.add_argument("--composed-head-ref", default=None,
                     help="ADR-0011: ludlow's own commit-ish for composed/evidence.json 'after'")
    ap.add_argument("--out-comment", type=Path)
    ap.add_argument("--identity-regexp", default=EXPECTED_IDENTITY_REGEXP)
    ap.add_argument("--issuer", default=EXPECTED_ISSUER)
    args = ap.parse_args(argv)

    if args.selfcheck:
        selfcheck()
        return 0

    if args.matrix_row:
        if args.platform_dir is None:
            ap.error("--platform-dir is required with --matrix-row")
        adopter_dir = args.ludlow_dir or Path(".")
        row = (matrix_row(args.platform_dir, adopter_dir) if args.print_only
               else write_matrix_row(args.platform_dir, adopter_dir))
        print(json.dumps(row, indent=2))
        return 0

    if args.splice_body:
        missing = [n for n in ("current_body", "section", "out_body") if getattr(args, n) is None]
        if missing:
            ap.error(f"--splice-body needs: {', '.join('--' + m.replace('_','-') for m in missing)}")
        args.out_body.write_text(splice_body(args.current_body.read_text(), args.section.read_text()))
        return 0

    missing = [n for n in ("ludlow_dir", "platform_dir", "old_ref", "new_ref", "out_comment")
               if getattr(args, n) is None]
    if missing:
        ap.error(f"missing required arguments: {', '.join('--' + m.replace('_','-') for m in missing)}")

    code, comment = run(args.ludlow_dir, args.platform_dir, args.old_ref, args.new_ref,
                         args.identity_regexp, args.issuer,
                         composed_base_ref=args.composed_base_ref, composed_head_ref=args.composed_head_ref)
    args.out_comment.write_text(wrap_section(comment))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
