# What is vendored here, and at which ref

Authored by eco-system ticket 64, the same shape ticket 29 built for driftwood. Ticket 29's own
Answer claimed all three adopters and only driftwood had one; that Answer is corrected with a
dated note in the hub.

## `world/` -- the twin's shared world layer

An overlay may reference the world layer and the world layer may never reference an overlay, and
`twin/model.py Overlay.load` resolves `world_ref` on the **same** `ModelRepo`. So an overlay that
lives in an adopter's own repository must carry the world layer in the same git tree, or the
loader would have to learn a second repository (ticket 11 answer item 1). It is vendored, not
imported.

| | |
|---|---|
| Source repository | `policy-as-versioned-flux` (the hub) |
| Source release | `twin` **0.1.0** (`twin/VERSION`), pinned machine-readably in `PIN.yaml` |
| Tag the owner must cut | `twin/v0.1.0` -- **not cut yet**, see below |
| Source path | `twin/fixtures.py`, the `LIBRARY_WORLD_FILES` mapping |
| Files | 30: `world/meta.yaml`, 15 components, 13 propositions, 1 world model |
| Copied | byte-for-byte, verbatim, no edits |
| Stages to | `world_ref: c2d07330a778ed547b60cfbb87217bcf9813181f` in `orgs/ludlow/meta.yaml` |

The same sha driftwood's overlay pins, and that is a checkable fact rather than a coincidence: the
staging mirror commits `world/` alone in its first commit, so identical bytes stage to an identical
content-addressed commit in every adopter's repository.

Two pins, and they check each other. `PIN.yaml`'s `twin_version` must equal the hub's
`twin/VERSION` or `emit-forward-intel.py` refuses -- the release these bytes came from cannot
silently move underneath them. `world_ref` must equal the commit the vendored bytes stage to in
the emitter's deterministic mirror, or it refuses again.

**The tag.** `twin/v0.1.0` is prefixed because the hub repository is not only the twin. It does
not exist yet: a signed tag is cut by a release workflow with gitsign, never on a laptop, so until
the owner dispatches that workflow, `PIN.yaml` carries `tag_cut: false`. Its full
`hub_commit` pins genuinely published producer code, while `world_ref` pins the vendored
world bytes independently.

Re-vendoring is a two-line job:

```sh
.venv/bin/python -c 'import pathlib; from twin.fixtures import LIBRARY_WORLD_FILES as W; [ (pathlib.Path(".estate-clone/ludlow/twin")/r).write_text(b, encoding="utf-8", newline="\n") for r,b in W.items() ]'
.venv/bin/python .estate-clone/ludlow/twin/emit-forward-intel.py   # refuses until world_ref is re-pinned
```

### The priors in `world/world_models/reference-map.yaml` are AUTHORED, not measured

Every causal edge in this estate carries an `evidence_grade` and a written basis. The prior
beliefs in the reference map carry neither, because the `world_models` schema has no grade field:
they are floats typed into `twin/fixtures.py` by whoever added the scenario class. Vendoring puts
them inside this repository's own signed tree, where they read like measured facts. The forward-intel producer does not read those authored priors: its money comes from the
declared native filing, causal edge and response mechanisms. Read every number in that file as
an authored prior, not an observed frequency.

## The declared financial and evidence instruments

Ludlow's declared USD turnover and service-fee share derive its native USD cash flow
as at 2025-12-31. The GBP perspective requires the genuine signature-verified December 2025
FX instrument: `fx/v2.0.0`, whose USD rate is 1.3126 units per GBP. An absent signature,
rate or matching valuation month remains `CANNOT LOOK` (exit 3), never a guessed amount.

Both the valuation and the loss mechanism retain evidence grade 3: published comparable
work, **not observed here**. The party explicitly declares `pricing_threshold: 3`, which
admits that grade without a regrade event. Grade-5 mitigation remains unpriced. The producer
borrows the subscribed threat-register frequency explicitly; the comparable enforcement
record is no claim that this institution experienced that event.

The first forward-intel v1 envelope is authored on 2026-10-04. Its ordinary publisher rule,
bump and discovery declaration are reviewed with the source. Local emission is not an
authentic signed release, delivered application, or scheduled live observation.

## `forward-intel/payload.schema.json`

This is the adopter's owned schema for its forward-intel envelope. Its base is the
immutable `platform/feeds/forward-intel.payload.schema.json` at authenticated tools
v5.0.0 (`703eff6aee959843c4160aa54fd03413f62858cc`). It preserves every canonical
property, requirement and type. Ticket 144 adds exactly two optional declarations:
`rests_on_grade` (integer grades 1–3) and `valuation` (the native amount/currency,
party fact, reporting amount/currency and nullable dated FX record). No inherited
constraint is removed and the closed property set remains closed.

The active schema is an owned extension, not a byte-for-byte vendored copy. It lives
inside this publishing repository because the envelope resolves `payload_schema`
here, and the feed can be validated offline from these self-contained bytes.
`verify-twin-overlay.sh` checks the complete canonical base semantically and the
exact two optional additions against the materialized authentic platform schema.
It reports could-not-look if that parent is absent; absence never proves agreement.

## `ladder.yaml` -- the rungs, and why they are not read from a selection policy

This repository also ships a versioned `selection-policy` package. Its forward-intel
producer reads its curve rungs from the separate `ladder.yaml` declaration; it does not select
a delivered tier. The ladder records the platform release that published the rungs
(`graded/cage.py`, `ORDER`, TABLE_VERSION 1.0.0, at platform v2.0.1) and is checked against that
release's own module when a platform checkout is present.

## The twin has no representation for this party's regulated data, and says so

Found while authoring this overlay, 2026-09-04. `twin/schema.py:refuse_special_category` refuses
an Article 9 special category anywhere in a loaded document, at any depth, as a key or a value,
by blunt substring match -- its own docstring says "a false positive costs an author one rename,
a false negative puts an Article 9 record in the repository". This party administers a US benefit
plan, so the records it holds ARE such a category, and three separate documents were refused at
load before this overlay would parse: the data component, an affected-parties line, and the
perspective's own trading name.

The response is not a rename to get past the check. This overlay models the record STORE, its
dependency on the adjudication service and the cage it sits behind, and deliberately models no
category, cohort or attribute of the people in it -- which is what the refusal exists to secure.
The limit is stated in `orgs/ludlow/components/member-record-store.yaml` itself rather than worked
around silently.

The residue is real and is named here rather than hidden: an adopter whose own trading name
contains one of those words cannot be described by name in a loaded document. That is a fact about
the model worth an owner's attention, not a defect this ticket may fix by loosening the check.
