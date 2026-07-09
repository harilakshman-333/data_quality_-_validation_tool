# miraxis User Guide

## What miraxis does

miraxis is a command-line data quality tool for **LeRobotDataset** — the robot-learning dataset format developed by Hugging Face. It has three features:

- **lint** — inspect a dataset and produce a quality report
- **fix** — automatically repair known issues in a local dataset
- **web** — serve a visual dashboard of a lint report in the browser

It works on datasets you have locally on disk, or datasets hosted on the Hugging Face Hub. It never modifies your original data.

---

## Prerequisites

Python 3.11 or 3.12 must be installed.

---

## Installation

```bash
cd /home/kwalker96/projects/data_quality_&_validation_tool
uv venv
source .venv/bin/activate

cd miraxis-main
uv pip install -e ".[dev,hub,web]"
```

Verify it installed correctly:

```bash
miraxis --version
# miraxis 0.2.0
```

The `[hub]` extra is required to lint datasets from the Hugging Face Hub by their repo id.
The `[web]` extra is required for `miraxis web`.

---

## Feature 1: lint

### What it does

`miraxis lint` loads a dataset, runs every applicable quality check against it, and prints a colour-coded report to the terminal. It tells you whether the dataset is safe to train on, has warnings, or has hard failures.

Every time you run lint, miraxis does the following in order:

**Step 1 — Resolve the dataset**

If you pass a local folder path, miraxis reads it directly from disk.
If you pass a Hub dataset id like `lerobot/pusht`, miraxis downloads only the `meta/` folder from the Hub into a local cache at `~/.cache/miraxis/hub/`. The full data and video payload is not downloaded at this step.

**Step 2 — Validate metadata**

miraxis reads `meta/info.json` and verifies it is valid JSON with the required fields: `codebase_version`, `fps`, and `features`. It also checks that the declared dataset version matches the actual folder layout on disk.

**Step 3 — Enforce safety limits**

Before iterating anything, miraxis checks whether the declared episode count or frame count exceeds hard limits (1 million episodes, 500 million frames). This prevents a corrupt or hostile dataset from causing runaway processing.

**Step 4 — Build a canonical model**

miraxis normalises the dataset into a single typed in-memory model (`CanonicalDataset`). This handles all version differences (v2.0, v2.1, v3.0) so every check works the same way regardless of dataset version.

**Step 5 — Run checks**

miraxis runs all registered quality checks in sequence against the model. Each check is independent. If any check crashes internally, the crash is converted to an `ERROR` result and the remaining checks continue running — one broken check never aborts the whole lint run.

**Step 6 — Render the report**

miraxis prints results to the terminal (with colour-coded labels), or writes them to JSON, HTML, or SARIF format depending on your flags.

**Step 7 — Exit with a meaningful code**

- `0` = clean, no issues
- `1` = at least one WARN
- `2` = at least one FAIL or ERROR

This lets `miraxis lint` work as a CI gate.

### Basic usage

```bash
# Terminal report — a Hub dataset
miraxis lint lerobot/pusht

# Terminal report — a local dataset
miraxis lint /path/to/my-dataset

# Machine-readable JSON to stdout
miraxis lint lerobot/pusht --json

# Write an HTML report to a file
miraxis lint lerobot/pusht --report report.html

# Write SARIF output (for GitHub Actions / CI annotations)
miraxis lint lerobot/pusht --sarif report.sarif

# Deep mode — also decodes video and re-checks per-frame stats
# (slow; downloads full dataset payload for Hub refs)
miraxis lint lerobot/pusht --deep

# Verbose logging
miraxis lint lerobot/pusht --verbose
```

### Understanding the output

Each result line shows a severity label and the check id:

```
  ✖ FAIL   STRUCTURAL.SCHEMA_CONSISTENCY
           Parquet column 'action' has dtype int32; declared as float32.

  ⚠ WARN   TEMPORAL.TIMESTAMP_SPACING
           Frame spacing deviates from declared fps in 3 episodes.

  ✔ INFO   STRUCTURAL.VERSION_DETECTED
           Detected format version: v3.0
```

At the end, you get a summary table with counts, an overall grade (PASS / WARN / FAIL / ERROR), and a trust score from 0 to 100.

**Trust score formula:**

```
start at 100
subtract 30 per FAIL   (max deduction from FAILs: 60)
subtract  5 per WARN   (max deduction from WARNs: 20)
subtract 10 per ERROR
score = max(0, result)
```

A dataset with any FAIL scores at most 70.

### What each check looks for

| Category | Check | Severity | What it catches |
|---|---|---|---|
| STRUCTURAL | `VERSION_DETECTED` | INFO | Reports the detected format version |
| STRUCTURAL | `SCHEMA_CONSISTENCY` | FAIL | Column types in Parquet disagree with declared feature shapes in `info.json` |
| STRUCTURAL | `INDEX_CONTINUITY` | FAIL | Gaps or duplicate values in `frame_index`, `episode_index`, or `index` columns |
| STRUCTURAL | `METADATA_DATA_AGREEMENT` | FAIL | Declared episode boundaries disagree with actual row counts in Parquet |
| STRUCTURAL | `PATH_TEMPLATE_RESOLVES` | FAIL | A declared shard path does not point to a readable file |
| SEMANTIC | `FEATURE_DIMENSIONALITY` | FAIL | A feature's actual column width does not match its declared shape |
| SEMANTIC | `TASK_INTEGRITY` | FAIL | A task index reference has no matching task description |
| SEMANTIC | `LANGUAGE_PRESENT` | WARN | An episode has no language or task description |
| SEMANTIC | `CAMERA_INTRINSICS_PLAUSIBLE` | INFO | Advisory; skipped if no intrinsics field is present |
| TEMPORAL | `TIMESTAMP_MONOTONIC` | FAIL | Timestamps are not strictly increasing within an episode |
| TEMPORAL | `TIMESTAMP_SPACING` | WARN | Timestamp spacing is inconsistent with declared fps |
| KNOWNBUG | `TIMESTAMP_DRIFT` | FAIL | Cumulative timestamp drift matching a known upstream lerobot bug |
| STATISTICAL | `STATS_MATCH_DATA` | FAIL | Recomputed global stats diverge from `meta/stats.json` |
| STATISTICAL | `PER_EPISODE_STATS_MATCH` | WARN | Recomputed per-episode stats diverge from stored values |
| STATISTICAL | `VALUE_SANITY` | WARN | NaN, Inf, or implausible numeric values in features |
| VIDEO | `DECODABLE_SPOTCHECK` | FAIL | A sampled video file fails to decode |

> Statistical and video checks are skipped for Hub datasets unless you pass `--deep`.

---

## Feature 2: fix

### What it does

`miraxis fix` runs lint first, then automatically repairs a subset of known issues. Repair is always **copy-on-write**: it copies the dataset to a new location and rewrites only the affected files. Your original data is never changed.

Only local datasets can be repaired. Hub datasets are refused with a clear error because their full data payload is never fully present on disk to copy.

Three fixers are available:

| Fixer | Targeted check | What it does |
|---|---|---|
| `EpisodeReindexFixer` | `STRUCTURAL.METADATA_DATA_AGREEMENT` | Recomputes episode boundary metadata from actual Parquet row counts |
| `TimestampDedriftFixer` | `KNOWNBUG.TIMESTAMP_DRIFT` | Replaces each frame's timestamp with its ideal value: `frame_index / fps` |
| `StatsRecomputeFixer` | `STATISTICAL.STATS_MATCH_DATA` | Streams all numeric columns and rewrites `meta/stats.json` with correct values |

Fixers always run in the order shown above. `TimestampDedriftFixer` runs before `StatsRecomputeFixer` so the recomputed statistics reflect already-corrected timestamps.

### Basic usage

```bash
# Dry run — preview what would be changed, write nothing
miraxis fix /path/to/my-dataset

# Apply repairs, writing the repaired copy to a new path
miraxis fix /path/to/my-dataset --apply --out /path/to/repaired-dataset

# Machine-readable dry-run output
miraxis fix /path/to/my-dataset --json

# Machine-readable applied output
miraxis fix /path/to/my-dataset --apply --out /path/to/repaired-dataset --json
```

### Step by step: what happens when you run fix

**Step 1 — Load the dataset**

Same as lint: resolve the local path, validate metadata, detect version.

**Step 2 — Lint**

Run all checks, same as `miraxis lint`.

**Step 3 — Select applicable fixers**

A fixer is selected only if its targeted check fired at WARN or worse in the lint results. If the dataset is clean, no fixers run and the exit code is `0`.

**Step 4 — Dry run (always)**

Each selected fixer produces a `Diff` — a structured list of exactly which frames, stats entries, or episode boundaries would change, with old and new values. In dry-run mode this is printed or returned as JSON and no files are written.

**Step 5 — Apply (only with --apply)**

Each fixer copies the full dataset tree to a new location and rewrites only its specific files. After each fixer, the next one works from the new copy. The final output lands at your `--out` path.

### Exit codes

- `0` = nothing to fix, dataset already clean
- `1` = fixes proposed (dry-run) or applied successfully
- `2` = failed to load, usage error, or fixer refused

### Rules

- `--apply` requires `--out`. miraxis never writes to an implicit or guessed path.
- `--out` must not be the same path as the source. Copy-on-write means no in-place rewriting.
- Hub refs are always refused by `fix`.

---

## Feature 3: web

### What it does

`miraxis web` lints a dataset once, then serves a read-only visual dashboard of that report in your browser. It binds only to `127.0.0.1` (your machine only, not the network). The browser cannot choose or switch datasets — the dataset is fixed at launch time.

### Basic usage

```bash
# Open dashboard for a Hub dataset
miraxis web lerobot/pusht

# Open dashboard for a local dataset
miraxis web /path/to/my-dataset

# Use a custom port
miraxis web lerobot/pusht --port 9000

# Start server without auto-opening a browser tab
miraxis web lerobot/pusht --no-open
```

After running, open `http://127.0.0.1:8000` in your browser (or the port you specified). Stop the server with `Ctrl-C`.

### What happens step by step

1. miraxis resolves and lints the dataset (same steps as `miraxis lint`).
2. It builds the JSON report once in memory.
3. It starts a local FastAPI server.
4. The browser dashboard loads the report JSON from `/api/report` and renders it.
5. The server never accepts any user input from the browser. It only serves the one pre-computed report.

---

## Output formats

| Format | Flag | Use case |
|---|---|---|
| Terminal (default) | none | Human reading |
| JSON | `--json` | Scripts, pipelines, further processing |
| HTML | `--report out.html` | Sharing a visual report as a file |
| SARIF | `--sarif out.sarif` | CI tools, GitHub Actions annotations |
| Web dashboard | `miraxis web ...` | Interactive browser view |

---

## Accepted dataset types

miraxis only works with **LeRobotDataset** format versions **v2.0, v2.1, and v3.0**.

If your data is in another format such as MCAP, HDF5, ROS bags, or raw CSV, you need to convert it to LeRobotDataset first.

A valid LeRobotDataset must have:
- `meta/info.json` with `codebase_version`, `fps`, `features`
- episode metadata in either `meta/episodes/` (v3) or `meta/episodes.jsonl` (v2)
- data payload in Parquet shards under `data/`
- optionally video shards under `videos/`

---

## Hub datasets vs local datasets

| | Hub dataset (`org/name`) | Local dataset (`/path/to/...`) |
|---|---|---|
| `lint` | Supported; metadata cached locally | Supported |
| `fix` | Not supported | Supported |
| `web` | Supported | Supported |
| Deep checks | Require `--deep` | Run by default |
| Cache location | `~/.cache/miraxis/hub/` | Not cached |

---

## Real-world demo

Install and run a lint against a known public dataset:

```bash
cd /home/kwalker96/projects/data_quality_&_validation_tool
source .venv/bin/activate
cd miraxis-main

# Quick terminal report
miraxis lint lerobot/pusht

# JSON report
miraxis lint lerobot/pusht --json

# Visual browser dashboard
miraxis web lerobot/pusht
```

---

## Common errors

| Error message | Cause | Fix |
|---|---|---|
| `not a Python project, as neither pyproject.toml nor setup.py are present` | Running `uv pip install` from the wrong directory | `cd miraxis-main` first, then re-run |
| `bash: syntax error near unexpected token 'newline'` | Using angle bracket placeholders like `<org/dataset>` literally in the shell | Replace with real values, e.g. `lerobot/pusht` |
| `miraxis web requires the [web] extra` | Web dependencies not installed | `uv pip install -e ".[web]"` |
| `not a local path, and the optional Hub dependency is not installed` | `[hub]` extra missing | `uv pip install -e ".[hub]"` |
| `ERROR: Could not load dataset ...` | Dataset missing, wrong path, or not a LeRobotDataset | Check the path or Hub id |
| `--apply requires --out` | Used `--apply` without specifying an output path | Add `--out /some/output/path` |
| `--out must not be the same path as the source` | Source and output path are the same | Use a different output path |

---

## Quick reference

```bash
# Check version
miraxis --version

# Lint
miraxis lint lerobot/pusht
miraxis lint /path/to/dataset
miraxis lint lerobot/pusht --json
miraxis lint lerobot/pusht --report report.html
miraxis lint lerobot/pusht --sarif report.sarif
miraxis lint lerobot/pusht --deep

# Fix
miraxis fix /path/to/dataset
miraxis fix /path/to/dataset --apply --out /path/to/output
miraxis fix /path/to/dataset --json

# Web dashboard
miraxis web lerobot/pusht
miraxis web /path/to/dataset --port 9000
miraxis web lerobot/pusht --no-open
```
