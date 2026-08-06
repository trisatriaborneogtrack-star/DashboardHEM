"""
Healthy Employee Movement Program — Ops Monitoring Dashboard
============================================================
Dashboard harian untuk monitoring program olahraga karyawan (Walking / Running)
berbasis submission Google Form + Strava screenshot.

Jalankan:
    streamlit run app.py

Sumber data:
    1. Upload file .xlsx hasil export Google Form (default)
    2. Google Sheet CSV URL (sheet harus di-share "Anyone with the link")
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:  # opsional — hanya dibutuhkan untuk mode service account
    import gspread

    HAS_GSPREAD = True
except ImportError:  # pragma: no cover
    HAS_GSPREAD = False

# Epoch serial Google Sheets / Excel
SHEETS_EPOCH = pd.Timestamp("1899-12-30")

# ---------------------------------------------------------------------------
# Konstanta & tema
# ---------------------------------------------------------------------------

APP_TITLE = "Healthy Employee Movement Program"
APP_SUB = "Monitoring Harian Aktivitas Olahraga Karyawan"

WITA = timezone(timedelta(hours=8))

INK = "#0F172A"
ACCENT = "#2563EB"
SUCCESS = "#16A34A"
WARN = "#F59E0B"
DANGER = "#DC2626"
MUTED = "#64748B"
GRID = "#E2E8F0"

STATUS_ORDER = ["Tercapai", "On Track", "Tertinggal", "Belum Mulai"]
STATUS_COLOR = {
    "Tercapai": SUCCESS,
    "On Track": ACCENT,
    "Tertinggal": WARN,
    "Belum Mulai": DANGER,
}

BULAN_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
}
BULAN_NAMA = {v: k.capitalize() for k, v in BULAN_ID.items()}

DEFAULT_SHEET_ID = "1I30t7uLOzwBMVyq0k-Rfy1NTzGUFLbT9v37XeFjKbF0"
DEFAULT_GID_RESP = "1186413594"

COL_TS = "Timestamp"
COL_NAMA = "Nama Karyawan"
COL_KAT = "Kategori"
COL_TGL = "Tanggal Aktifitas"
COL_KM = "Jarak Tempuh Aktivitas (Km)"
COL_BULAN = "Bulan Target"
COL_BUKTI = "Screenshot Aktivitas Strava"

CSS = """
<style>
  .block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }
  #MainMenu, footer { visibility: hidden; }

  .hero { border-bottom: 1px solid #E2E8F0; padding-bottom: 1.1rem; margin-bottom: 1.6rem; }
  .hero h1 { font-size: 1.85rem; font-weight: 700; color: #0F172A; margin: 0 0 .25rem 0;
             letter-spacing: -.02em; line-height: 1.15; }
  .hero p { color: #64748B; font-size: .95rem; margin: 0; }
  .hero .pill { display:inline-block; background:#EFF6FF; color:#2563EB; font-size:.72rem;
                font-weight:600; padding:.2rem .55rem; border-radius:999px; margin-left:.5rem;
                vertical-align: middle; letter-spacing:.02em; }

  .kpi { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:12px; padding:1rem 1.1rem;
         height:100%; transition: border-color .15s ease; }
  .kpi:hover { border-color:#CBD5E1; }
  .kpi .lbl { font-size:.72rem; font-weight:600; color:#64748B; text-transform:uppercase;
              letter-spacing:.06em; margin-bottom:.4rem; }
  .kpi .val { font-size:1.85rem; font-weight:700; color:#0F172A; line-height:1.05;
              letter-spacing:-.02em; }
  .kpi .val small { font-size:.9rem; font-weight:600; color:#94A3B8; margin-left:.2rem; }
  .kpi .sub { font-size:.78rem; color:#64748B; margin-top:.35rem; }
  .kpi .bar { height:5px; background:#F1F5F9; border-radius:99px; margin-top:.65rem; overflow:hidden; }
  .kpi .bar > div { height:100%; border-radius:99px; }

  .sec { font-size:1.02rem; font-weight:700; color:#0F172A; margin:.4rem 0 .1rem 0;
         letter-spacing:-.01em; }
  .sec-sub { font-size:.82rem; color:#64748B; margin-bottom:.7rem; }

  .note { background:#F8FAFC; border-left:3px solid #2563EB; border-radius:0 8px 8px 0;
          padding:.7rem .9rem; font-size:.84rem; color:#334155; margin:.4rem 0 1rem 0; }
  .note.warn { border-left-color:#F59E0B; background:#FFFBEB; }
  .note.ok   { border-left-color:#16A34A; background:#F0FDF4; }

  div[data-testid="stMetricValue"] { font-size:1.5rem; }
  section[data-testid="stSidebar"] { border-right:1px solid #E2E8F0; }
  section[data-testid="stSidebar"] .block-container { padding-top:1.5rem; }
  .stTabs [data-baseweb="tab-list"] { gap:.3rem; border-bottom:1px solid #E2E8F0; }
  .stTabs [data-baseweb="tab"] { font-weight:600; font-size:.88rem; padding:.5rem .9rem; }
</style>
"""

# ---------------------------------------------------------------------------
# Parsing helpers (pure — bisa diuji tanpa Streamlit)
# ---------------------------------------------------------------------------

# Format nama: "NAMA LENGKAP - (TPB.14112022-322) - JABATAN"
RE_EMP = re.compile(
    r"^\s*(?P<nama>.+?)\s*-\s*\(\s*(?P<entitas>[A-Za-z]+)\.(?P<join>\d{6,8})-(?P<nik>\d+)\s*\)\s*-\s*(?P<jabatan>.+?)\s*$"
)
RE_TARGET = re.compile(r"target\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*km", re.I)


def _clean(text) -> str:
    """Normalisasi whitespace + unicode agar join antar-sheet konsisten."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_employee(raw) -> dict:
    """Pecah string peserta jadi nama / entitas / NIK / tanggal gabung / jabatan."""
    s = _clean(raw)
    out = {
        "Peserta": s, "Nama": s, "Entitas": "Lainnya",
        "NIK": "", "Tanggal Gabung": pd.NaT, "Jabatan": "-",
    }
    m = RE_EMP.match(s)
    if not m:
        return out

    out["Nama"] = m.group("nama").title()
    out["Entitas"] = m.group("entitas").upper()
    out["NIK"] = m.group("nik")
    out["Jabatan"] = m.group("jabatan").title()

    j = m.group("join")
    if len(j) == 8:  # DDMMYYYY
        out["Tanggal Gabung"] = pd.to_datetime(j, format="%d%m%Y", errors="coerce")
    return out


def map_divisi(jabatan: str) -> str:
    """Kelompokkan jabatan jadi divisi ringkas untuk breakdown."""
    j = _clean(jabatan).upper()
    if not j or j == "-":
        return "Lainnya"
    if "MANAGER" in j or "COORDINATOR" in j or "KOORDINATOR" in j:
        return "Manajemen & Koordinator"
    if "TEKNISI GTRACK" in j:
        return "Teknisi GTrack"
    if "TEKNISI CCTV" in j:
        return "Teknisi CCTV"
    if "TEKNISI AC" in j:
        return "Teknisi AC"
    if "TECHNICAL SUPPORT" in j or "ENGINEER" in j or "CUSTOMER SUPPORT" in j:
        return "Technical Support"
    if "SALES" in j or "MARKETING" in j or "BUSINESS" in j:
        return "Sales & BD"
    if "ADMIN" in j or "ACCOUNTING" in j or "FINANCE" in j or "PURCHASING" in j:
        return "Admin & Finance"
    return "Support & Umum"


def parse_kategori(raw) -> tuple[str, float]:
    """'Running ( Berlari ), Target 15 Km/bulan' -> ('Running', 15.0)."""
    s = _clean(raw)
    if not s:
        return "-", np.nan

    jenis = re.split(r"[(,]", s)[0].strip().title() or "-"

    target = np.nan
    m = RE_TARGET.search(s)
    if m:
        target = float(m.group(1).replace(",", "."))
    return jenis, target


def parse_bulan(raw) -> pd.Timestamp:
    """'Agustus 2026' -> Timestamp('2026-08-01'). Toleran terhadap format lain."""
    s = _clean(raw).lower()
    if not s:
        return pd.NaT

    m = re.search(r"([a-z]+)\s*(\d{4})", s)
    if m and m.group(1) in BULAN_ID:
        return pd.Timestamp(year=int(m.group(2)), month=BULAN_ID[m.group(1)], day=1)

    ts = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return pd.Timestamp(year=ts.year, month=ts.month, day=1) if pd.notna(ts) else pd.NaT


def coerce_datetime(s: pd.Series, dayfirst: bool = True) -> pd.Series:
    """Ubah kolom tanggal jadi datetime, apa pun bentuk aslinya.

    Menangani tiga kasus yang muncul tergantung sumber data:
      - sudah datetime (hasil baca .xlsx)
      - angka serial Google Sheets/Excel (mode service account, UNFORMATTED_VALUE)
      - string berformat locale (mode CSV export) — diasumsikan dd/mm/yyyy
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return s

    non_null = s.notna() & (s.astype("string").str.strip() != "")
    n = int(non_null.sum())
    if n == 0:
        return pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")

    num = pd.to_numeric(s, errors="coerce")
    # Kalau mayoritas nilai berupa angka, perlakukan sebagai serial date
    if int((num.notna() & non_null).sum()) >= n * 0.8:
        return SHEETS_EPOCH + pd.to_timedelta(num.astype("float64"), unit="D")

    # ISO (yyyy-mm-dd) harus dicoba lebih dulu — dayfirst=True akan salah membacanya
    try:
        iso = pd.to_datetime(s, errors="coerce", format="ISO8601")
        if int((iso.notna() & non_null).sum()) >= n * 0.8:
            return iso
    except (ValueError, TypeError):
        pass

    return pd.to_datetime(s, errors="coerce", dayfirst=dayfirst)


def label_bulan(ts) -> str:
    if pd.isna(ts):
        return "Tidak diketahui"
    ts = pd.Timestamp(ts)
    return f"{BULAN_NAMA.get(ts.month, ts.month)} {ts.year}"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _pick_sheets(sheets: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Deteksi otomatis sheet responses (punya Timestamp) vs sheet roster."""
    resp, roster = None, None
    for _, df in sheets.items():
        cols = {_clean(c) for c in df.columns}
        if COL_NAMA not in cols:
            continue
        if COL_TS in cols and COL_KM in cols and resp is None:
            resp = df
        elif roster is None:
            roster = df
    if resp is None:
        # fallback: sheet pertama yang punya kolom nama
        for _, df in sheets.items():
            if COL_NAMA in {_clean(c) for c in df.columns}:
                resp = df
                break
    if resp is None:
        raise ValueError(
            f"Tidak menemukan sheet dengan kolom '{COL_NAMA}'. "
            f"Sheet terbaca: {list(sheets)}"
        )
    return resp, roster


def _normalize(resp_raw: pd.DataFrame, roster_raw: pd.DataFrame | None):
    """Bersihkan + perkaya kolom. Return (responses, roster_series)."""
    df = resp_raw.copy()
    df.columns = [_clean(c) for c in df.columns]

    required = [COL_NAMA, COL_KM]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Kolom wajib tidak ada: {missing}. Kolom terbaca: {list(df.columns)}")

    for c in (COL_TS, COL_TGL):
        if c in df.columns:
            df[c] = coerce_datetime(df[c])
        else:
            df[c] = pd.NaT

    if COL_KAT not in df.columns:
        df[COL_KAT] = ""
    if COL_BUKTI not in df.columns:
        df[COL_BUKTI] = ""

    df[COL_KM] = pd.to_numeric(df[COL_KM], errors="coerce")
    df[COL_NAMA] = df[COL_NAMA].map(_clean)
    df = df[df[COL_NAMA] != ""].copy()
    df = df.dropna(subset=[COL_KM])

    emp = pd.DataFrame([parse_employee(v) for v in df[COL_NAMA]], index=df.index)
    df = pd.concat([df.drop(columns=["Peserta"], errors="ignore"), emp], axis=1)
    df["Divisi"] = df["Jabatan"].map(map_divisi)

    kat = df[COL_KAT].map(parse_kategori)
    df["Jenis"] = [k[0] for k in kat]
    df["Target KM"] = [k[1] for k in kat]

    # Bulan periode: pakai kolom Bulan Target; kalau kosong, turunkan dari tanggal aktivitas
    if COL_BULAN in df.columns:
        df["Periode"] = df[COL_BULAN].map(parse_bulan)
    else:
        df["Periode"] = pd.NaT
    fallback = df[COL_TGL].dt.to_period("M").dt.to_timestamp()
    df["Periode"] = df["Periode"].fillna(fallback)
    df["Periode Label"] = df["Periode"].map(label_bulan)

    df["Tanggal"] = df[COL_TGL].dt.normalize()
    df["Tanggal"] = df["Tanggal"].fillna(df[COL_TS].dt.normalize())

    # Roster: gabungan daftar master + semua peserta yang pernah submit
    names = set(df["Peserta"])
    if roster_raw is not None:
        r = roster_raw.copy()
        r.columns = [_clean(c) for c in r.columns]
        if COL_NAMA in r.columns:
            names |= {n for n in r[COL_NAMA].map(_clean) if n}

    roster = pd.DataFrame([parse_employee(n) for n in sorted(names)])
    roster["Divisi"] = roster["Jabatan"].map(map_divisi)
    return df.reset_index(drop=True), roster


@st.cache_data(show_spinner=False)
def load_excel(content: bytes):
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine="openpyxl")
    resp, roster = _pick_sheets(sheets)
    return _normalize(resp, roster)


@st.cache_data(ttl=300, show_spinner=False)
def load_gsheet_csv(sheet_id: str, gid_resp: str, gid_roster: str | None):
    """Baca lewat endpoint CSV export. Sheet harus di-share 'Anyone with the link'."""
    base = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    resp = pd.read_csv(base.format(sid=sheet_id, gid=gid_resp))
    roster = None
    if gid_roster:
        try:
            roster = pd.read_csv(base.format(sid=sheet_id, gid=gid_roster))
        except Exception:
            roster = None
    return _normalize(resp, roster)


def _ws_to_df(ws) -> pd.DataFrame:
    """Worksheet -> DataFrame dengan tanggal tetap sebagai serial number.

    UNFORMATTED_VALUE dipakai supaya tanggal tidak terpengaruh locale sheet
    (dd/mm vs mm/dd) — konversi serial ditangani oleh coerce_datetime().
    """
    values = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not values:
        return pd.DataFrame()

    header = [_clean(h) for h in values[0]]
    rows = values[1:]
    width = len(header)
    rows = [(r + [None] * width)[:width] for r in rows]
    df = pd.DataFrame(rows, columns=header)
    return df.loc[:, [c for c in df.columns if c]]


@st.cache_data(ttl=300, show_spinner=False)
def load_gsheet_sa(sheet_id: str, ws_resp: str, ws_roster: str | None, _creds: dict):
    """Baca lewat service account. Sheet tetap private, cukup di-share ke email SA."""
    if not HAS_GSPREAD:
        raise RuntimeError(
            "Paket 'gspread' belum terpasang. Tambahkan gspread dan google-auth "
            "ke requirements.txt."
        )
    gc = gspread.service_account_from_dict(dict(_creds))
    sh = gc.open_by_key(sheet_id)

    resp = _ws_to_df(sh.worksheet(ws_resp))
    roster = None
    if ws_roster:
        try:
            roster = _ws_to_df(sh.worksheet(ws_roster))
        except Exception:
            roster = None
    return _normalize(resp, roster)


# ---------------------------------------------------------------------------
# Perhitungan
# ---------------------------------------------------------------------------

def periode_progress(periode: pd.Timestamp, today: pd.Timestamp | None = None):
    """Hitung hari berjalan / total hari dalam periode bulan."""
    if today is None:
        today = pd.Timestamp(datetime.now(WITA).date())
    start = pd.Timestamp(periode).normalize().replace(day=1)
    end = (start + pd.offsets.MonthEnd(1)).normalize()
    total = int((end - start).days) + 1
    if today < start:
        berjalan = 0
    elif today > end:
        berjalan = total
    else:
        berjalan = int((today - start).days) + 1
    return berjalan, total, start, end


def build_rekap(resp: pd.DataFrame, roster: pd.DataFrame,
                ratio: float, target_default: float) -> pd.DataFrame:
    """Rekap per peserta: aktual vs target, status, konsistensi."""
    agg = (
        resp.groupby("Peserta")
        .agg(**{
            "Aktual KM": (COL_KM, "sum"),
            "Total Aktivitas": (COL_KM, "size"),
            "Rata2 KM/Aktivitas": (COL_KM, "mean"),
            "Aktivitas Terjauh": (COL_KM, "max"),
            "Hari Aktif": ("Tanggal", "nunique"),
            "Aktivitas Terakhir": ("Tanggal", "max"),
            "Target KM": ("Target KM", "max"),
            "Jenis": ("Jenis", "last"),
        })
        .reset_index()
    )

    base = roster[["Peserta", "Nama", "Entitas", "NIK", "Jabatan", "Divisi", "Tanggal Gabung"]]
    rekap = base.merge(agg, on="Peserta", how="left")

    for c in ["Aktual KM", "Total Aktivitas", "Hari Aktif"]:
        rekap[c] = rekap[c].fillna(0)
    for c in ["Rata2 KM/Aktivitas", "Aktivitas Terjauh"]:
        rekap[c] = rekap[c].fillna(0.0)
    rekap["Jenis"] = rekap["Jenis"].fillna("Belum ada data")
    rekap["Target KM"] = rekap["Target KM"].fillna(target_default)

    rekap["Pencapaian %"] = np.where(
        rekap["Target KM"] > 0, rekap["Aktual KM"] / rekap["Target KM"] * 100, 0.0
    )
    rekap["Sisa KM"] = (rekap["Target KM"] - rekap["Aktual KM"]).clip(lower=0)
    rekap["Target Pace KM"] = rekap["Target KM"] * ratio

    rekap["Status"] = np.select(
        [
            rekap["Aktual KM"] <= 0,
            rekap["Aktual KM"] >= rekap["Target KM"],
            rekap["Aktual KM"] >= rekap["Target Pace KM"],
        ],
        ["Belum Mulai", "Tercapai", "On Track"],
        default="Tertinggal",
    )
    rekap["Status"] = pd.Categorical(rekap["Status"], categories=STATUS_ORDER, ordered=True)
    return rekap.sort_values(["Aktual KM", "Nama"], ascending=[False, True]).reset_index(drop=True)


def find_anomali(resp: pd.DataFrame, periode: pd.Timestamp) -> pd.DataFrame:
    """Flag entri yang perlu diverifikasi HR sebelum rekap dikunci."""
    start, end = periode_progress(periode)[2:]
    rows = []

    dup = resp.groupby(["Peserta", "Tanggal"]).size().reset_index(name="n")
    for _, r in dup[dup["n"] > 1].iterrows():
        rows.append({
            "Peserta": r["Peserta"],
            "Tanggal": r["Tanggal"],
            "Isu": f"{int(r['n'])}x submit di tanggal yang sama",
            "Tingkat": "Perlu cek",
        })

    for _, r in resp[(resp["Tanggal"] < start) | (resp["Tanggal"] > end)].iterrows():
        rows.append({
            "Peserta": r["Peserta"],
            "Tanggal": r["Tanggal"],
            "Isu": "Tanggal aktivitas di luar periode bulan target",
            "Tingkat": "Perlu cek",
        })

    if len(resp) >= 5:
        q3 = resp[COL_KM].quantile(0.75)
        iqr = q3 - resp[COL_KM].quantile(0.25)
        batas = q3 + 3 * iqr
        for _, r in resp[resp[COL_KM] > batas].iterrows():
            rows.append({
                "Peserta": r["Peserta"],
                "Tanggal": r["Tanggal"],
                "Isu": f"Jarak {r[COL_KM]:.2f} km jauh di atas pola normal (>{batas:.1f} km)",
                "Tingkat": "Outlier",
            })

    tanpa_bukti = resp[resp[COL_BUKTI].map(_clean) == ""]
    for _, r in tanpa_bukti.iterrows():
        rows.append({
            "Peserta": r["Peserta"],
            "Tanggal": r["Tanggal"],
            "Isu": "Tidak ada link screenshot Strava",
            "Tingkat": "Bukti kurang",
        })

    if not rows:
        return pd.DataFrame(columns=["Peserta", "Tanggal", "Isu", "Tingkat"])
    return pd.DataFrame(rows).sort_values(["Tingkat", "Peserta"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Komponen UI
# ---------------------------------------------------------------------------

def kpi_card(label: str, value: str, sub: str = "", pct: float | None = None,
             color: str = ACCENT) -> str:
    bar = ""
    if pct is not None:
        w = max(0.0, min(100.0, float(pct)))
        bar = f'<div class="bar"><div style="width:{w:.1f}%;background:{color}"></div></div>'
    return (
        f'<div class="kpi"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div>'
        f'<div class="sub">{sub}</div>{bar}</div>'
    )


def style_fig(fig, height: int = 340, legend: bool = True):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12, color=INK),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=GRID),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    title_text=""),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor="rgba(0,0,0,0)",
                     tickfont=dict(color=MUTED))
    return fig


def sec(title: str, sub: str = ""):
    st.markdown(f'<div class="sec">{title}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="sec-sub">{sub}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def chart_status_donut(rekap: pd.DataFrame):
    counts = rekap["Status"].value_counts().reindex(STATUS_ORDER, fill_value=0)
    fig = go.Figure(go.Pie(
        labels=list(counts.index), values=list(counts.values), hole=0.62, sort=False,
        marker=dict(colors=[STATUS_COLOR[s] for s in counts.index],
                    line=dict(color="white", width=2)),
        textinfo="value", textfont=dict(size=13, color="white"),
        hovertemplate="<b>%{label}</b><br>%{value} orang (%{percent})<extra></extra>",
    ))
    total = int(counts.sum())
    tercapai = int(counts.get("Tercapai", 0))
    fig.add_annotation(
        text=f"<b style='font-size:26px'>{tercapai}</b><br>"
             f"<span style='font-size:11px;color:{MUTED}'>dari {total} tercapai</span>",
        showarrow=False, font=dict(color=INK),
    )
    return style_fig(fig, 320)


def chart_leaderboard(rekap: pd.DataFrame, top_n: int):
    d = rekap[rekap["Aktual KM"] > 0].nlargest(top_n, "Aktual KM").sort_values("Aktual KM")
    if d.empty:
        return None
    d = d.assign(_pct=d["Pencapaian %"].clip(upper=200))
    fig = go.Figure(go.Bar(
        x=d["Aktual KM"], y=d["Nama"], orientation="h",
        marker=dict(color=d["_pct"], colorscale=[[0, DANGER], [0.5, WARN], [1, SUCCESS]],
                    cmin=0, cmax=100, line=dict(width=0)),
        text=[f"{v:.1f} km · {p:.0f}%" for v, p in zip(d["Aktual KM"], d["Pencapaian %"])],
        textposition="outside", textfont=dict(size=11, color=MUTED),
        customdata=np.stack([d["Target KM"], d["Total Aktivitas"], d["Divisi"]], axis=-1),
        hovertemplate="<b>%{y}</b><br>Aktual: %{x:.2f} km<br>Target: %{customdata[0]:.0f} km"
                      "<br>Aktivitas: %{customdata[1]}x<br>%{customdata[2]}<extra></extra>",
    ))
    fig.update_xaxes(title_text="Jarak tempuh (km)", range=[0, d["Aktual KM"].max() * 1.32])
    return style_fig(fig, max(300, 34 * len(d) + 90), legend=False)


def chart_tren(resp: pd.DataFrame, start, end, target_harian: float | None):
    daily = (resp.groupby("Tanggal")
             .agg(KM=(COL_KM, "sum"), Aktivitas=(COL_KM, "size"),
                  Peserta=("Peserta", "nunique"))
             .reindex(pd.date_range(start, end, freq="D"), fill_value=0))
    daily.index.name = "Tanggal"
    daily = daily.reset_index()
    daily["Kumulatif"] = daily["KM"].cumsum()

    today = pd.Timestamp(datetime.now(WITA).date())
    view = daily[daily["Tanggal"] <= max(today, resp["Tanggal"].max())]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=view["Tanggal"], y=view["KM"], name="KM per hari",
        marker=dict(color=ACCENT, opacity=0.82, line=dict(width=0)),
        customdata=np.stack([view["Aktivitas"], view["Peserta"]], axis=-1),
        hovertemplate="<b>%{x|%d %b}</b><br>%{y:.2f} km<br>"
                      "%{customdata[0]} aktivitas · %{customdata[1]} peserta<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=view["Tanggal"], y=view["Kumulatif"], name="Kumulatif", yaxis="y2",
        mode="lines+markers", line=dict(color=INK, width=2.4),
        marker=dict(size=5, color=INK),
        hovertemplate="Kumulatif: %{y:.1f} km<extra></extra>",
    ))
    if target_harian:
        fig.add_hline(y=target_harian, line=dict(color=SUCCESS, width=1.4, dash="dot"),
                      annotation_text=f"Pace ideal {target_harian:.1f} km/hari",
                      annotation_position="top left",
                      annotation_font=dict(size=10, color=SUCCESS))
    fig.update_layout(
        yaxis=dict(title="KM per hari"),
        yaxis2=dict(title="Kumulatif (km)", overlaying="y", side="right",
                    showgrid=False, tickfont=dict(color=MUTED)),
        barmode="overlay",
    )
    return style_fig(fig, 380)


def chart_divisi(rekap: pd.DataFrame):
    d = (rekap.groupby("Divisi")
         .agg(Aktual=("Aktual KM", "sum"), Peserta=("Peserta", "size"),
              Aktif=("Aktual KM", lambda s: int((s > 0).sum())))
         .reset_index())
    d["Partisipasi %"] = d["Aktif"] / d["Peserta"] * 100
    d = d.sort_values("Aktual")
    fig = go.Figure(go.Bar(
        x=d["Aktual"], y=d["Divisi"], orientation="h",
        marker=dict(color=ACCENT, line=dict(width=0)),
        text=[f"{v:.0f} km" for v in d["Aktual"]], textposition="outside",
        textfont=dict(size=11, color=MUTED),
        customdata=np.stack([d["Aktif"], d["Peserta"], d["Partisipasi %"]], axis=-1),
        hovertemplate="<b>%{y}</b><br>%{x:.1f} km<br>"
                      "%{customdata[0]}/%{customdata[1]} aktif (%{customdata[2]:.0f}%)<extra></extra>",
    ))
    fig.update_xaxes(range=[0, max(d["Aktual"].max() * 1.25, 1)])
    return style_fig(fig, max(280, 32 * len(d) + 80), legend=False)


def chart_status_divisi(rekap: pd.DataFrame):
    piv = (rekap.pivot_table(index="Divisi", columns="Status", values="Peserta",
                             aggfunc="count", observed=False)
           .reindex(columns=STATUS_ORDER).fillna(0))
    piv = piv.loc[piv.sum(axis=1).sort_values().index]
    fig = go.Figure()
    for s in STATUS_ORDER:
        fig.add_trace(go.Bar(
            x=piv[s], y=piv.index, name=s, orientation="h",
            marker=dict(color=STATUS_COLOR[s], line=dict(width=0)),
            hovertemplate=f"<b>%{{y}}</b><br>{s}: %{{x:.0f}} orang<extra></extra>",
        ))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title_text="Jumlah karyawan")
    return style_fig(fig, max(280, 32 * len(piv) + 90))


def chart_entitas(rekap: pd.DataFrame):
    d = (rekap.groupby("Entitas")
         .agg(Peserta=("Peserta", "size"),
              Aktif=("Aktual KM", lambda s: int((s > 0).sum())),
              KM=("Aktual KM", "sum"))
         .reset_index())
    d["Partisipasi %"] = d["Aktif"] / d["Peserta"] * 100
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d["Entitas"], y=d["Aktif"], name="Sudah submit",
        marker=dict(color=ACCENT, line=dict(width=0)),
        text=[f"{a}/{p}" for a, p in zip(d["Aktif"], d["Peserta"])],
        textposition="inside", textfont=dict(color="white", size=12),
        hovertemplate="<b>%{x}</b><br>Aktif: %{y} orang<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=d["Entitas"], y=d["Peserta"] - d["Aktif"], name="Belum submit",
        marker=dict(color="#E2E8F0", line=dict(width=0)),
        hovertemplate="<b>%{x}</b><br>Belum: %{y} orang<extra></extra>",
    ))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Jumlah karyawan")
    return style_fig(fig, 320)


def chart_jenis(rekap: pd.DataFrame):
    d = rekap[rekap["Aktual KM"] > 0]
    if d.empty:
        return None
    g = (d.groupby("Jenis")
         .agg(Peserta=("Peserta", "size"), KM=("Aktual KM", "sum"),
              Pencapaian=("Pencapaian %", "mean"))
         .reset_index().sort_values("KM", ascending=False))
    fig = go.Figure(go.Bar(
        x=g["Jenis"], y=g["KM"],
        marker=dict(color=[ACCENT, SUCCESS, WARN, MUTED][: len(g)], line=dict(width=0)),
        text=[f"{v:.0f} km" for v in g["KM"]], textposition="outside",
        textfont=dict(size=11, color=MUTED),
        customdata=np.stack([g["Peserta"], g["Pencapaian"]], axis=-1),
        hovertemplate="<b>%{x}</b><br>%{y:.1f} km<br>%{customdata[0]} peserta"
                      "<br>Rata2 pencapaian %{customdata[1]:.0f}%<extra></extra>",
    ))
    fig.update_yaxes(title_text="Total KM", range=[0, g["KM"].max() * 1.25])
    return style_fig(fig, 320, legend=False)


def chart_heatmap(resp: pd.DataFrame, start, end, top_n: int = 20):
    piv = resp.pivot_table(index="Nama", columns="Tanggal", values=COL_KM, aggfunc="sum")
    if piv.empty:
        return None
    piv = piv.loc[piv.sum(axis=1).nlargest(top_n).index]
    piv = piv.reindex(columns=pd.date_range(start, end, freq="D"))
    piv = piv.loc[piv.sum(axis=1).sort_values().index]

    fig = go.Figure(go.Heatmap(
        z=piv.values, x=[d.strftime("%d %b") for d in piv.columns], y=piv.index,
        colorscale=[[0, "#EFF6FF"], [0.5, "#93C5FD"], [1, ACCENT]],
        xgap=3, ygap=3, hoverongaps=False,
        colorbar=dict(title="KM", thickness=10, len=0.8, outlinewidth=0),
        hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2f} km<extra></extra>",
    ))
    return style_fig(fig, max(300, 26 * len(piv) + 110), legend=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🏃", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)

    # ---------------- Sidebar: sumber data ----------------
    with st.sidebar:
        st.markdown(f"### {APP_TITLE}")
        st.caption("Ops monitoring · TPB & GTN")
        st.divider()

        try:  # st.secrets bisa melempar error kalau secrets.toml belum ada
            has_sa = HAS_GSPREAD and "gcp_service_account" in st.secrets
        except Exception:  # noqa: BLE001
            has_sa = False
        opsi = ["Google Sheet (service account)"] if has_sa else []
        opsi += ["Upload file Excel", "Google Sheet (link publik)"]

        sumber = st.radio("Sumber data", opsi, index=0)

        data, err = None, None

        if sumber == "Google Sheet (service account)":
            cfg = st.secrets.get("gsheet", {})
            sid = cfg.get("sheet_id", DEFAULT_SHEET_ID)
            ws_r = cfg.get("worksheet_responses", "Form Responses 1")
            ws_m = cfg.get("worksheet_roster", "Sheet1")
            st.caption(f"Terhubung ke sheet `{sid[:12]}…` · tab **{ws_r}**")
            if st.button("🔄 Refresh data", width="stretch", type="primary"):
                st.cache_data.clear()
                st.rerun()
            try:
                data = load_gsheet_sa(sid, ws_r, ws_m or None,
                                      st.secrets["gcp_service_account"])
            except Exception as e:  # noqa: BLE001
                err = str(e)

        elif sumber == "Upload file Excel":
            up = st.file_uploader("File hasil export Google Form (.xlsx)", type=["xlsx", "xlsm"])
            if up is not None:
                try:
                    data = load_excel(up.getvalue())
                except Exception as e:  # noqa: BLE001
                    err = str(e)
            else:
                st.info("Upload file export Google Form untuk memulai.", icon="📄")

        else:
            sid = st.text_input("Sheet ID", value=DEFAULT_SHEET_ID)
            gid_r = st.text_input("GID tab Form Responses", value=DEFAULT_GID_RESP)
            gid_m = st.text_input("GID tab master karyawan (opsional)", value="")
            st.caption("Sheet harus di-share **Anyone with the link → Viewer**.")
            if st.button("🔄 Refresh data", width="stretch", type="primary"):
                st.cache_data.clear()
                st.rerun()
            if sid and gid_r:
                try:
                    data = load_gsheet_csv(sid.strip(), gid_r.strip(), gid_m.strip() or None)
                except Exception as e:  # noqa: BLE001
                    err = str(e)

        if err:
            st.error(f"Gagal membaca data: {err}", icon="⚠️")

    if data is None:
        st.markdown(
            f'<div class="hero"><h1>{APP_TITLE}</h1>'
            f'<p>{APP_SUB}</p></div>', unsafe_allow_html=True)
        st.info(
            "Pilih sumber data di panel kiri untuk menampilkan dashboard.\n\n"
            "**Format yang diharapkan** — tab *Form Responses* dengan kolom: "
            f"`{COL_TS}`, `{COL_NAMA}`, `{COL_KAT}`, `{COL_TGL}`, `{COL_KM}`, "
            f"`{COL_BULAN}`, `{COL_BUKTI}`. Tab kedua (opsional) berisi daftar master "
            "karyawan untuk menghitung tingkat partisipasi.",
            icon="👈",
        )
        return

    resp_all, roster_all = data

    # ---------------- Sidebar: filter ----------------
    with st.sidebar:
        st.divider()
        st.markdown("**Filter**")

        periodes = (resp_all[["Periode", "Periode Label"]].dropna()
                    .drop_duplicates().sort_values("Periode", ascending=False))
        if periodes.empty:
            st.error("Tidak ada periode yang bisa dibaca dari data.")
            return
        pilih = st.selectbox("Periode", periodes["Periode Label"].tolist(), index=0)
        periode = periodes.loc[periodes["Periode Label"] == pilih, "Periode"].iloc[0]

        ent_opsi = sorted(roster_all["Entitas"].unique())
        ent = st.multiselect("Entitas", ent_opsi, default=ent_opsi)

        div_opsi = sorted(roster_all["Divisi"].unique())
        div = st.multiselect("Divisi", div_opsi, default=div_opsi)

        st.divider()
        st.markdown("**Pengaturan**")
        target_default = st.number_input(
            "Target default untuk yang belum submit (km)",
            min_value=1.0, max_value=100.0, value=7.0, step=1.0,
            help="Dipakai saat kategori peserta belum diketahui karena belum pernah submit.",
        )
        top_n = st.slider("Jumlah peserta di leaderboard", 5, 40, 15)

    roster = roster_all[roster_all["Entitas"].isin(ent) & roster_all["Divisi"].isin(div)].copy()
    resp = resp_all[(resp_all["Periode"] == periode)
                    & resp_all["Peserta"].isin(set(roster["Peserta"]))].copy()

    berjalan, total_hari, start, end = periode_progress(periode)
    ratio = berjalan / total_hari if total_hari else 0.0

    rekap = build_rekap(resp, roster, ratio, target_default)

    # ---------------- Header ----------------
    now = datetime.now(WITA)
    st.markdown(
        f'<div class="hero"><h1>{APP_TITLE}'
        f'<span class="pill">{pilih}</span></h1>'
        f'<p>{APP_SUB} · Hari ke-{berjalan} dari {total_hari} '
        f'({start:%d %b} – {end:%d %b %Y}) · diperbarui {now:%d %b %Y, %H:%M} WITA</p></div>',
        unsafe_allow_html=True,
    )

    if rekap.empty:
        st.warning("Tidak ada data untuk kombinasi filter ini.", icon="🔍")
        return

    # ---------------- KPI ----------------
    n_roster = len(rekap)
    n_aktif = int((rekap["Aktual KM"] > 0).sum())
    partisipasi = n_aktif / n_roster * 100 if n_roster else 0
    total_km = rekap["Aktual KM"].sum()
    total_akt = int(rekap["Total Aktivitas"].sum())
    n_tercapai = int((rekap["Status"] == "Tercapai").sum())
    pct_tercapai = n_tercapai / n_roster * 100 if n_roster else 0
    total_target = rekap["Target KM"].sum()
    pace_pct = total_km / (total_target * ratio) * 100 if total_target and ratio else 0
    km_per_aktif = total_km / n_aktif if n_aktif else 0

    c = st.columns(5)
    c[0].markdown(kpi_card(
        "Partisipasi", f"{n_aktif}<small>/{n_roster}</small>",
        f"{partisipasi:.0f}% karyawan sudah submit", partisipasi, ACCENT), unsafe_allow_html=True)
    c[1].markdown(kpi_card(
        "Total Jarak", f"{total_km:,.0f}<small> km</small>",
        f"dari target kolektif {total_target:,.0f} km",
        total_km / total_target * 100 if total_target else 0, SUCCESS), unsafe_allow_html=True)
    c[2].markdown(kpi_card(
        "Sudah Capai Target", f"{n_tercapai}<small>/{n_roster}</small>",
        f"{pct_tercapai:.0f}% dari total karyawan", pct_tercapai, SUCCESS),
        unsafe_allow_html=True)
    warna_pace = SUCCESS if pace_pct >= 100 else (WARN if pace_pct >= 70 else DANGER)
    c[3].markdown(kpi_card(
        "Pace vs Ideal", f"{pace_pct:.0f}<small>%</small>",
        f"pace ideal hari ke-{berjalan}: {total_target * ratio:,.0f} km",
        min(pace_pct, 100), warna_pace), unsafe_allow_html=True)
    c[4].markdown(kpi_card(
        "Aktivitas Tercatat", f"{total_akt}",
        f"rata-rata {km_per_aktif:.1f} km per peserta aktif"), unsafe_allow_html=True)

    st.markdown("")

    # ---------------- Tabs ----------------
    t1, t2, t3, t4, t5 = st.tabs(
        ["📊 Ringkasan", "🏅 Leaderboard", "📈 Tren Harian", "🏢 Breakdown", "📋 Detail & Tindak Lanjut"]
    )

    # --- Ringkasan ---
    with t1:
        a, b = st.columns([1, 1.35])
        with a:
            sec("Status Pencapaian", f"Ambang On Track: {ratio * 100:.0f}% dari target bulanan")
            st.plotly_chart(chart_status_donut(rekap), width="stretch")
        with b:
            sec("Progres per Divisi", "Jumlah karyawan menurut status pencapaian")
            st.plotly_chart(chart_status_divisi(rekap), width="stretch")

        belum = rekap[rekap["Status"] == "Belum Mulai"]
        tertinggal = rekap[rekap["Status"] == "Tertinggal"]
        if len(belum) or len(tertinggal):
            st.markdown(
                f'<div class="note warn"><b>Perlu tindak lanjut HR.</b> '
                f'{len(belum)} karyawan belum submit sama sekali dan {len(tertinggal)} '
                f'karyawan tertinggal dari pace ideal. Sisa {total_hari - berjalan} hari '
                f'di periode ini. Daftar lengkapnya ada di tab '
                f'<i>Detail &amp; Tindak Lanjut</i>.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="note ok"><b>Semua karyawan on track atau sudah mencapai '
                'target.</b> Tidak ada yang perlu di-follow-up periode ini.</div>',
                unsafe_allow_html=True,
            )

        a, b = st.columns(2)
        with a:
            sec("Partisipasi per Entitas")
            st.plotly_chart(chart_entitas(rekap), width="stretch")
        with b:
            sec("Kontribusi per Jenis Aktivitas")
            f = chart_jenis(rekap)
            if f:
                st.plotly_chart(f, width="stretch")
            else:
                st.info("Belum ada aktivitas tercatat pada periode ini.")

    # --- Leaderboard ---
    with t2:
        sec("Peringkat Peserta", f"Top {top_n} berdasarkan total jarak tempuh · "
                                 "warna batang = persentase pencapaian target")
        f = chart_leaderboard(rekap, top_n)
        if f:
            st.plotly_chart(f, width="stretch")
        else:
            st.info("Belum ada peserta yang submit pada periode ini.")

        st.markdown("")
        sec("Papan Peringkat Lengkap")
        board = rekap[rekap["Aktual KM"] > 0].copy()
        board.insert(0, "#", range(1, len(board) + 1))
        st.dataframe(
            board[["#", "Nama", "Entitas", "Divisi", "Jenis", "Aktual KM", "Target KM",
                   "Pencapaian %", "Total Aktivitas", "Hari Aktif", "Aktivitas Terjauh",
                   "Status"]],
            hide_index=True, width="stretch",
            column_config={
                "Aktual KM": st.column_config.NumberColumn(format="%.2f km"),
                "Target KM": st.column_config.NumberColumn(format="%.0f km"),
                "Aktivitas Terjauh": st.column_config.NumberColumn(format="%.2f km"),
                "Pencapaian %": st.column_config.ProgressColumn(
                    "Pencapaian", format="%.0f%%", min_value=0, max_value=100),
            },
        )

    # --- Tren ---
    with t3:
        pace_harian = (rekap["Target KM"].sum() / total_hari) if total_hari else None
        sec("Tren Aktivitas Harian",
            "Batang = jarak per hari · garis = akumulasi bulan berjalan")
        if resp.empty:
            st.info("Belum ada aktivitas tercatat pada periode ini.")
        else:
            st.plotly_chart(chart_tren(resp, start, end, pace_harian),
                            width="stretch")

            a, b, cc = st.columns(3)
            daily_km = resp.groupby("Tanggal")[COL_KM].sum()
            hari_ada = int(daily_km.size)
            a.metric("Hari dengan aktivitas", f"{hari_ada} / {berjalan}",
                     help="Jumlah hari yang punya minimal satu submission")
            b.metric("Hari terproduktif",
                     f"{daily_km.idxmax():%d %b}" if hari_ada else "-",
                     f"{daily_km.max():.1f} km" if hari_ada else None)
            c_avg = daily_km.sum() / berjalan if berjalan else 0
            cc.metric("Rata-rata per hari kalender", f"{c_avg:.1f} km")

            st.markdown("")
            sec("Konsistensi Peserta",
                f"Distribusi jarak harian · top {min(20, resp['Nama'].nunique())} peserta")
            f = chart_heatmap(resp, start, end)
            if f:
                st.plotly_chart(f, width="stretch")

    # --- Breakdown ---
    with t4:
        a, b = st.columns(2)
        with a:
            sec("Total Jarak per Divisi")
            st.plotly_chart(chart_divisi(rekap), width="stretch")
        with b:
            sec("Ringkasan Divisi", "Partisipasi dan pencapaian rata-rata")
            g = (rekap.groupby("Divisi", observed=False)
                 .agg(Karyawan=("Peserta", "size"),
                      Aktif=("Aktual KM", lambda s: int((s > 0).sum())),
                      **{"Total KM": ("Aktual KM", "sum"),
                         "Rata2 Pencapaian %": ("Pencapaian %", "mean")})
                 .reset_index())
            g["Partisipasi %"] = g["Aktif"] / g["Karyawan"] * 100
            st.dataframe(
                g.sort_values("Total KM", ascending=False),
                hide_index=True, width="stretch",
                column_config={
                    "Total KM": st.column_config.NumberColumn(format="%.1f km"),
                    "Partisipasi %": st.column_config.ProgressColumn(
                        format="%.0f%%", min_value=0, max_value=100),
                    "Rata2 Pencapaian %": st.column_config.NumberColumn(format="%.0f%%"),
                },
            )

        st.markdown("")
        sec("Perbandingan Entitas")
        g2 = (rekap.groupby("Entitas", observed=False)
              .agg(Karyawan=("Peserta", "size"),
                   Aktif=("Aktual KM", lambda s: int((s > 0).sum())),
                   Tercapai=("Status", lambda s: int((s == "Tercapai").sum())),
                   **{"Total KM": ("Aktual KM", "sum"),
                      "Total Aktivitas": ("Total Aktivitas", "sum")})
              .reset_index())
        g2["Partisipasi %"] = g2["Aktif"] / g2["Karyawan"] * 100
        g2["KM per Karyawan"] = g2["Total KM"] / g2["Karyawan"]
        st.dataframe(
            g2, hide_index=True, width="stretch",
            column_config={
                "Total KM": st.column_config.NumberColumn(format="%.1f km"),
                "KM per Karyawan": st.column_config.NumberColumn(format="%.2f km"),
                "Partisipasi %": st.column_config.ProgressColumn(
                    format="%.0f%%", min_value=0, max_value=100),
            },
        )

    # --- Detail & tindak lanjut ---
    with t5:
        sec("Daftar Tindak Lanjut", "Karyawan yang perlu diingatkan sebelum periode berakhir")
        fu = rekap[rekap["Status"].isin(["Belum Mulai", "Tertinggal"])].copy()
        fu = fu.sort_values(["Status", "Sisa KM"], ascending=[True, False])
        if fu.empty:
            st.success("Tidak ada karyawan yang perlu di-follow-up. 🎉")
        else:
            sisa_hari = max(total_hari - berjalan, 1)
            fu["KM/hari agar tercapai"] = fu["Sisa KM"] / sisa_hari
            st.dataframe(
                fu[["Nama", "Entitas", "Jabatan", "Divisi", "Status", "Aktual KM",
                    "Target KM", "Sisa KM", "KM/hari agar tercapai", "Aktivitas Terakhir"]],
                hide_index=True, width="stretch",
                column_config={
                    "Aktual KM": st.column_config.NumberColumn(format="%.2f km"),
                    "Target KM": st.column_config.NumberColumn(format="%.0f km"),
                    "Sisa KM": st.column_config.NumberColumn(format="%.2f km"),
                    "KM/hari agar tercapai": st.column_config.NumberColumn(format="%.2f km"),
                    "Aktivitas Terakhir": st.column_config.DateColumn(format="DD MMM YYYY"),
                },
            )
            st.download_button(
                "⬇️ Unduh daftar tindak lanjut (CSV)",
                fu.to_csv(index=False).encode("utf-8"),
                file_name=f"follow_up_{pilih.replace(' ', '_')}.csv",
                mime="text/csv",
            )

        st.markdown("")
        sec("Verifikasi Data", "Entri yang sebaiknya dicek sebelum rekap dikunci")
        anom = find_anomali(resp, periode)
        if anom.empty:
            st.markdown('<div class="note ok">Tidak ada anomali terdeteksi pada '
                        'periode ini.</div>', unsafe_allow_html=True)
        else:
            st.dataframe(anom, hide_index=True, width="stretch",
                         column_config={"Tanggal": st.column_config.DateColumn(
                             format="DD MMM YYYY")})

        st.markdown("")
        sec("Log Aktivitas", "Seluruh submission pada periode terpilih")
        detail = resp[["Tanggal", "Nama", "Entitas", "Divisi", "Jenis", COL_KM,
                       COL_BUKTI, COL_TS]].sort_values(COL_TS, ascending=False)
        st.dataframe(
            detail, hide_index=True, width="stretch",
            column_config={
                "Tanggal": st.column_config.DateColumn(format="DD MMM YYYY"),
                COL_TS: st.column_config.DatetimeColumn("Waktu Submit",
                                                        format="DD MMM YYYY HH:mm"),
                COL_KM: st.column_config.NumberColumn("Jarak", format="%.2f km"),
                COL_BUKTI: st.column_config.LinkColumn("Bukti Strava", display_text="Buka"),
            },
        )

        d1, d2 = st.columns(2)
        d1.download_button(
            "⬇️ Unduh rekap per karyawan (CSV)",
            rekap.to_csv(index=False).encode("utf-8"),
            file_name=f"rekap_{pilih.replace(' ', '_')}.csv",
            mime="text/csv", width="stretch",
        )
        d2.download_button(
            "⬇️ Unduh log aktivitas (CSV)",
            detail.to_csv(index=False).encode("utf-8"),
            file_name=f"log_aktivitas_{pilih.replace(' ', '_')}.csv",
            mime="text/csv", width="stretch",
        )


if __name__ == "__main__":
    main()
