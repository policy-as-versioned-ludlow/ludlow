# reports — ludlow's own application

Lifted into ludlow by eco-system ticket 33 from `policy-as-versioned-flux/reports` at commit
`b809e063514dedee5a1df8701d71d3a1856d5693`. Ticket 13's resolution put it here: ludlow is the
health institution, and reporting over member records is a health plan's application.

**This is ludlow's artefact now.** It is versioned by ludlow's own tags, its served workload
manifest is `gitops/apps/reports.yaml` (rendered by `gitops/apps/kustomization.yaml`, which is
what this repository's Flux Kustomization reconciles at `path: ./gitops/apps`), it is graded by ludlow's
own `shift-left` job against ludlow's own composed policy set, and its dependency tree is bumped
by ludlow's own `renovate.json`. Nothing outside this repository reads it.

The tree below is the incumbent repository's tree, unchanged except for the four things a lift
changes: its `k8s/` manifest is removed (superseded by the served manifest above, re-labelled
and re-namespaced), its own `renovate.json` stub is removed (superseded by this repository's),
its release workflow is removed (see the residual below), and this README is rewritten -- the
incumbent's described a repository, this one describes a lift. Every other file is
byte-identical, so that a reader can `git diff` the tree against
`policy-as-versioned-flux/reports` at that commit and see the whole of the move: `diff -rq`
against the incumbent reports `Only in incumbent: .github, k8s, renovate.json` and
`README.md differ`, and nothing else.

## The point of this app

The middle case: a real, resolvable, moderately old Python tree — Flask 1.1.4 and its era's
Jinja2, Werkzeug, itsdangerous and click (2020). Not the laggard (that is tuppence's `ledger`),
not current.

## The residual: who builds the image

`gitops/apps/reports.yaml` pins
`ghcr.io/policy-as-versioned-flux/reports@sha256:36dc3d7d1bd5193f46a55d57b505beb5e99d7925f65b0fad3c1f7d1aeafefcf5`
— the digest the incumbent repository's own manifest pinned, built and published by the incumbent
org. The source moved and the build did not. Moving the build needs a new workflow job in this
repository and a container registry under `policy-as-versioned-ludlow`; both are on ticket 33's
`## Waits on the owner`. The hub's `verify/lifted-apps/` check counts the lifted apps whose image
is still published by the incumbent org and prints that count on every run, so this paragraph
cannot quietly stop being true without the gate saying so.
