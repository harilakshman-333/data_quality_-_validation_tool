# miraxis — Codebase Explanation

## Overview

**miraxis** is a data quality and validation tool for [LeRobotDataset](https://github.com/huggingface/lerobot) — the open robot-learning dataset format developed by Hugging Face. It is described in the README as "ruff for robot data": a lint, fix, and synthesis tool for ensuring clean, trustworthy training data.

The project targets LeRobotDataset format versions **v2.0**, **v2.1**, and **v3.0**, and can operate on datasets stored locally or streamed from the Hugging Face Hub.

---

## High-Level Architecture

The system is divided into six functional layers that communicate through clean, typed boundaries:

```
CLI / Web / SDK
     │
     ▼
Source Layer  ──── resolves references, detects format versions
     │
     ▼
Canonical Model ── version-agnostic in-memory view of the dataset
     │
     ▼
Check Engine ────── runs all applicable checks against the model
     │
     ▼
Report Layer ─────  terminal / JSON / HTML / SARIF output
     │
     ▼
Repair Layer ─────  copy-on-write fixers for repairable issues
```

The CLI and Web server are intentionally thin shells over the library. No lint or repair logic lives in either of them.

---

## Module-by-Module Breakdown

### `src/miraxis/cli.py` — Command-Line Interface

The entry point registered as the `miraxis` command in `pyproject.toml`. Built with [Typer](https://typer.tiangolo.com/), it exposes three subcommands:

- **`miraxis lint <ref>`** — loads a dataset, runs all checks, and renders the results. Accepts flags for JSON output (`--json`), HTML report (`--report`), SARIF output (`--sarif`), and deep mode (`--deep`). Exits with code `0` (clean), `1` (WARN present), or `2` (FAIL/ERROR).

- **`miraxis fix <ref>`** — runs lint, then selects and runs applicable repair fixers. Dry-run by default; `--apply --out <path>` writes a repaired copy. Exits with `0` (nothing to fix), `1` (fixes proposed/applied), or `2` (failure).

- **`miraxis web <ref>`** — lints the dataset once and serves a read-only HTML dashboard. Binds only to `127.0.0.1`.

All heavy logic is delegated to library modules; the CLI never contains domain logic.

---

### `src/miraxis/sources/` — Dataset Source Layer

This layer is the **only place miraxis performs filesystem or network I/O** when reading a dataset.

| File | Responsibility |
|---|---|
| `loader.py` | `SourceLoader.resolve()` — turns a local path or Hub repo id into a `SourceHandle` |
| `info.py` | Parses `meta/info.json` into a typed `DatasetInfoModel` (Pydantic) |
| `version.py` | `detect_version()` — cross-checks the declared `codebase_version` against the actual directory layout |
| `handles.py` | Opens Parquet shards and video shards as lazy handles |
| `paths.py` | `safe_join()` — prevents path traversal attacks by rejecting any resolved path that escapes the dataset root |
| `bounds.py` | Hard ceilings (`MAX_DECLARED_EPISODES = 1_000_000`, `MAX_DECLARED_FRAMES = 500_000_000`) to refuse malformed or hostile datasets before iteration begins |

**Hub access** is lazy and opt-in: if the `ref` argument does not resolve to a local directory, `SourceLoader` attempts to use `huggingface_hub.snapshot_download`. If the `[hub]` extra is not installed, it raises a clean `SourceResolutionError` with an installation hint instead of crashing.

**Version detection** (in `version.py`) does not trust `codebase_version` in `info.json` alone. It cross-checks the claimed version against the actual on-disk directory shape:
- `v3.0` requires `meta/episodes/` to be a directory of sharded Parquet files.
- `v2.x` requires `meta/episodes.jsonl` to be a flat file.
A mismatch raises `DatasetFormatError`.

---

### `src/miraxis/model/` — Canonical Dataset Model

The model layer builds a **version-agnostic, typed in-memory view** of the dataset's declared structure. It never reads frame data or video bytes — only metadata is materialized.

| Class | Purpose |
|---|---|
| `CanonicalDataset` | The central view object: holds `version`, `fps`, `features`, `num_episodes`, `num_frames`, `task_table`, `cameras`, `stats`, and a list of `EpisodeRecord`s |
| `EpisodeRecord` | One episode's declared metadata: `episode_index`, `length`, `tasks`, `dataset_from_index`, `dataset_to_index` |
| `FeatureSpec` | A single feature from `info.json`: `name`, `dtype`, `shape`, `names` |
| `VideoSegment` | A lazy handle to a video shard (episode × camera) |
| `ShardResolver` | A Protocol (interface) for version-specific Parquet/video lookups; implemented in `adapters.py` |
| `StatsHandle` | In `stats.py`: lazy access to global and per-episode `meta/stats.json` |

The `build_canonical_dataset(handle)` function (in `model/__init__.py`) is the factory that constructs a `CanonicalDataset` from a `SourceHandle`. It dispatches to version-specific adapters in `model/adapters.py`.

**The model never judges the data** — whether declared metadata agrees with actual row counts, or whether timestamps are monotonic, is entirely the Check Engine's job.

---

### `src/miraxis/checks/` — Check Engine and Rules

#### `protocol.py` — Core Types

All checks share these common types:

- **`Severity`** (`StrEnum`): `INFO < WARN < FAIL < ERROR`. Custom comparison operators allow `max(severities)` to work correctly.
- **`CheckContext`**: Runtime context passed to every check — currently just a `deep: bool` flag.
- **`CheckResult`**: The output of one check: `check_id`, `severity`, `message`, and a `details` dict for machine consumers.
- **`Check`** (Protocol): The interface every check must satisfy — `id`, `severity`, `category`, `requires_video`, and `run(ds, ctx) -> CheckResult`.

#### `registry.py` — Check Registry

A **singleton, append-only registry** (`registry`) that holds all check instances keyed by their `id`. Each check module registers its checks at module import time with `registry.register(check_instance)`. The engine queries `registry.all_checks()` at runtime.

#### `engine.py` — Check Engine

`CheckEngine.run(ds, ctx)` iterates over all registered checks and runs each one. Skipping rules:
1. A check with `requires_video=True` is skipped when the dataset has no cameras.
2. All other checks run unconditionally.

**ADR-003 (crash isolation)**: Every `check.run()` call is wrapped in a broad `try/except`. If a check raises any exception, the engine converts it into a `CheckResult(severity=ERROR, ...)` rather than letting the exception propagate. This prevents one bad check from aborting the entire lint run.

#### Check Modules

Checks are grouped into five modules, each self-registering at import time:

| Module | Check IDs | Default Severity |
|---|---|---|
| `structural.py` | `STRUCTURAL.VERSION_DETECTED` | INFO |
| | `STRUCTURAL.SCHEMA_CONSISTENCY` | FAIL |
| | `STRUCTURAL.INDEX_CONTINUITY` | FAIL |
| | `STRUCTURAL.METADATA_DATA_AGREEMENT` | FAIL |
| | `STRUCTURAL.PATH_TEMPLATE_RESOLVES` | FAIL |
| `semantic.py` | `SEMANTIC.FEATURE_DIMENSIONALITY` | FAIL |
| | `SEMANTIC.TASK_INTEGRITY` | FAIL |
| | `SEMANTIC.LANGUAGE_PRESENT` | WARN |
| | `SEMANTIC.CAMERA_INTRINSICS_PLAUSIBLE` | INFO |
| `temporal.py` | `TEMPORAL.TIMESTAMP_MONOTONIC` | FAIL |
| | `TEMPORAL.TIMESTAMP_SPACING` | WARN |
| | `KNOWNBUG.TIMESTAMP_DRIFT` | FAIL |
| `statistical.py` | `STATISTICAL.STATS_MATCH_DATA` | FAIL |
| | `STATISTICAL.PER_EPISODE_STATS_MATCH` | WARN |
| | `STATISTICAL.VALUE_SANITY` | WARN |
| `video.py` | `VIDEO.DECODABLE_SPOTCHECK` | FAIL |

**Notable checks:**
- `STRUCTURAL.METADATA_DATA_AGREEMENT` catches the class of corruption documented in lerobot issue [#2401](https://github.com/huggingface/lerobot/issues/2401): declared episode lengths disagree with actual Parquet row counts.
- `KNOWNBUG.TIMESTAMP_DRIFT` fingerprints the cumulative timestamp drift bug from lerobot issue [#3177](https://github.com/huggingface/lerobot/issues/3177).
- Statistical checks (`STATS_MATCH_DATA`, `PER_EPISODE_STATS_MATCH`, `VALUE_SANITY`) are skipped over Hub HTTP by default — too slow without materializing all data. Pass `--deep` to force them.

#### Supporting Utilities

- `welford.py` — `WelfordAccumulator`: numerically stable online mean/std/min/max for streaming stats recomputation without loading full data into memory.
- `utils.py` — `ShardColumnCache`: caches opened Parquet column arrays per episode to avoid re-reading the same shard for multiple checks.

---

### `src/miraxis/repair/` — Repair Engine

The repair engine implements copy-on-write dataset repair. It is composed of three independent fixers applied in a fixed order.

#### `protocol.py` — Fixer Protocol and Diff Types

- **`FrameChange`**: Describes a single frame-level change (which episode, frame, shard, column, old value, new value).
- **`StatChange`**: Describes a single stats entry change (feature, stat key, old value, new value).
- **`BoundaryChange`**: Describes a change to an episode's declared boundary metadata.
- **`Diff`**: A collection of changes (any mix of the above) produced by a fixer's dry run, along with the `check_id` it targets.
- **`Fixer`** (Protocol): Every fixer must implement `dry_run(ds) -> Diff` and `apply(ds, output_path) -> Diff`.

#### The Three Fixers

| Module | Fixer | Targeted Check | What it fixes |
|---|---|---|---|
| `timestamp_dedrift.py` | `TimestampDedriftFixer` | `KNOWNBUG.TIMESTAMP_DRIFT` | Resets accumulated timestamp drift — replaces each frame's timestamp with its ideal value `frame_index / fps`. |
| `stats_recompute.py` | `StatsRecomputeFixer` | `STATISTICAL.STATS_MATCH_DATA` | Streams all numeric feature columns through Welford accumulators and rewrites `meta/stats.json` with the correct values. |
| `episode_reindex.py` | `EpisodeReindexFixer` | `STRUCTURAL.METADATA_DATA_AGREEMENT` | Recomputes `dataset_from_index`, `dataset_to_index`, and `length` in episode metadata from actual Parquet row counts. |

#### `orchestrator.py` — Fixer Orchestration

`run_dry_run(ds, results)` and `run_apply(ds, results, out_path)` are the library-level entry points. The orchestrator:

1. **Selects** applicable fixers: a fixer is applicable when its target `check_id` appears in the lint results at severity `WARN` or above.
2. **Chains** fixers in a fixed order: `episode_reindex` → `timestamp_dedrift` → `stats_recompute`. The order matters: `stats_recompute` must run *after* `timestamp_dedrift` so it computes correct statistics over the already-corrected timestamps.
3. **Copy-chains**: each fixer copies the entire dataset tree to a temporary directory and rewrites only its narrow slice. For N fixers, this produces N full copies, with only the last landing at `--out`. Each temporary dataset is reloaded as a fresh `CanonicalDataset` before the next fixer runs.

**Hub datasets are refused**: `refuse_if_hub_ref()` raises `RepairError` with a clean message rather than silently attempting a partial repair on data that is never fully present on disk.

---

### `src/miraxis/report/` — Report Renderers

All renderers receive the same inputs: `ref`, `version`, `num_episodes`, `num_frames`, and `list[CheckResult]`. They never re-run checks.

| Module | Renderer | Output |
|---|---|---|
| `terminal.py` | `render_terminal()` | Color-coded Rich output with per-result labels and a summary table |
| `json_report.py` | `render_json()` | Machine-readable JSON with all results and their `details` dicts |
| `html_report.py` | `render_html()` | Self-contained HTML report |
| `sarif.py` | `render_sarif()` | SARIF 2.1.0 document for CI integration (GitHub Actions annotations, etc.) |
| `fix_report.py` | `render_fix_terminal()` / `render_fix_json()` | Output for the `fix` subcommand's diff preview |
| `trust_score.py` | `compute_trust_score()` | A score in [0, 100] computed from check results |

#### Trust Score Formula (version `"1.0"`)

```
base = 100
subtract 30 per FAIL   (capped at -60 total)
subtract  5 per WARN   (capped at -20 total)
subtract 10 per ERROR  (uncapped)
score = max(0, base)
```

A dataset with any FAIL always scores ≤ 70. The score is a coarse supplementary signal — it never overrides the categorical grade.

---

### `src/miraxis/web/` — Web Dashboard

An optional, security-hardened local web dashboard built with FastAPI.

- **`app.py`** (`create_app(report_json)`): Builds the FastAPI app. The report JSON is computed once at CLI startup and served verbatim from memory. No route accepts a path, ref, or dataset id from the browser — the app is a static read-only shell.
- **`server.py`**: Starts a uvicorn server, binds only to `127.0.0.1`.
- **`static/`**: Self-contained HTML/CSS/JS dashboard frontend.

Security headers set on every response:
- `Content-Security-Policy`: `default-src 'self'` — no unsafe-inline, no unsafe-eval, no third-party origins.
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`

---

## Data Flow: `miraxis lint`

```
User runs: miraxis lint <ref>
      │
      ▼
SourceLoader.resolve(ref)
  → if local path:  read from filesystem
  → if Hub id:      snapshot_download() to local cache
  → parse meta/info.json (Pydantic)
  → detect_version() (cross-check layout vs declared version)
  → check_resource_bound() (refuse absurd declared counts)
  → returns SourceHandle
      │
      ▼
build_canonical_dataset(handle)
  → dispatch to v2.x or v3.0 adapter
  → load episode records (from episodes.jsonl or episodes/ parquet shards)
  → load task table
  → build StatsHandle (lazy: stats.json not parsed yet)
  → returns CanonicalDataset
      │
      ▼
CheckEngine.run(ds, ctx)
  → iterate registry.all_checks()
  → skip checks requiring video if dataset has no cameras
  → call check.run(ds, ctx) for each applicable check
  → catch any exception → ERROR CheckResult (ADR-003)
  → returns list[CheckResult]
      │
      ▼
render_terminal / render_json / render_html / render_sarif
  → compute trust score
  → print or write output
      │
      ▼
sys.exit(0 / 1 / 2) based on worst severity
```

---

## Data Flow: `miraxis fix --apply --out <path>`

```
lint phase (same as above)
      │
      ▼
run_apply(ds, results, out_path)
  → select applicable fixers (those whose check_id appears in results at WARN+)
  → for each fixer in fixed order (episode_reindex → timestamp_dedrift → stats_recompute):
      fixer.apply(current_ds, tmp_dir)  → full tree copy + narrow rewrite
      reload: current_ds = build_canonical_dataset(load(tmp_dir))
  → shutil.move(final_tmp_dir, out_path)
  → returns RepairSummary with per-fixer Diffs
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **ADR-001: Library-first** | All logic lives in importable library modules; CLI and Web are thin shells. Enables SDK use and testing without subprocess overhead. |
| **ADR-002: Canonical model** | Checks operate on a single typed model, never on raw files. Version-specific parsing is isolated to adapters. |
| **ADR-003: Check crash isolation** | A crashing check produces an ERROR result, never an exception. The entire lint run always completes. |
| **ADR-004: Copy-on-write repair** | Source datasets are never mutated. Every fixer copies the full tree, rewrites its slice, and the original is always preserved. |
| **No shell-outs for video** | `av` (PyAV) is used directly for video decode. No `ffmpeg` subprocess — avoids shell injection risk and improves portability. |
| **Lazy data access** | `CanonicalDataset` materializes only metadata. Frame data and video bytes are fetched only when a specific check needs them for a specific episode. |
| **Resource bounds at load time** | Hard ceilings on declared episode/frame counts are enforced before any iteration begins, preventing resource exhaustion from hostile or corrupt datasets. |
| **Path traversal prevention** | `safe_join()` in `sources/paths.py` checks that every resolved path stays within the dataset root, guarding against dataset-committed symlinks or path components like `../`. |

---

## Error Hierarchy (`src/miraxis/errors.py`)

```
MiraxisError
├── DatasetError
│   ├── DatasetFormatError       — malformed/missing metadata, layout mismatch
│   ├── DatasetVersionError      — unsupported codebase_version
│   ├── SourceResolutionError    — path not found or Hub unreachable
│   └── ResourceBoundError       — declared count exceeds hard ceiling
├── CheckExecutionError          — internal; caught by engine before propagation
└── RepairError                  — fixer failed; source dataset always intact
```

---

## Project Configuration

- **Python**: ≥ 3.11
- **Build backend**: `hatchling`
- **Core dependencies**: `pyarrow`, `av`, `pydantic`, `typer`, `structlog`, `numpy`, `rich`
- **Optional extras**:
  - `[hub]`: `huggingface_hub` — required only for Hub dataset access
  - `[web]`: `fastapi`, `uvicorn` — required only for `miraxis web`
  - `[dev]`: testing (`pytest`, `hypothesis`), linting (`ruff`, `mypy`), auditing (`pip-audit`)
- **Linter/formatter**: `ruff` (configured in `pyproject.toml`)
- **Type checker**: `mypy`
- **Test runner**: `pytest` with `hypothesis` for property-based tests

---

## Testing (`tests/`)

The test suite has two layers:

- **`tests/unit/`** — Unit tests for every major module: checks, CLI, model adapters, renderers, repair fixers, source loading, trust score, web app routes, and more.
- **`tests/property/`** — Property-based tests using `hypothesis` for the canonical model, check pipeline, episode reindex, repair, and stats repair.
- **`tests/fixtures/`** — Builders (`builders.py`, `corpus_builders.py`) that generate synthetic in-memory LeRobotDataset trees for testing, including intentionally corrupted variants for each check.

---

## Real-World Validation (`scripts/audit_hub.py`)

`audit_hub.py` runs `miraxis lint --json` against a random sample of public Hub datasets tagged `lerobot`, each in an isolated subprocess with a 60-second timeout, and aggregates the results. This is how the project validates itself against the real diversity of community datasets rather than only its own synthetic fixtures.
