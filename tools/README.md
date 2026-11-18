# Build tools

Helpers for regenerating the proposal documents.

## One-time setup

`matplotlib` is pinned in the repo's `requirements-dev.txt` and locked (with
hashes) in `requirements-dev.lock`, so install from there rather than
pulling an unpinned copy:

```bash
make install            # from the repo root: creates .venv from requirements-dev.lock
```

or, equivalently:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements-dev.lock
```

## Regenerate the architecture diagram

> **Canonical diagram:** `images/bedrock-guardrails-architecture-v2.svg` is what the README and blog reference. It depicts only what this repository builds or documents (Layers 1, 3, 4; CDK stacks; CI; CloudTrail queries) and marks the optional SCP as "not shipped". The SVG was hand-finished from the layout this generator produces; the generator is kept so the layout can be re-derived from code. If you change what the repository builds, update the SVG (and this generator's labels) in the same change.

```bash
.venv/bin/python tools/generate_architecture_diagram.py
# → images/architecture-draft.png  (layout reference for editing the canonical SVG; not referenced by any doc)
```

Edit `tools/generate_architecture_diagram.py` to tweak colours, layout, or
text, then re-run it and commit the PNG alongside the script change.

## Regenerate the flow / hierarchy diagrams

```bash
.venv/bin/python tools/generate_flow_diagram.py
.venv/bin/python tools/generate_hierarchy_diagram.py
```
