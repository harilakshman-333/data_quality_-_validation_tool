# Miraxis Cheat Sheet

## What This Repo Is

`miraxis` is a dataset quality tool for LeRobotDataset data.

It does three main things:

- `lint`: inspect a dataset and report problems
- `fix`: repair a subset of known, repairable problems
- `web`: serve a local read-only dashboard over one lint result

The core rule of the repo is:

1. Load a dataset safely.
2. Convert it into one canonical in-memory model.
3. Run checks against that model.
4. Render the results.
5. Optionally apply copy-on-write repairs.

---

## Codebase By Category

### 1. Entry Points

- `src/miraxis/cli.py`: Typer CLI with `lint`, `fix`, and `web`
- `src/miraxis/__main__.py`: package entry point
- `src/miraxis/__init__.py`: package version/export surface

Use this area when you want to understand how a command is wired, not where business logic lives.

---

### 2. Source Layer

Purpose: safely turn a user ref into something readable by the rest of the system.

- `src/miraxis/sources/loader.py`: resolves local path vs Hub ref and returns `SourceHandle`
- `src/miraxis/sources/info.py`: parses and validates `meta/info.json`
- `src/miraxis/sources/version.py`: cross-checks declared version vs on-disk layout
- `src/miraxis/sources/paths.py`: prevents path traversal / root escape
- `src/miraxis/sources/bounds.py`: enforces hard limits on declared counts
- `src/miraxis/sources/handles.py`: lazy openers for Parquet and video shards

Key idea: this is the only layer that performs dataset read I/O directly.

---

### 3. Canonical Model Layer

Purpose: normalize version-specific dataset metadata into one typed model.

- `src/miraxis/model/__init__.py`: `build_canonical_dataset()`
- `src/miraxis/model/canonical.py`: `CanonicalDataset`, `EpisodeRecord`, `FeatureSpec`, `VideoSegment`
- `src/miraxis/model/adapters.py`: version-specific translation from raw metadata to canonical objects
- `src/miraxis/model/stats.py`: lazy stats access

Key idea: this layer represents the dataset; it does not judge whether the dataset is good.

---

### 4. Check Engine

Purpose: run all validation rules against a `CanonicalDataset`.

- `src/miraxis/checks/protocol.py`: `Severity`, `CheckContext`, `CheckResult`, `Check`
- `src/miraxis/checks/registry.py`: singleton registry of checks
- `src/miraxis/checks/engine.py`: runs checks and converts crashes into `ERROR` results

Check categories:

- `src/miraxis/checks/structural.py`: schema, indexes, metadata/data agreement, path resolution
- `src/miraxis/checks/semantic.py`: feature meaning/integrity checks
- `src/miraxis/checks/temporal.py`: timestamp monotonicity, spacing, drift fingerprints
- `src/miraxis/checks/statistical.py`: stats.json agreement and numeric sanity
- `src/miraxis/checks/video.py`: video decodability checks
- `src/miraxis/checks/utils.py`: caching helpers used by checks
- `src/miraxis/checks/welford.py`: streaming numeric accumulation

Key idea: one broken check should not crash the whole lint run.

---

### 5. Report Layer

Purpose: render one lint result in different formats.

- `src/miraxis/report/terminal.py`: Rich terminal rendering
- `src/miraxis/report/json_report.py`: machine-readable JSON
- `src/miraxis/report/html_report.py`: standalone HTML
- `src/miraxis/report/sarif.py`: SARIF for CI tooling
- `src/miraxis/report/fix_report.py`: repair dry-run / apply summaries
- `src/miraxis/report/trust_score.py`: trust score formula
- `src/miraxis/report/__init__.py`: report exports

Key idea: renderers should consume results, not re-run checks.

---

### 6. Repair Layer

Purpose: fix a small set of known issues without mutating the source dataset.

- `src/miraxis/repair/protocol.py`: fixer/diff types
- `src/miraxis/repair/orchestrator.py`: selects and chains fixers
- `src/miraxis/repair/episode_reindex.py`: repair metadata/data boundary mismatches
- `src/miraxis/repair/timestamp_dedrift.py`: repair cumulative timestamp drift
- `src/miraxis/repair/stats_recompute.py`: recompute stats.json from data
- `src/miraxis/repair/__init__.py`: exports

Key idea: repairs are copy-on-write. The original dataset is never edited in place.

---

### 7. Web Layer

Purpose: serve a read-only local UI over one already-computed lint report.

- `src/miraxis/web/app.py`: FastAPI app factory
- `src/miraxis/web/server.py`: local server runner
- `src/miraxis/web/static/index.html`: dashboard shell
- `src/miraxis/web/static/app.js`: browser-side rendering logic
- `src/miraxis/web/static/style.css`: dashboard styling

Key idea: the browser never chooses the dataset path; the CLI computes the report first.

---

### 8. Support Modules

- `src/miraxis/errors.py`: typed exception hierarchy
- `src/miraxis/logging.py`: structured logging setup
- `src/miraxis/synth/`: future synthesis surface / placeholder package

---

### 9. Tests

- `tests/unit/`: narrow module-level behavior tests
- `tests/property/`: Hypothesis property tests for invariants
- `tests/fixtures/`: synthetic dataset builders and corpus helpers

Use tests as executable documentation when a module's behavior is unclear.

---

### 10. Repo Meta

- `pyproject.toml`: packaging, dependencies, tool config, CLI entrypoint
- `README.md`: user-facing overview and usage
- `scripts/audit_hub.py`: real-world Hub dataset audit runner
- `docs/CODEBASE_EXPLANATION.md`: longer architectural explanation

---

## Codebase By Execution Path

### Path A: `miraxis lint <ref>`

1. `src/miraxis/cli.py`
   `lint()` parses flags and builds the check context.
2. `src/miraxis/sources/loader.py`
   `SourceLoader.resolve(ref)` resolves local path or Hub metadata cache.
3. `src/miraxis/sources/info.py`
   `load_info()` validates `meta/info.json`.
4. `src/miraxis/sources/version.py`
   `detect_version()` verifies metadata version matches layout.
5. `src/miraxis/model/__init__.py`
   `build_canonical_dataset(handle)` creates `CanonicalDataset`.
6. `src/miraxis/checks/engine.py`
   `CheckEngine.run(ds, ctx)` runs all registered checks.
7. `src/miraxis/report/*`
   Renderer outputs terminal, JSON, HTML, or SARIF.
8. `src/miraxis/cli.py`
   Exit code is chosen from the worst severity.

---

### Path B: `miraxis fix <ref>`

1. Run the same load + canonicalize + check steps as `lint`.
2. `src/miraxis/repair/orchestrator.py`
   Determine which fixers apply from the lint results.
3. Apply fixers in order:
   `episode_reindex` -> `timestamp_dedrift` -> `stats_recompute`
4. Each fixer copies the dataset tree and rewrites only its own slice.
5. `src/miraxis/report/fix_report.py`
   Render the dry-run or apply summary.

---

### Path C: `miraxis web <ref>`

1. Run the same load + canonicalize + check steps as `lint`.
2. `src/miraxis/report/json_report.py`
   Build one report JSON string.
3. `src/miraxis/web/app.py`
   Create the FastAPI app around that fixed JSON payload.
4. `src/miraxis/web/server.py`
   Serve locally on `127.0.0.1`.

---

## The Most Important Objects

- `SourceHandle`: resolved dataset root + version + parsed `info.json`
- `CanonicalDataset`: version-agnostic in-memory dataset view
- `CheckContext`: runtime knobs for checks, mainly `deep`
- `CheckResult`: one check outcome
- `Severity`: `INFO`, `WARN`, `FAIL`, `ERROR`
- `Diff`: structured repair preview
- `RepairSummary`: aggregate output of a fix run

---

## Fast Answers To Common Questions

### Where does real dataset I/O happen?

Only in `src/miraxis/sources/`.

### Where does format branching happen?

Primarily in `src/miraxis/model/adapters.py`.

### Where are validation rules defined?

In `src/miraxis/checks/*.py`.

### Where are terminal outputs built?

In `src/miraxis/report/terminal.py` and `src/miraxis/report/fix_report.py`.

### Where does repair order live?

In `src/miraxis/repair/orchestrator.py`.

### Where do security protections live?

Mostly in:

- `src/miraxis/sources/paths.py`
- `src/miraxis/sources/bounds.py`
- `src/miraxis/sources/version.py`
- `src/miraxis/web/app.py`

---

## Minimal Mental Model

Think of the repo as this pipeline:

```text
user ref
  -> source resolution
  -> metadata validation
  -> canonical dataset model
  -> checks
  -> report
  -> optional repair
```

If you are debugging:

1. Start at the command in `cli.py`.
2. Find the handoff into `sources/` or `repair/`.
3. Follow the object boundary (`SourceHandle`, `CanonicalDataset`, `CheckResult`, `Diff`).
4. Use the matching unit test as the fastest behavior spec.
