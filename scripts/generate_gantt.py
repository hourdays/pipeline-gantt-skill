#!/usr/bin/env python3
"""
Pipeline Gantt-chart generator for Claude AI.

Produces 16:9 transparent-background timelines with:
  • Six pipeline stages: Validating → Scoping → Evaluating → Confirming → Onboarding → Live
  • Two-tone bars (pastel ramp + saturated 14-day tip at target date)
  • Live bars: light grey → dark tip at live date → medium grey to today
  • Configurable fiscal-quarter shading + FY-end marker
  • Flag emojis on Y axis (30+ built-in, extensible, optional)
  • Sort by pipeline stage or by Business Unit
  • Stage filtering (include / exclude)
  • Auto-pagination for large datasets with group-aware splitting
  • Multi-page PDF or numbered PNG output

Usage:
    python generate_gantt.py data.csv
    python generate_gantt.py data.csv out.png --account "Acme" --today 2026-03-15
    python generate_gantt.py data.csv --sort bu --fy-start 4
    python generate_gantt.py data.csv --exclude-stages Live Validating
    python generate_gantt.py data.csv --max-rows 15 --pdf --no-flags
"""

import argparse, json, os, re, warnings
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.backends.backend_pdf import PdfPages
from PIL import Image, ImageDraw, ImageFont

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

FONT = "TeX Gyre Heros"  # Helvetica clone; falls back to sans-serif

# Bar colours: (pastel body, saturated 14-day tip)
STATUS_COLORS = {
    "Validating": ("#E0D4F5", "#B89CE0"),
    "Scoping":    ("#D3EFF4", "#7DD4E4"),
    "Evaluating": ("#F3E6C4", "#F4D76F"),
    "Confirming": ("#CCE7BA", "#7ED956"),
    "Onboarding": ("#F4D6D6", "#F4A6A6"),
    "Live":       ("#CFCFCF", "#777777"),
}
LEGEND_CLR = {
    "Validating": "#C8B4E3",
    "Scoping": "#A5DDE8", "Evaluating": "#EDD98A", "Confirming": "#A3D88E",
    "Onboarding": "#F0B5B5", "Live": "#999999",
}
LIVE_TIP_CLR = "#333333"

# Sort order (top → bottom in stage view)
STAGE_ORDER = ["Live", "Onboarding", "Confirming", "Evaluating", "Scoping", "Validating"]
# Legend order (left → right)
LEGEND_ORDER = ["Validating", "Scoping", "Evaluating", "Confirming", "Onboarding", "Live"]

LIVE_SEG = 14
MAX_ROWS_DEFAULT = 20

# Column auto-detection candidates
_VALUE_CANDIDATES = [
    "Monthly Revenue", "Monthly ARR", "Monthly MRR", "Monthly DBU",
    "Revenue", "ARR", "MRR", "DBU", "Value", "Amount",
    "Monthly Value", "Monthly Amount",
]
_STATUS_CANDIDATES = [
    "Plain Status", "Status", "Stage", "Stage (plain)", "Pipeline Stage", "Phase",
]
_NAME_CANDIDATES = ["Name", "Use Case", "Use-case", "Project", "Deal", "Opportunity"]
_BU_CANDIDATES = ["Business Unit", "BU", "Region", "Country", "Territory", "Segment"]
_ONBOARD_CANDIDATES = [
    "Onboarding date", "Start date", "Start Date", "Onboard Date", "Begin Date",
]
_LIVE_CANDIDATES = [
    "Target live date", "Live date", "Go-live date", "Go-Live Date",
    "End Date", "Target Date", "Go Live Date",
]

_SCOTLAND = "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"

DEFAULT_FLAGS = {
    "Belgium": "🇧🇪", "United Kingdom": "🇬🇧", "France": "🇫🇷",
    "Middle East": "🇦🇪", "North America": "🇺🇸", "Netherlands": "🇳🇱",
    "Northern Europe": "🇪🇺", "Spain": "🇪🇸", "Corporate": "🏢",
    "Global": "🌐", "Scotland": _SCOTLAND, "Germany": "🇩🇪",
    "Italy": "🇮🇹", "Ireland": "🇮🇪", "Switzerland": "🇨🇭",
    "Sweden": "🇸🇪", "Norway": "🇳🇴", "Denmark": "🇩🇰",
    "Finland": "🇫🇮", "Poland": "🇵🇱", "Portugal": "🇵🇹",
    "Austria": "🇦🇹", "Czech Republic": "🇨🇿", "Greece": "🇬🇷",
    "Australia": "🇦🇺", "Japan": "🇯🇵", "China": "🇨🇳",
    "India": "🇮🇳", "Brazil": "🇧🇷", "Canada": "🇨🇦",
    "Mexico": "🇲🇽", "South Korea": "🇰🇷", "Singapore": "🇸🇬",
    "APAC": "🌏", "EMEA": "🌍", "LATAM": "🌎",
}

TXT    = "#333333"
SUBTXT = "#666666"
GRID   = "#E0E0E0"
RED    = "#D03030"
BLUE   = "#2E6EB5"
QTR_BG = "#000000"
EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _find_col(df, candidates, required=True, label="column"):
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for cand in candidates:
        if cand.lower().strip() in cols_lower:
            return cols_lower[cand.lower().strip()]
    if required:
        raise KeyError(
            f"Could not find {label} column. Tried: {candidates}. "
            f"Available: {list(df.columns)}. Use --col-* flags to specify."
        )
    return None


def _emoji(char, sz=109):
    try:
        fnt = ImageFont.truetype(EMOJI_FONT, sz)
    except Exception:
        return np.array(Image.new("RGBA", (sz, sz), (200, 200, 200, 180)))
    c = Image.new("RGBA", (sz * 3, sz * 3), (0, 0, 0, 0))
    ImageDraw.Draw(c).text((0, 0), char, font=fnt, embedded_color=True)
    bb = c.getbbox()
    if not bb:
        return np.array(Image.new("RGBA", (sz, sz), (200, 200, 200, 180)))
    cr = c.crop(bb)
    w, h = cr.size
    s = max(w, h)
    sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sq.paste(cr, ((s - w) // 2, (s - h) // 2))
    return np.array(sq)


def _parse_date(v):
    if pd.isna(v) or str(v).strip() == "":
        return None
    s = str(v).split("(")[0].strip()
    for f in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def _quarterly_sums(df, mcols, fy_start):
    months = [((fy_start - 1 + i * 3) % 12) + 1 for i in range(4)]
    q_totals = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    for col in mcols:
        col_m = int(col[5:7])
        qi = None
        for i in range(4):
            q_start = months[i]
            q_end = months[(i + 1) % 4] if i < 3 else months[0]
            if q_end <= q_start:
                if col_m >= q_start or col_m < q_end:
                    qi = i; break
            else:
                if q_start <= col_m < q_end:
                    qi = i; break
        if qi is None:
            qi = 3
        q_totals[f"Q{qi + 1}"] += int(df[col].sum())
    return {k: v for k, v in q_totals.items() if v > 0}


def _fiscal_quarter_spans(xmin, xmax, fy_start):
    months = [((fy_start - 1 + i * 3) % 12) + 1 for i in range(5)]
    spans = []
    for y in range(xmin.year - 1, xmax.year + 2):
        for qi in range(4):
            m, nm = months[qi], months[qi + 1]
            qy, ny = y, y + (1 if nm <= m else 0)
            try:
                qs, qe = datetime(qy, m, 1), datetime(ny, nm, 1)
            except ValueError:
                continue
            if qe > xmin and qs < xmax:
                spans.append((max(qs, xmin), min(qe, xmax), qi))
    return spans


def _fy_end_date(today, fy_start):
    if today.month < fy_start:
        fy_begin = datetime(today.year - 1, fy_start, 1)
    else:
        fy_begin = datetime(today.year, fy_start, 1)
    return datetime(fy_begin.year + 1, fy_start, 1)


def _truncate(name, max_chars, align="left"):
    if len(name) <= max_chars:
        return name
    if max_chars < 4:
        return ""
    if align == "right":
        return "…" + name[-(max_chars - 1):]
    return name[: max_chars - 1] + "…"


def _extract_account_and_date(csv_path):
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    date_match = re.search(r"(\d{4})-(\d{2})F?-(\d{2})", basename)
    dt = None
    if date_match:
        try:
            dt = datetime(int(date_match.group(1)), int(date_match.group(2)),
                          int(date_match.group(3)))
        except ValueError:
            pass
    name_match = re.match(r"^([^_]+)", basename)
    return (name_match.group(1) if name_match else None), dt


def _format_value(v):
    if v >= 1000:
        k = v / 1000
        return f"{k:.0f}K" if k == int(k) else f"{k:.1f}K"
    return str(v)


# ═══════════════════════════════════════════════════════════════════════
#  PAGINATION
# ═══════════════════════════════════════════════════════════════════════

def _split_into_pages(df, max_rows, group_key):
    if len(df) <= max_rows:
        return [df]
    groups = [grp for _, grp in df.groupby(group_key, sort=False)]
    pages, cur, cnt = [], [], 0
    for grp in groups:
        gs = len(grp)
        if cnt + gs <= max_rows:
            cur.append(grp); cnt += gs
        elif cnt == 0:
            for i in range(0, gs, max_rows):
                chunk = grp.iloc[i:i + max_rows]
                if i + max_rows < gs:
                    pages.append(chunk.reset_index(drop=True))
                else:
                    cur, cnt = [chunk], len(chunk)
        else:
            pages.append(pd.concat(cur).reset_index(drop=True))
            cur, cnt = [], 0
            if gs <= max_rows:
                cur, cnt = [grp], gs
            else:
                for i in range(0, gs, max_rows):
                    chunk = grp.iloc[i:i + max_rows]
                    if i + max_rows < gs:
                        pages.append(chunk.reset_index(drop=True))
                    else:
                        cur, cnt = [chunk], len(chunk)
    if cur:
        pages.append(pd.concat(cur).reset_index(drop=True))
    return pages


# ═══════════════════════════════════════════════════════════════════════
#  SINGLE-PAGE RENDERER
# ═══════════════════════════════════════════════════════════════════════

def _render_page(
    df_page, *,
    title, sub, page_num, total_pages,
    today, xmin, xmax, total_d, fm, fy_start, fy_label,
    c_name, c_bu, c_status, c_val,
    region_flags, emoji_cache, sort_by,
    all_stages, dpi, show_flags, y_label,
):
    N = len(df_page)
    BH = 0.56
    fig, ax = plt.subplots(figsize=(19.2, 10.8))
    fig.patch.set_alpha(0.0); ax.set_facecolor("none")
    ax.set_position([0.045, 0.055, 0.94, 0.785])
    ax_px = 19.2 * 0.94 * dpi
    px_day = ax_px / total_d
    ch_px = 9.5 * (dpi / 72) * 0.52

    # Quarter shading
    for qs, qe, qi in _fiscal_quarter_spans(xmin, xmax, fy_start):
        if qi % 2 == 0:
            ax.axvspan(qs, qe, facecolor=QTR_BG, alpha=0.035, zorder=0)

    # Bars
    for i, (_, r) in enumerate(df_page.iterrows()):
        st = r[c_status]
        cm, cb = STATUS_COLORS.get(st, ("#ccc", "#999"))
        ob, lv = r["_ob"] or today, r["_lv"] or today
        val = int(float(r.get(c_val, 0) or 0)) if c_val else 0
        bs = max(ob, fm)
        name = str(r[c_name])

        if st == "Live":
            tip_start = max(lv - timedelta(days=LIVE_SEG), bs)
            # Light grey: start → tip
            seg1_d = max((tip_start - bs).days, 0)
            if seg1_d > 0:
                ax.barh(i, seg1_d, left=bs, height=BH, color=cm,
                        ec="none", alpha=0.95, zorder=3)
            # Dark tip: 14 days ending at live date
            tip_end = min(lv, max(today, lv))
            tip_d = max((tip_end - tip_start).days, 0)
            if tip_d > 0:
                ax.barh(i, tip_d, left=tip_start, height=BH, color=LIVE_TIP_CLR,
                        ec="none", alpha=0.95, zorder=3)
            # Medium grey: live date → today
            if today > lv:
                ax.barh(i, (today - lv).days, left=lv, height=BH, color=cb,
                        ec="none", alpha=0.95, zorder=3)
            be = max(today, lv)
            bar_d = (be - bs).days
            max_c = int((bar_d * px_day - 20) / ch_px)
            tname = _truncate(name, max_c, "right")
            if tname:
                ax.text(be - timedelta(days=2), i, tname, va="center", ha="right",
                        fontsize=9.5, fontweight="medium", color="#EEEEEE",
                        zorder=5, fontfamily=FONT)
            if val > 0:
                ax.text(be + timedelta(days=4), i, f"{val:,}", va="center",
                        ha="left", fontsize=10, fontweight="bold", color="#888",
                        zorder=5, fontfamily=FONT)
        else:
            re_ = lv - timedelta(days=LIVE_SEG)
            rd = max((re_ - bs).days, 0)
            if rd > 0:
                ax.barh(i, rd, left=bs, height=BH, color=cm,
                        ec="none", alpha=0.90, zorder=3)
            ss = max(re_, bs)
            sd = max((lv - ss).days, 7)
            ax.barh(i, sd, left=ss, height=BH, color=cb,
                    ec="none", alpha=0.95, zorder=3)
            be = lv
            bar_d = (be - bs).days
            frac = bar_d / total_d
            if frac > 0.10:
                max_c = int((bar_d * px_day - 20) / ch_px)
                tname = _truncate(name, max_c, "left")
                if tname:
                    ax.text(bs + timedelta(days=4), i, tname, va="center",
                            ha="left", fontsize=9.5, fontweight="medium",
                            color=TXT, zorder=5, fontfamily=FONT)
            else:
                gap = 42 if val > 0 else 6
                ax.text(be + timedelta(days=gap), i, name, va="center",
                        ha="left", fontsize=9.5, fontweight="medium",
                        color=TXT, zorder=5, fontfamily=FONT)
            if val > 0:
                ax.text(be + timedelta(days=4), i, f"{val:,}", va="center",
                        ha="left", fontsize=10, fontweight="bold", color=SUBTXT,
                        zorder=5, fontfamily=FONT)

    # Y-axis flags
    ax.set_yticks(range(N)); ax.set_yticklabels([""] * N)
    if show_flags and emoji_cache:
        for i, (_, r) in enumerate(df_page.iterrows()):
            fl = region_flags.get(str(r[c_bu]), "❓")
            arr = emoji_cache.get(fl)
            if arr is not None:
                ib = OffsetImage(arr, zoom=0.14); ib.image.axes = ax
                ab = AnnotationBbox(ib, (0, i), xybox=(-24, 0),
                    xycoords=("axes fraction", "data"),
                    boxcoords="offset points", frameon=False,
                    box_alignment=(0.5, 0.5), clip_on=False)
                ax.add_artist(ab)
    if y_label:
        ax.set_ylabel(y_label, fontsize=9, color="#999",
                      labelpad=32, fontfamily=FONT)

    # Today line
    ax.axvline(today, color=RED, ls="--", lw=1.3, zorder=4, alpha=0.7)
    ax.annotate("Today", xy=(today, 1), xycoords=("data", "axes fraction"),
                xytext=(0, 6), textcoords="offset points", ha="center",
                va="bottom", fontsize=9.5, fontweight="bold", color=RED,
                fontfamily=FONT, annotation_clip=False)

    # FY end line
    fy_end = _fy_end_date(today, fy_start)
    if xmin < fy_end < xmax:
        ax.axvline(fy_end, color=BLUE, ls="--", lw=1.3, zorder=4, alpha=0.6)
        ax.annotate(f"{fy_label} End", xy=(fy_end, 1),
                    xycoords=("data", "axes fraction"), xytext=(0, 6),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=9.5, fontweight="bold", color=BLUE,
                    fontfamily=FONT, annotation_clip=False)

    # Group separators
    gk = c_bu if sort_by == "bu" else c_status
    prev = None
    for i, (_, r) in enumerate(df_page.iterrows()):
        cur = r[gk]
        if prev and cur != prev:
            ax.axhline(i - 0.5, color="#DDDDDD", lw=0.7, zorder=2)
        prev = cur

    # Axes
    ax.set_xlim(xmin, xmax); ax.set_ylim(N - 0.5, -1.0)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.tick_params(axis="x", colors=SUBTXT, labelsize=10, pad=5)
    ax.tick_params(axis="y", left=False, pad=20)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.grid(axis="x", color=GRID, lw=0.4, zorder=1)

    # Header
    fig.text(0.50, 0.960, title, ha="center", va="center", fontsize=18,
             fontweight="bold", color=TXT, fontfamily=FONT)
    ps = sub + (f"  —  Page {page_num} of {total_pages}" if total_pages > 1 else "")
    fig.text(0.50, 0.933, ps, ha="center", va="center", fontsize=10.5,
             color=SUBTXT, fontfamily=FONT)

    # Legend
    leg = [s for s in LEGEND_ORDER if s in all_stages]
    hs = [mpatches.Patch(fc=LEGEND_CLR.get(s, "#ccc"), ec="none", label=s) for s in leg]
    fig.legend(handles=hs, loc="upper center", bbox_to_anchor=(0.50, 0.915),
               ncol=len(leg), frameon=False, fontsize=9.5, labelcolor=TXT,
               handlelength=1.2, handletextpad=0.4, columnspacing=2.0,
               prop={"family": FONT})
    return fig


# ═══════════════════════════════════════════════════════════════════════
#  MAIN GENERATOR
# ═══════════════════════════════════════════════════════════════════════

def generate_gantt(
    csv_path, output_path="gantt_output.png", *,
    title=None, account=None, today=None, region_flags=None,
    dpi=150, sort_by="stage", fy_label=None, fy_start=1,
    value_col=None, metric_label="Revenue",
    col_name=None, col_bu=None, col_status=None,
    col_onboard=None, col_live=None,
    max_rows=MAX_ROWS_DEFAULT, pdf=False,
    include_stages=None, exclude_stages=None,
    show_flags=True, y_label=None,
):
    """Generate Gantt timeline chart(s) from a pipeline CSV.

    Returns a list of output file paths.
    """
    auto_account, auto_date = _extract_account_and_date(csv_path)
    if account is None: account = auto_account or "Account"
    if today is None:   today = auto_date or datetime.now()
    if region_flags is None: region_flags = DEFAULT_FLAGS.copy()

    # Font
    try:
        matplotlib.rcParams["font.family"] = FONT
        ft = plt.figure(figsize=(1, 1)); ft.text(0.5, 0.5, "x", fontfamily=FONT)
        plt.close(ft)
    except Exception:
        matplotlib.rcParams["font.family"] = "sans-serif"

    # Load
    df = pd.read_csv(csv_path)
    c_name   = col_name   or _find_col(df, _NAME_CANDIDATES, label="name")
    c_bu     = col_bu     or _find_col(df, _BU_CANDIDATES, label="business unit")
    c_status = col_status or _find_col(df, _STATUS_CANDIDATES, label="status")
    c_onboard= col_onboard or _find_col(df, _ONBOARD_CANDIDATES, label="onboarding date")
    c_live   = col_live   or _find_col(df, _LIVE_CANDIDATES, label="target live date")
    c_val    = value_col or _find_col(df, _VALUE_CANDIDATES, required=False, label="value")

    mcols = sorted(c for c in df.columns if len(c) == 7 and c[4] == "-" and c[:4].isdigit())
    for c in mcols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["_ob"] = df[c_onboard].apply(_parse_date)
    df["_lv"] = df[c_live].apply(_parse_date)
    fm = datetime.strptime(mcols[0], "%Y-%m") if mcols else today

    # Stage filtering
    if include_stages:
        df = df[df[c_status].isin(include_stages)].reset_index(drop=True)
    if exclude_stages:
        df = df[~df[c_status].isin(exclude_stages)].reset_index(drop=True)
    if len(df) == 0:
        print("⚠️  No rows remain after stage filtering."); return []

    # FY label
    if fy_label is None:
        cal_year = int(mcols[0][:4]) if mcols else today.year
        fy_label = f"FY{(cal_year + 1) % 100:02d}"

    # Sort
    so = {s: i for i, s in enumerate(STAGE_ORDER)}
    df["_so"] = df[c_status].map(so).fillna(99)
    if sort_by == "bu":
        df = df.sort_values([c_bu, "_lv"], ascending=[True, True]).reset_index(drop=True)
    else:
        df = df.sort_values(["_so", "_ob", "_lv"], ascending=[True, False, True]).reset_index(drop=True)

    # Subtitle
    ts = today.strftime("%b. %d, %Y")
    if mcols:
        qf = _quarterly_sums(df, mcols, fy_start)
        qp = " • ".join(f"{q} ({_format_value(v)})" for q, v in qf.items())
        sub = f"{ts} {metric_label} Pipeline: {qp}"
    else:
        sub = ts

    # Title
    if title is None:
        title = f"{account} Use-cases {fy_label} Timeline"

    # Global geometry
    all_lv = [d for d in df["_lv"] if d]
    xmin = fm - timedelta(days=15)
    xmax = max(all_lv + [today]) + timedelta(days=50)
    total_d = (xmax - xmin).days
    all_stages = set(df[c_status].unique())

    # Emoji cache
    emoji_cache = {}
    if show_flags:
        for bu in df[c_bu].unique():
            fl = region_flags.get(str(bu), "❓")
            if fl not in emoji_cache:
                emoji_cache[fl] = _emoji(fl)

    # Paginate
    gk = c_bu if sort_by == "bu" else c_status
    pages = _split_into_pages(df, max_rows, gk)
    tp = len(pages)

    # Render
    output_files, figs = [], []
    stem, ext = os.path.splitext(output_path)
    if not ext: ext = ".png"

    for pi, pg in enumerate(pages, 1):
        fig = _render_page(pg, title=title, sub=sub, page_num=pi, total_pages=tp,
            today=today, xmin=xmin, xmax=xmax, total_d=total_d, fm=fm,
            fy_start=fy_start, fy_label=fy_label,
            c_name=c_name, c_bu=c_bu, c_status=c_status, c_val=c_val,
            region_flags=region_flags, emoji_cache=emoji_cache,
            sort_by=sort_by, all_stages=all_stages, dpi=dpi,
            show_flags=show_flags, y_label=y_label)
        figs.append(fig)
        p = stem + ext if tp == 1 else f"{stem}_{pi}{ext}"
        fig.savefig(p, dpi=dpi, transparent=True, pad_inches=0)
        output_files.append(p)
        print(f"✅  {p}  ({os.path.getsize(p) / 1024:.0f} KB)")

    if pdf:
        pp = stem + ".pdf"
        with PdfPages(pp) as doc:
            for fig in figs:
                doc.savefig(fig, dpi=dpi, transparent=True, pad_inches=0)
        output_files.append(pp)
        print(f"✅  {pp}  ({os.path.getsize(pp) / 1024:.0f} KB, {tp} pages)")

    for fig in figs:
        plt.close(fig)
    return output_files


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Generate 16:9 pipeline Gantt timeline(s) from a CSV.")
    ap.add_argument("csv", help="Input CSV file path")
    ap.add_argument("output", nargs="?", default="gantt_output.png",
                    help="Output path. Multi-page → output_1.png, output_2.png…")

    g = ap.add_argument_group("chart")
    g.add_argument("--account",  default=None, help="Account name (auto-detected)")
    g.add_argument("--title",    default=None, help="Full chart title")
    g.add_argument("--today",    default=None, help="Reference date YYYY-MM-DD")
    g.add_argument("--sort",     default="stage", choices=["stage", "bu"])
    g.add_argument("--dpi",      type=int, default=150)
    g.add_argument("--flags",    default=None, help='JSON {"Region":"emoji"}')
    g.add_argument("--no-flags", action="store_true", help="Hide flag emojis")
    g.add_argument("--y-label",  default=None, help="Y axis label (hidden by default)")

    s = ap.add_argument_group("stages")
    s.add_argument("--include-stages", nargs="+", default=None)
    s.add_argument("--exclude-stages", nargs="+", default=None)

    p = ap.add_argument_group("pagination")
    p.add_argument("--max-rows", type=int, default=MAX_ROWS_DEFAULT,
                   help=f"Rows per page (default {MAX_ROWS_DEFAULT}, 0=disable)")
    p.add_argument("--pdf", action="store_true", help="Also produce multi-page PDF")

    f = ap.add_argument_group("fiscal year")
    f.add_argument("--fy",       default=None, help="FY label e.g. FY27")
    f.add_argument("--fy-start", type=int, default=1, help="FY start month (1=Jan)")

    m = ap.add_argument_group("metric")
    m.add_argument("--value-col",    default=None, help="Value column name")
    m.add_argument("--metric-label", default="Revenue", help="Subtitle metric label")

    c = ap.add_argument_group("column overrides")
    c.add_argument("--col-name",    default=None)
    c.add_argument("--col-bu",      default=None)
    c.add_argument("--col-status",  default=None)
    c.add_argument("--col-onboard", default=None)
    c.add_argument("--col-live",    default=None)

    a = ap.parse_args()
    td = datetime.strptime(a.today, "%Y-%m-%d") if a.today else None
    fl = None
    if a.flags:
        fl = DEFAULT_FLAGS.copy(); fl.update(json.loads(a.flags))

    generate_gantt(
        a.csv, a.output,
        title=a.title, account=a.account, today=td,
        region_flags=fl, dpi=a.dpi, sort_by=a.sort,
        fy_label=a.fy, fy_start=a.fy_start,
        value_col=a.value_col, metric_label=a.metric_label,
        col_name=a.col_name, col_bu=a.col_bu, col_status=a.col_status,
        col_onboard=a.col_onboard, col_live=a.col_live,
        max_rows=a.max_rows if a.max_rows > 0 else 99999,
        pdf=a.pdf,
        include_stages=a.include_stages, exclude_stages=a.exclude_stages,
        show_flags=not a.no_flags, y_label=a.y_label,
    )

if __name__ == "__main__":
    main()
