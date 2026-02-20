---
name: pipeline-gantt
description: >
  Generate 16:9 slide-ready Gantt timeline charts from pipeline CSVs. Use this skill whenever
  the user uploads a CSV containing pipeline data (projects, deals, or use-cases with stages
  like Validating/Scoping/Evaluating/Confirming/Onboarding/Live, dates, and revenue or value
  figures) and wants a visual timeline, Gantt chart, or pipeline overview. Also trigger when
  the user mentions "pipeline chart", "timeline", "Gantt", or references updating a previously
  generated timeline with new data. Works for any account — auto-detects the account name,
  date, column names, and value metric from the CSV. Supports auto-pagination for large
  datasets (50+ rows), stage filtering, fiscal year end markers, and optional multi-page PDF.
---

# Pipeline Gantt Chart Generator

Generates polished, 16:9, transparent-background Gantt timeline PNGs from pipeline CSVs.
Designed for slide decks — drops cleanly onto any background colour.

## When to Use

- User uploads a CSV with pipeline data and wants a timeline visualisation
- User mentions "pipeline chart", "timeline", "Gantt chart"
- User asks to "update the timeline", "refresh the chart", or "generate a new Gantt"
- User references pipeline stages (Validating, Scoping, Evaluating, Confirming, Onboarding, Live)

## Quick Start

```bash
python /mnt/skills/user/pipeline-gantt/scripts/generate_gantt.py \
  INPUT.csv OUTPUT.png [OPTIONS]
```

The script auto-detects: account name and date from the filename, column names via fuzzy
matching, fiscal year, and the value/metric column. Override anything with flags.

## CSV Format

Needs at minimum: a **name** column, a **stage/status** column, a **start date** column,
and an **end date** column. Optionally a **Business Unit** column, a **value** column,
and monthly columns in `YYYY-MM` format for quarterly totals in the subtitle.

If monthly columns are absent, the subtitle shows just the date (no quarterly breakdown).

### Recognised Column Names

| Purpose | Candidates (case-insensitive) |
|---------|-------------------------------|
| Name | Name, Use Case, Project, Deal, Opportunity |
| Region / BU | Business Unit, BU, Region, Country, Territory, Segment |
| Stage | Plain Status, Status, Stage, Stage (plain), Pipeline Stage, Phase |
| Start date | Onboarding date, Start date, Start Date, Begin Date |
| End date | Target live date, Live date, Go-live date, End Date, Target Date |
| Value | Monthly Revenue, Revenue, ARR, MRR, Value, Amount |

Use `--col-*` flags to override any of these.

## Pagination

Large datasets auto-split across pages (~20 rows each by default).

- Groups (stage or BU) kept intact when possible; oversized groups split at the row limit
- Output: numbered PNGs (`output_1.png`, `output_2.png`…) or single file if ≤20 rows
- Add `--pdf` to also generate a single multi-page PDF
- Override with `--max-rows N` (or `--max-rows 0` to disable)
- Each page shares header, legend, x-axis, "Today" line, and "FY End" marker

## Stage Filtering

```bash
--exclude-stages Live Validating      # Hide already-live and early-stage
--include-stages Evaluating Confirming # Show only a subset
```

## CLI Reference

### Chart

| Flag | Default | Description |
|------|---------|-------------|
| `--account` | *auto* | Account name |
| `--title` | *auto* | Full chart title (overrides auto-generated) |
| `--today` | *auto* | "Today" date as YYYY-MM-DD |
| `--sort` | `stage` | `stage` or `bu` |
| `--dpi` | `150` | Output resolution |
| `--no-flags` | off | Hide flag emojis on Y axis |
| `--y-label` | hidden | Custom Y axis label |
| `--flags` | — | JSON `{"Region":"🏳️"}` to add/override flags |

### Stage filtering

| Flag | Default | Description |
|------|---------|-------------|
| `--include-stages` | all | Only show these stages |
| `--exclude-stages` | none | Hide these stages |

### Pagination

| Flag | Default | Description |
|------|---------|-------------|
| `--max-rows` | `20` | Rows per page (0 = disable) |
| `--pdf` | off | Also generate multi-page PDF |

### Fiscal year

| Flag | Default | Description |
|------|---------|-------------|
| `--fy` | *auto* | FY label e.g. FY27 |
| `--fy-start` | `1` | FY start month (1=Jan, 2=Feb, 4=Apr, 7=Jul, 10=Oct) |

### Metric / value

| Flag | Default | Description |
|------|---------|-------------|
| `--value-col` | *auto* | Column name for the numeric value |
| `--metric-label` | `Revenue` | Label in subtitle (Revenue, ARR, MRR, DBU…) |

### Column overrides

| Flag | Description |
|------|-------------|
| `--col-name` | Use-case name column |
| `--col-bu` | Business Unit column |
| `--col-status` | Pipeline stage column |
| `--col-onboard` | Start date column |
| `--col-live` | End date column |

## Typical Workflow

1. User uploads `Acme_Pipeline_v3_2026-03-15.csv`
2. Generate both sort variants:

```bash
python /mnt/skills/user/pipeline-gantt/scripts/generate_gantt.py \
  /mnt/user-data/uploads/Acme_Pipeline_v3_2026-03-15.csv \
  /mnt/user-data/outputs/Acme_by_Stage.png --sort stage

python /mnt/skills/user/pipeline-gantt/scripts/generate_gantt.py \
  /mnt/user-data/uploads/Acme_Pipeline_v3_2026-03-15.csv \
  /mnt/user-data/outputs/Acme_by_BU.png --sort bu
```

3. Present both PNGs to the user

## Visual Design

| Element | Detail |
|---------|--------|
| Background | Fully transparent — works on any slide colour |
| Font | TeX Gyre Heros (Helvetica clone, sans-serif fallback) |
| Non-live bars | Pastel body + saturated 14-day tip at target date |
| Live bars | Light grey → dark 14-day tip → medium grey to today |
| Validating | Lavender / purple — distinct from all other stages |
| Quarter shading | Alternating subtle grey bands based on `--fy-start` |
| "Today" | Red dashed line with label |
| "FY End" | Blue dashed line marking fiscal year boundary |
| Flags | 30+ built-in country emoji mappings, extensible via `--flags` |
| Names | Auto-truncated to fit bar boundaries |
| Legend | Only shows stages present in the data |
