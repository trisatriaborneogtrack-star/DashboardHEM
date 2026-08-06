"""
Healthy Employee Movement Program — Dashboard
=============================================
Dashboard monitoring aktivitas olahraga karyawan (Walking / Running) berbasis
submission Google Form + bukti Strava.

Sumber data: Google Sheet (otomatis — service account kalau tersedia, kalau tidak
lewat CSV export). Tidak ada sidebar: semua filter ada di halaman utama.

Jalankan:
    streamlit run app.py
"""

from __future__ import annotations

import hmac
import io
import re
import traceback
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:  # opsional — dipakai kalau sheet dibaca via service account
    import gspread

    HAS_GSPREAD = True
except ImportError:  # pragma: no cover
    HAS_GSPREAD = False

SHEETS_EPOCH = pd.Timestamp("1899-12-30")

# ---------------------------------------------------------------------------
# Identitas & palet
# ---------------------------------------------------------------------------

APP_TITLE = "Healthy Employee Movement Program"
APP_SUB = "Monitoring aktivitas olahraga karyawan TPB & GTN"

WITA = timezone(timedelta(hours=8))

# Warna cerah — HANYA untuk isian grafik, latar, dan aksen (bukan teks)
INDIGO = "#5B5BD6"
VIOLET = "#8B5CF6"
CYAN = "#06B6D4"
EMERALD = "#10B981"
AMBER = "#F59E0B"
ROSE = "#F43F5E"
PINK = "#EC4899"

# Varian gelap — dipakai kalau warna tersebut jadi TEKS di atas latar terang.
# Versi cerahnya punya kontras < 3:1 pada latar putih sehingga tidak terbaca.
INDIGO_T = "#4338CA"
VIOLET_T = "#6D28D9"
CYAN_T = "#0E7490"
EMERALD_T = "#047857"
AMBER_T = "#B45309"
ROSE_T = "#BE123C"

TEKS_AKSEN = {
    INDIGO: INDIGO_T, VIOLET: VIOLET_T, CYAN: CYAN_T,
    EMERALD: EMERALD_T, AMBER: AMBER_T, ROSE: ROSE_T,
}

INK = "#181B2E"        # teks utama  — kontras ~14:1 di latar putih
MUTED = "#5A6288"      # teks sekunder — kontras ~6.4:1 (sebelumnya #7A82A6 ≈ 4:1)
GRID = "#E3E6F4"

PALETTE = [INDIGO, CYAN, EMERALD, AMBER, PINK, VIOLET, "#14B8A6", "#F97316"]

STATUS_ORDER = ["Tercapai", "On Track", "Tertinggal", "Belum Mulai"]
STATUS_COLOR = {
    "Tercapai": EMERALD,
    "On Track": INDIGO,
    "Tertinggal": AMBER,
    "Belum Mulai": ROSE,
}
STATUS_EMOJI = {
    "Tercapai": "🏆", "On Track": "🚀", "Tertinggal": "⚡", "Belum Mulai": "💤",
}

HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

BULAN_ID = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
    "september": 9, "oktober": 10, "november": 11, "desember": 12,
}
BULAN_NAMA = {v: k.capitalize() for k, v in BULAN_ID.items()}

DEFAULT_SHEET_ID = "1I30t7uLOzwBMVyq0k-Rfy1NTzGUFLbT9v37XeFjKbF0"
DEFAULT_GID_RESP = "1186413594"
DEFAULT_WS_RESP = "Form Responses 1"
DEFAULT_WS_ROSTER = "Sheet1"

COL_TS = "Timestamp"
COL_NAMA = "Nama Karyawan"
COL_KAT = "Kategori"
COL_TGL = "Tanggal Aktifitas"
COL_KM = "Jarak Tempuh Aktivitas (Km)"
COL_BULAN = "Bulan Target"
COL_BUKTI = "Screenshot Aktivitas Strava"

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

  /* Kunci skema terang. Tanpa ini, browser/OS dalam mode gelap membuat Streamlit
     memakai teks putih di atas latar terang buatan kita -> tidak terbaca. */
  :root, .stApp { color-scheme: light !important; }

  html, body, [class*="css"], .stApp { font-family: 'Plus Jakarta Sans', system-ui, sans-serif; }
  .stApp { background: #F5F6FC; color: #181B2E; }
  .block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1480px; }

  /* Sidebar dimatikan; header dibiarkan agar menu Settings tetap bisa dibuka. */
  section[data-testid="stSidebar"], div[data-testid="collapsedControl"] { display: none !important; }
  [data-testid="stAppDeployButton"], footer { display: none !important; }
  header[data-testid="stHeader"] { background: transparent; }

  /* ---------- paksa warna teks bawaan Streamlit ---------- */
  .stApp p, .stApp li, .stApp label, .stApp .stMarkdown,
  [data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
  [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p,
  [data-testid="stExpander"] summary, [data-testid="stExpander"] p,
  .stSelectbox label, .stTextInput label, .stNumberInput label, .stSlider label {
      color: #181B2E !important;
  }
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
  .stApp small { color: #5A6288 !important; }
  [data-testid="stMetricValue"] { font-size: 1.32rem; font-weight: 800; color: #181B2E !important; }
  [data-testid="stMetricDelta"] { color: #047857 !important; }

  /* input & dropdown */
  .stSelectbox div[data-baseweb="select"] > div, .stTextInput input,
  .stNumberInput input { background: #fff !important; color: #181B2E !important;
      border-color: #DDE1F2 !important; }
  .stTextInput input::placeholder { color: #8A91B4 !important; }
  div[data-baseweb="popover"] li { color: #181B2E !important; }

  /* pills & segmented control */
  div[data-testid="stPills"] button, div[data-testid="stSegmentedControl"] button {
      color: #3B4168 !important; background: #fff !important; border-color: #DDE1F2 !important;
      font-weight: 600; }
  div[data-testid="stPills"] button[aria-checked="true"],
  div[data-testid="stSegmentedControl"] button[aria-checked="true"] {
      background: #4F46E5 !important; color: #fff !important; border-color: #4F46E5 !important; }

  /* ---------- hero ---------- */
  .hero { background: linear-gradient(115deg,#4338CA 0%,#6D28D9 45%,#BE185D 100%);
          border-radius: 20px; padding: 1.5rem 1.8rem; position: relative;
          overflow: hidden; box-shadow: 0 14px 34px -14px rgba(67,56,202,.5); }
  .hero::after { content:""; position:absolute; right:-70px; top:-90px; width:290px; height:290px;
                 border-radius:50%; background:rgba(255,255,255,.10); }
  .hero::before { content:""; position:absolute; right:80px; bottom:-120px; width:210px; height:210px;
                  background:rgba(255,255,255,.07); border-radius:50%; }
  .hero h1, .hero p, .hero .tag { color:#fff !important; position:relative; z-index:1; }
  .hero h1 { font-size:1.7rem; font-weight:800; margin:0 0 .3rem 0; letter-spacing:-.03em;
             line-height:1.14; }
  .hero p { margin:0; font-size:.9rem; opacity:.93; }
  .hero .tags { margin-top:.85rem; display:flex; gap:.45rem; flex-wrap:wrap;
                position:relative; z-index:1; }
  .hero .tag { background:rgba(255,255,255,.2); border:1px solid rgba(255,255,255,.32);
               padding:.24rem .68rem; border-radius:999px; font-size:.74rem; font-weight:600; }
  .hero .track { margin-top:1rem; height:7px; background:rgba(255,255,255,.25);
                 border-radius:99px; overflow:hidden; position:relative; z-index:1; }
  .hero .track > div { height:100%; background:#fff; border-radius:99px; }

  /* ---------- kartu KPI ---------- */
  .kpi { background:#fff; border-radius:16px; padding:1rem 1.05rem; height:100%;
         border:1px solid #E6E9F7; box-shadow:0 2px 10px -4px rgba(24,27,46,.1);
         position:relative; overflow:hidden; transition:transform .16s ease, box-shadow .16s ease; }
  .kpi:hover { transform:translateY(-3px); box-shadow:0 12px 26px -14px rgba(24,27,46,.3); }
  .kpi .cap { position:absolute; inset:0 0 auto 0; height:4px; }
  .kpi .row { display:flex; align-items:center; gap:.5rem; margin:.25rem 0 .55rem 0; }
  .kpi .ico { width:30px; height:30px; border-radius:9px; display:grid; place-items:center;
              font-size:.95rem; flex:none; }
  .kpi .lbl { font-size:.7rem; font-weight:700; color:#4A5178; text-transform:uppercase;
              letter-spacing:.06em; }
  .kpi .val { font-size:1.9rem; font-weight:800; color:#181B2E; line-height:1;
              letter-spacing:-.035em; }
  .kpi .val small { font-size:.85rem; font-weight:700; color:#5A6288; margin-left:.15rem;
                    letter-spacing:0; }
  .kpi .sub { font-size:.76rem; color:#5A6288; margin-top:.42rem; line-height:1.4; }
  .kpi .bar { height:6px; background:#EEF0FA; border-radius:99px; margin-top:.6rem; overflow:hidden; }
  .kpi .bar > div { height:100%; border-radius:99px; }

  /* ---------- kartu insight ---------- */
  .ins { border-radius:14px; padding:.8rem .95rem; height:100%; border:1px solid transparent;
         background:#fff; }
  .ins .t { font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em;
            margin-bottom:.28rem; display:flex; align-items:center; gap:.38rem; }
  .ins .dot { width:7px; height:7px; border-radius:50%; display:inline-block; flex:none; }
  .ins .v { font-size:.96rem; font-weight:700; line-height:1.28; color:#181B2E; }
  .ins .d { font-size:.76rem; margin-top:.22rem; line-height:1.4; color:#5A6288; }

  /* ---------- podium ---------- */
  .pod { background:#fff; border:1px solid #E6E9F7; border-radius:16px; padding:.95rem;
         text-align:center; box-shadow:0 2px 10px -4px rgba(24,27,46,.1); height:100%; }
  .pod .m { font-size:1.7rem; line-height:1; }
  .pod .n { font-size:.88rem; font-weight:700; color:#181B2E; margin-top:.45rem; line-height:1.25; }
  .pod .k { font-size:1.3rem; font-weight:800; letter-spacing:-.03em; margin-top:.3rem; }
  .pod .s { font-size:.72rem; color:#5A6288; margin-top:.15rem; }

  /* ---------- umum ---------- */
  .sec { font-size:1rem; font-weight:700; color:#181B2E; margin:.2rem 0 .1rem 0;
         letter-spacing:-.015em; }
  .sec-sub { font-size:.79rem; color:#5A6288; margin-bottom:.6rem; }
  .note { border-radius:12px; padding:.75rem .95rem; font-size:.83rem; line-height:1.5;
          margin:.3rem 0 .9rem 0; }
  .note.warn { background:#FFF7ED; border:1px solid #FDBA74; color:#7C2D12; }
  .note.ok { background:#ECFDF5; border:1px solid #6EE7B7; color:#065F46; }
  .note b { color: inherit; }

  .stTabs [data-baseweb="tab-list"] { gap:.25rem; background:#fff; padding:.3rem;
      border-radius:13px; border:1px solid #E6E9F7; }
  .stTabs [data-baseweb="tab-list"] button { border-radius:9px; font-weight:600;
      font-size:.85rem; padding:.42rem .95rem; color:#4A5178 !important; }
  .stTabs [aria-selected="true"] { background:linear-gradient(120deg,#4338CA,#6D28D9) !important; }
  .stTabs [aria-selected="true"] * { color:#fff !important; }
  .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }

  div[data-testid="stExpander"] { border:1px solid #E6E9F7; border-radius:13px; background:#fff; }
  .stDownloadButton button, .stButton button { border-radius:10px; font-weight:600;
      color:#181B2E; border-color:#DDE1F2; }
  .stButton button[kind="primary"], .stFormSubmitButton button { color:#fff !important; }
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
# Metrik turunan
# ---------------------------------------------------------------------------

def hitung_ringkasan(rekap: pd.DataFrame, ratio: float) -> dict:
    """Semua angka KPI dikumpulkan di satu tempat supaya konsisten antar panel."""
    n = len(rekap)
    aktif = int((rekap["Aktual KM"] > 0).sum())
    total_km = float(rekap["Aktual KM"].sum())
    total_target = float(rekap["Target KM"].sum())
    tercapai = int((rekap["Status"] == "Tercapai").sum())
    pace_ideal = total_target * ratio
    return {
        "n": n,
        "aktif": aktif,
        "partisipasi": aktif / n * 100 if n else 0.0,
        "total_km": total_km,
        "total_target": total_target,
        "progres_km": total_km / total_target * 100 if total_target else 0.0,
        "tercapai": tercapai,
        "pct_tercapai": tercapai / n * 100 if n else 0.0,
        "pace_ideal": pace_ideal,
        "pace_pct": total_km / pace_ideal * 100 if pace_ideal else 0.0,
        "aktivitas": int(rekap["Total Aktivitas"].sum()),
        "km_per_aktif": total_km / aktif if aktif else 0.0,
        # Ekstrapolasi linear dari pace saat ini ke akhir bulan
        "proyeksi": total_km / ratio if ratio > 0 else 0.0,
    }


def susun_insight(rekap: pd.DataFrame, resp: pd.DataFrame, r: dict,
                  sisa_hari: int) -> list[dict]:
    """Tiga sorotan otomatis yang paling relevan untuk periode berjalan."""
    out = []

    aktif = rekap[rekap["Aktual KM"] > 0]
    if not aktif.empty:
        div = (rekap.groupby("Divisi", observed=False)
               .agg(a=("Aktual KM", lambda s: int((s > 0).sum())), n=("Peserta", "size"),
                    km=("Aktual KM", "sum")))
        div = div[div["n"] >= 2]
        if not div.empty:
            div["p"] = div["a"] / div["n"] * 100
            top = div.sort_values(["p", "km"], ascending=False).iloc[0]
            out.append({
                "t": "Divisi terdepan", "v": str(div.sort_values(['p','km'], ascending=False).index[0]),
                "d": f"{int(top['a'])} dari {int(top['n'])} orang aktif "
                     f"({top['p']:.0f}%) · {top['km']:.0f} km",
                "c": INDIGO,
            })

        konsisten = aktif.sort_values(["Hari Aktif", "Aktual KM"], ascending=False).iloc[0]
        out.append({
            "t": "Paling konsisten", "v": str(konsisten["Nama"]),
            "d": f"{int(konsisten['Hari Aktif'])} hari aktif · "
                 f"{konsisten['Aktual KM']:.1f} km · {konsisten['Pencapaian %']:.0f}% target",
            "c": EMERALD,
        })

    if not resp.empty:
        hari = resp.groupby(resp["Tanggal"].dt.dayofweek)[COL_KM].sum()
        if not hari.empty:
            fav = int(hari.idxmax())
            out.append({
                "t": "Hari paling aktif", "v": HARI_ID[fav],
                "d": f"{hari.max():.0f} km terkumpul di hari {HARI_ID[fav]}",
                "c": CYAN,
            })

    belum = int((rekap["Status"] == "Belum Mulai").sum())
    if belum:
        out.append({
            "t": "Butuh dorongan", "v": f"{belum} karyawan belum mulai",
            "d": f"Sisa {sisa_hari} hari untuk mengejar target periode ini",
            "c": ROSE,
        })

    if r["pace_pct"] >= 100:
        out.append({
            "t": "Status program", "v": "Di atas pace ideal",
            "d": f"Terkumpul {r['total_km']:.0f} km, {r['pace_pct'] - 100:.0f}% "
                 f"di atas target hari ini",
            "c": EMERALD,
        })

    return out[:4]


# ---------------------------------------------------------------------------
# Komponen tampilan
# ---------------------------------------------------------------------------

def kartu_kpi(label: str, nilai: str, sub: str, ikon: str, warna: str,
              pct: float | None = None) -> str:
    bar = ""
    if pct is not None:
        w = max(0.0, min(100.0, float(pct)))
        bar = (f'<div class="bar"><div style="width:{w:.1f}%;'
               f'background:linear-gradient(90deg,{warna},{warna}bb)"></div></div>')
    return (
        f'<div class="kpi"><div class="cap" style="background:linear-gradient('
        f'90deg,{warna},{warna}55)"></div>'
        f'<div class="row"><div class="ico" style="background:{warna}1f">{ikon}</div>'
        f'<div class="lbl">{label}</div></div>'
        f'<div class="val">{nilai}</div><div class="sub">{sub}</div>{bar}</div>'
    )


def kartu_insight(d: dict) -> str:
    c = d["c"]
    teks = TEKS_AKSEN.get(c, INK)  # varian gelap supaya terbaca di latar terang
    return (
        f'<div class="ins" style="background:{c}0f;border-color:{c}40">'
        f'<div class="t" style="color:{teks}">'
        f'<span class="dot" style="background:{c}"></span>{d["t"]}</div>'
        f'<div class="v">{d["v"]}</div>'
        f'<div class="d">{d["d"]}</div></div>'
    )


def kartu_podium(medali: str, nama: str, km: float, sub: str, warna: str) -> str:
    return (
        f'<div class="pod"><div class="m">{medali}</div>'
        f'<div class="n">{nama}</div>'
        f'<div class="k" style="color:{warna}">{km:.1f} km</div>'
        f'<div class="s">{sub}</div></div>'
    )


def rapikan(fig, tinggi: int = 340, legend: bool = True):
    fig.update_layout(
        height=tinggi,
        margin=dict(l=8, r=8, t=26, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Plus Jakarta Sans, system-ui, sans-serif", size=12, color=INK),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=GRID,
                        font_family="Plus Jakarta Sans"),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0,
                    title_text="", font=dict(size=11)),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED, size=11))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor="rgba(0,0,0,0)",
                     tickfont=dict(color=MUTED, size=11))
    return fig


@contextmanager
def aman(nama: str):
    """Isolasi satu panel.

    Tanpa ini, satu kesalahan di panel mana pun menghentikan seluruh script dan
    halaman terpotong di titik itu. Dengan ini, panel yang bermasalah diganti kotak
    pesan dan sisa dashboard tetap tampil — sekaligus menunjukkan traceback yang
    bisa dilaporkan.
    """
    try:
        yield
    except Exception as e:  # noqa: BLE001
        st.error(f"Panel **{nama}** gagal dirender — {type(e).__name__}: {e}", icon="⚠️")
        with st.expander(f"Detail teknis · {nama}"):
            st.code(traceback.format_exc(), language="text")


def judul(teks: str, sub: str = ""):
    st.markdown(f'<div class="sec">{teks}</div>', unsafe_allow_html=True)
    if sub:
        st.markdown(f'<div class="sec-sub">{sub}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Grafik
# ---------------------------------------------------------------------------

def g_donat_status(rekap: pd.DataFrame):
    c = rekap["Status"].value_counts().reindex(STATUS_ORDER, fill_value=0)
    fig = go.Figure(go.Pie(
        labels=[f"{STATUS_EMOJI[s]} {s}" for s in c.index], values=list(c.values),
        hole=0.66, sort=False,
        marker=dict(colors=[STATUS_COLOR[s] for s in c.index],
                    line=dict(color="white", width=3)),
        textinfo="value", textfont=dict(size=13, color="white", family="Plus Jakarta Sans"),
        hovertemplate="<b>%{label}</b><br>%{value} orang (%{percent})<extra></extra>",
    ))
    total, ok = int(c.sum()), int(c.get("Tercapai", 0))
    fig.add_annotation(
        text=f"<b style='font-size:30px;color:{EMERALD_T}'>{ok}</b><br>"
             f"<span style='font-size:11px;color:{MUTED}'>dari {total} tercapai</span>",
        showarrow=False)
    return rapikan(fig, 320)


def g_leaderboard(rekap: pd.DataFrame, n: int):
    d = rekap[rekap["Aktual KM"] > 0].nlargest(n, "Aktual KM").sort_values("Aktual KM")
    if d.empty:
        return None
    fig = go.Figure(go.Bar(
        x=d["Aktual KM"], y=d["Nama"], orientation="h",
        marker=dict(color=d["Pencapaian %"].clip(upper=120),
                    colorscale=[[0, ROSE], [0.45, AMBER], [0.8, INDIGO], [1, EMERALD]],
                    cmin=0, cmax=120, line=dict(width=0)),
        text=[f"{v:.1f} km · {p:.0f}%" for v, p in zip(d["Aktual KM"], d["Pencapaian %"])],
        textposition="outside", textfont=dict(size=11, color=MUTED),
        customdata=np.stack([d["Target KM"], d["Total Aktivitas"], d["Divisi"]], axis=-1),
        hovertemplate="<b>%{y}</b><br>Aktual %{x:.2f} km dari target %{customdata[0]:.0f} km"
                      "<br>%{customdata[1]} aktivitas · %{customdata[2]}<extra></extra>",
    ))
    fig.update_xaxes(title_text="Jarak tempuh (km)", range=[0, d["Aktual KM"].max() * 1.35])
    return rapikan(fig, max(300, 33 * len(d) + 85), legend=False)


def g_tren(resp: pd.DataFrame, start, end, pace_harian: float | None):
    idx = pd.date_range(start, end, freq="D")
    d = (resp.groupby("Tanggal")
         .agg(KM=(COL_KM, "sum"), Akt=(COL_KM, "size"), Org=("Peserta", "nunique"))
         .reindex(idx, fill_value=0))
    d.index.name = "Tanggal"
    d = d.reset_index()
    d["Kum"] = d["KM"].cumsum()
    batas = max(pd.Timestamp(datetime.now(WITA).date()), resp["Tanggal"].max())
    v = d[d["Tanggal"] <= batas]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=v["Tanggal"], y=v["Kum"], name="Kumulatif", yaxis="y2", mode="lines",
        line=dict(color=VIOLET, width=3, shape="spline"),
        fill="tozeroy", fillcolor="rgba(139,92,246,.13)",
        hovertemplate="Kumulatif %{y:.1f} km<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=v["Tanggal"], y=v["KM"], name="KM per hari",
        marker=dict(color=INDIGO, line=dict(width=0)), opacity=.9,
        customdata=np.stack([v["Akt"], v["Org"]], axis=-1),
        hovertemplate="<b>%{x|%d %b}</b><br>%{y:.2f} km<br>"
                      "%{customdata[0]} aktivitas · %{customdata[1]} peserta<extra></extra>",
    ))
    if pace_harian:
        fig.add_hline(y=pace_harian, line=dict(color=EMERALD, width=1.5, dash="dot"),
                      annotation_text=f"Pace ideal {pace_harian:.1f} km/hari",
                      annotation_position="top left",
                      annotation_font=dict(size=11, color=EMERALD_T))
    fig.update_layout(
        yaxis=dict(title="KM per hari"),
        yaxis2=dict(title="Kumulatif (km)", overlaying="y", side="right",
                    showgrid=False, tickfont=dict(color=MUTED, size=11)),
    )
    return rapikan(fig, 370)


def g_hari(resp: pd.DataFrame):
    if resp.empty:
        return None
    s = resp.groupby(resp["Tanggal"].dt.dayofweek).agg(
        KM=(COL_KM, "sum"), Akt=(COL_KM, "size")).reindex(range(7), fill_value=0)
    warna = [EMERALD if i == int(s["KM"].idxmax()) else "#AEB5DC" for i in range(7)]
    fig = go.Figure(go.Bar(
        x=HARI_ID, y=s["KM"], marker=dict(color=warna, line=dict(width=0)),
        text=[f"{v:.0f}" if v else "" for v in s["KM"]], textposition="outside",
        textfont=dict(size=11, color=MUTED), customdata=s["Akt"],
        hovertemplate="<b>%{x}</b><br>%{y:.1f} km · %{customdata} aktivitas<extra></extra>",
    ))
    fig.update_yaxes(title_text="Total KM", range=[0, max(s["KM"].max() * 1.25, 1)])
    return rapikan(fig, 300, legend=False)


def g_jam(resp: pd.DataFrame):
    ts = resp[COL_TS].dropna()
    if ts.empty:
        return None
    s = ts.dt.hour.value_counts().reindex(range(24), fill_value=0).sort_index()
    fig = go.Figure(go.Bar(
        x=[f"{h:02d}" for h in s.index], y=s.values,
        marker=dict(color=s.values, colorscale=[[0, "#D8DDF2"], [1, CYAN]],
                    line=dict(width=0)),
        hovertemplate="Pukul %{x}:00<br>%{y} submission<extra></extra>",
    ))
    fig.update_yaxes(title_text="Jumlah submit")
    fig.update_xaxes(title_text="Jam (WITA)")
    return rapikan(fig, 300, legend=False)


def g_sebaran(rekap: pd.DataFrame):
    d = rekap[rekap["Aktual KM"] > 0]["Pencapaian %"]
    if d.empty:
        return None
    tepi = [0, 25, 50, 75, 100, 1e9]
    label = ["0–25%", "25–50%", "50–75%", "75–100%", "≥100%"]
    warna = [ROSE, "#FB923C", AMBER, INDIGO, EMERALD]
    n = pd.cut(d, bins=tepi, labels=label, right=False).value_counts().reindex(label,
                                                                              fill_value=0)
    fig = go.Figure(go.Bar(
        x=label, y=n.values, marker=dict(color=warna, line=dict(width=0)),
        text=[f"{v}" if v else "" for v in n.values], textposition="outside",
        textfont=dict(size=11, color=MUTED),
        hovertemplate="<b>%{x}</b> dari target<br>%{y} peserta<extra></extra>",
    ))
    fig.update_yaxes(title_text="Jumlah peserta", range=[0, max(n.max() * 1.3, 1)])
    return rapikan(fig, 300, legend=False)


def g_status_divisi(rekap: pd.DataFrame):
    p = (rekap.pivot_table(index="Divisi", columns="Status", values="Peserta",
                           aggfunc="count", observed=False)
         .reindex(columns=STATUS_ORDER).fillna(0))
    p = p.loc[p.sum(axis=1).sort_values().index]
    fig = go.Figure()
    for s in STATUS_ORDER:
        fig.add_trace(go.Bar(
            x=p[s], y=p.index, name=f"{STATUS_EMOJI[s]} {s}", orientation="h",
            marker=dict(color=STATUS_COLOR[s], line=dict(width=0)),
            hovertemplate=f"<b>%{{y}}</b><br>{s}: %{{x:.0f}} orang<extra></extra>",
        ))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title_text="Jumlah karyawan")
    return rapikan(fig, max(290, 31 * len(p) + 95))


def g_divisi(rekap: pd.DataFrame):
    d = (rekap.groupby("Divisi", observed=False)
         .agg(KM=("Aktual KM", "sum"), N=("Peserta", "size"),
              A=("Aktual KM", lambda s: int((s > 0).sum())))
         .reset_index().sort_values("KM"))
    d["P"] = d["A"] / d["N"] * 100
    fig = go.Figure(go.Bar(
        x=d["KM"], y=d["Divisi"], orientation="h",
        marker=dict(color=[PALETTE[i % len(PALETTE)] for i in range(len(d))],
                    line=dict(width=0)),
        text=[f"{v:.0f} km" for v in d["KM"]], textposition="outside",
        textfont=dict(size=11, color=MUTED),
        customdata=np.stack([d["A"], d["N"], d["P"]], axis=-1),
        hovertemplate="<b>%{y}</b><br>%{x:.1f} km<br>"
                      "%{customdata[0]}/%{customdata[1]} aktif "
                      "(%{customdata[2]:.0f}%)<extra></extra>",
    ))
    fig.update_xaxes(range=[0, max(d["KM"].max() * 1.28, 1)])
    return rapikan(fig, max(280, 31 * len(d) + 80), legend=False)


def g_entitas(rekap: pd.DataFrame):
    d = (rekap.groupby("Entitas", observed=False)
         .agg(N=("Peserta", "size"), A=("Aktual KM", lambda s: int((s > 0).sum())))
         .reset_index())
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d["Entitas"], y=d["A"], name="Sudah submit",
        marker=dict(color=INDIGO, line=dict(width=0)),
        text=[f"{a}/{n}" for a, n in zip(d["A"], d["N"])], textposition="inside",
        textfont=dict(color="white", size=12),
        hovertemplate="<b>%{x}</b><br>Aktif %{y} orang<extra></extra>"))
    fig.add_trace(go.Bar(
        x=d["Entitas"], y=d["N"] - d["A"], name="Belum submit",
        marker=dict(color="#C4CAE6", line=dict(width=0)),
        hovertemplate="<b>%{x}</b><br>Belum %{y} orang<extra></extra>"))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Jumlah karyawan")
    return rapikan(fig, 300)


def g_jenis(rekap: pd.DataFrame):
    d = rekap[rekap["Aktual KM"] > 0]
    if d.empty:
        return None
    g = (d.groupby("Jenis").agg(N=("Peserta", "size"), KM=("Aktual KM", "sum"),
                                P=("Pencapaian %", "mean"))
         .reset_index().sort_values("KM", ascending=False))
    fig = go.Figure(go.Bar(
        x=g["Jenis"], y=g["KM"],
        marker=dict(color=[PALETTE[i % len(PALETTE)] for i in range(len(g))],
                    line=dict(width=0)),
        text=[f"{v:.0f} km" for v in g["KM"]], textposition="outside",
        textfont=dict(size=11, color=MUTED),
        customdata=np.stack([g["N"], g["P"]], axis=-1),
        hovertemplate="<b>%{x}</b><br>%{y:.1f} km · %{customdata[0]} peserta"
                      "<br>Rata-rata %{customdata[1]:.0f}% target<extra></extra>",
    ))
    fig.update_yaxes(title_text="Total KM", range=[0, g["KM"].max() * 1.28])
    return rapikan(fig, 300, legend=False)


def g_heatmap(resp: pd.DataFrame, start, end, n: int = 20):
    p = resp.pivot_table(index="Nama", columns="Tanggal", values=COL_KM, aggfunc="sum")
    if p.empty:
        return None
    p = p.loc[p.sum(axis=1).nlargest(n).index]
    p = p.reindex(columns=pd.date_range(start, end, freq="D"))
    p = p.loc[p.sum(axis=1).sort_values().index]
    fig = go.Figure(go.Heatmap(
        z=p.values, x=[d.strftime("%d %b") for d in p.columns], y=p.index,
        colorscale=[[0, "#EEF0FC"], [.35, "#A5B4FC"], [.7, INDIGO], [1, VIOLET]],
        xgap=3, ygap=3, hoverongaps=False,
        colorbar=dict(title="KM", thickness=10, len=.8, outlinewidth=0),
        hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2f} km<extra></extra>",
    ))
    return rapikan(fig, max(300, 25 * len(p) + 105), legend=False)


# ---------------------------------------------------------------------------
# Pemuatan data (otomatis, tanpa pilihan di UI)
# ---------------------------------------------------------------------------

def _secret(path: str, default=None):
    try:
        node = st.secrets
        for k in path.split("."):
            if k not in node:
                return default
            node = node[k]
        return node
    except Exception:  # noqa: BLE001
        return default


def ambil_data():
    """Baca Google Sheet: pakai service account kalau ada, kalau tidak CSV export."""
    sid = str(_secret("gsheet.sheet_id", DEFAULT_SHEET_ID))
    if HAS_GSPREAD and _secret("gcp_service_account") is not None:
        return load_gsheet_sa(
            sid,
            str(_secret("gsheet.worksheet_responses", DEFAULT_WS_RESP)),
            str(_secret("gsheet.worksheet_roster", DEFAULT_WS_ROSTER) or "") or None,
            st.secrets["gcp_service_account"],
        ), "service account"
    return load_gsheet_csv(
        sid,
        str(_secret("gsheet.gid_responses", DEFAULT_GID_RESP)),
        str(_secret("gsheet.gid_roster", "") or "") or None,
    ), "CSV export"


def gerbang_akses() -> bool:
    """Halaman kata sandi bersama. Dilewati kalau [auth].password kosong."""
    sandi = str(_secret("auth.password", "") or "")
    if not sandi or st.session_state.get("_akses_ok"):
        return True

    _, mid, _ = st.columns([1, 1.15, 1])
    with mid:
        st.markdown(
            f'<div style="margin-top:10vh"></div>'
            f'<div class="hero"><h1>{APP_TITLE}</h1>'
            f'<p>{APP_SUB}</p></div><div style="height:1.1rem"></div>',
            unsafe_allow_html=True)
        with st.form("login"):
            masuk = st.text_input("Kata sandi", type="password",
                                  label_visibility="collapsed",
                                  placeholder="Masukkan kata sandi")
            kirim = st.form_submit_button("Masuk", width="stretch", type="primary")
        if kirim:
            if hmac.compare_digest(masuk, sandi):
                st.session_state["_akses_ok"] = True
                st.session_state.pop("_gagal", None)
                st.rerun()
            else:
                st.session_state["_gagal"] = st.session_state.get("_gagal", 0) + 1
        if st.session_state.get("_gagal"):
            st.error(f"Kata sandi salah. Percobaan ke-{st.session_state['_gagal']}.",
                     icon="🔒")
        st.caption("Hubungi HRGA / IT kalau belum punya akses.")
    return False


# ---------------------------------------------------------------------------
# Halaman
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🏃", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)

    if not gerbang_akses():
        return

    try:
        (resp_all, roster_all), mode = ambil_data()
    except Exception as e:  # noqa: BLE001
        st.markdown(f'<div class="hero"><h1>{APP_TITLE}</h1><p>{APP_SUB}</p></div>',
                    unsafe_allow_html=True)
        st.error(f"Gagal memuat Google Sheet: {e}", icon="⚠️")
        st.info(
            "Periksa **App settings → Secrets**: `[gsheet] sheet_id`, nama tab, dan "
            "kredensial `[gcp_service_account]`. Kalau memakai CSV export, sheet harus "
            "di-share *Anyone with the link → Viewer*.", icon="🔧")
        return

    periodes = (resp_all[["Periode", "Periode Label"]].dropna()
                .drop_duplicates().sort_values("Periode", ascending=False))
    if periodes.empty:
        st.error("Tidak ada periode yang bisa dibaca dari sheet.", icon="⚠️")
        return

    # ---------------- filter di halaman utama ----------------
    f1, f2, f3 = st.columns([1.5, 2.6, 1.1])
    with f1:
        pilih = st.selectbox("Periode", periodes["Periode Label"].tolist(), index=0)
    periode = periodes.loc[periodes["Periode Label"] == pilih, "Periode"].iloc[0]
    berjalan, total_hari, start, end = periode_progress(periode)
    ratio = berjalan / total_hari if total_hari else 0.0
    sisa_hari = max(total_hari - berjalan, 0)

    ent_opsi = sorted(roster_all["Entitas"].unique())
    with f2:
        ent = st.segmented_control("Entitas", ent_opsi, default=ent_opsi,
                                   selection_mode="multi") or ent_opsi
    with f3:
        st.markdown('<div style="height:1.72rem"></div>', unsafe_allow_html=True)
        if st.button("🔄 Muat ulang", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    div_opsi = sorted(roster_all["Divisi"].unique())
    div = st.pills("Divisi", div_opsi, default=div_opsi,
                   selection_mode="multi") or div_opsi

    with st.expander("⚙️ Pengaturan lanjutan"):
        c1, c2 = st.columns(2)
        target_default = c1.number_input(
            "Target default untuk yang belum submit (km)", 1.0, 100.0, 7.0, 1.0,
            help="Dipakai karena kategori peserta belum diketahui sebelum submit pertama.")
        top_n = c2.slider("Jumlah peserta di leaderboard", 5, 40, 15)
        st.caption(f"Sumber data: Google Sheet via {mode} · cache 5 menit. "
                   f"Ambang On Track: {ratio * 100:.0f}% dari target bulanan.")
        if _secret("auth.password") and st.button("Keluar"):
            st.session_state.pop("_akses_ok", None)
            st.rerun()

    roster = roster_all[roster_all["Entitas"].isin(ent)
                        & roster_all["Divisi"].isin(div)].copy()
    resp = resp_all[(resp_all["Periode"] == periode)
                    & resp_all["Peserta"].isin(set(roster["Peserta"]))].copy()
    rekap = build_rekap(resp, roster, ratio, target_default)

    # ---------------- hero ----------------
    now = datetime.now(WITA)
    st.markdown(
        f'<div class="hero"><h1>{APP_TITLE}</h1><p>{APP_SUB}</p>'
        f'<div class="tags"><span class="tag">📅 {pilih}</span>'
        f'<span class="tag">⏱️ Hari ke-{berjalan} dari {total_hari}</span>'
        f'<span class="tag">👥 {len(rekap)} karyawan</span>'
        f'<span class="tag">🕒 {now:%d %b %Y, %H:%M} WITA</span></div>'
        f'<div class="track"><div style="width:{ratio * 100:.1f}%"></div></div></div>',
        unsafe_allow_html=True)
    st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)

    if rekap.empty:
        st.warning("Tidak ada data untuk kombinasi filter ini.", icon="🔍")
        return

    r = hitung_ringkasan(rekap, ratio)

    # ---------------- KPI ----------------
    with aman("Kartu KPI"):
        k = st.columns(5)
        k[0].markdown(kartu_kpi(
            "Partisipasi", f"{r['aktif']}<small>/{r['n']}</small>",
            f"{r['partisipasi']:.0f}% karyawan sudah submit", "👥", INDIGO,
            r["partisipasi"]), unsafe_allow_html=True)
        k[1].markdown(kartu_kpi(
            "Total Jarak", f"{r['total_km']:,.0f}<small> km</small>",
            f"dari target kolektif {r['total_target']:,.0f} km", "🏃", CYAN,
            r["progres_km"]), unsafe_allow_html=True)
        k[2].markdown(kartu_kpi(
            "Capai Target", f"{r['tercapai']}<small>/{r['n']}</small>",
            f"{r['pct_tercapai']:.0f}% dari karyawan terpilih", "🏆", EMERALD,
            r["pct_tercapai"]), unsafe_allow_html=True)
        wp = EMERALD if r["pace_pct"] >= 100 else (AMBER if r["pace_pct"] >= 70 else ROSE)
        k[3].markdown(kartu_kpi(
            "Pace vs Ideal", f"{r['pace_pct']:.0f}<small>%</small>",
            f"pace ideal hari ini {r['pace_ideal']:,.0f} km", "⚡", wp,
            min(r["pace_pct"], 100)), unsafe_allow_html=True)
        proy = r["proyeksi"] / r["total_target"] * 100 if r["total_target"] else 0
        wr = EMERALD if proy >= 100 else (AMBER if proy >= 70 else ROSE)
        k[4].markdown(kartu_kpi(
            "Proyeksi Akhir Bulan", f"{r['proyeksi']:,.0f}<small> km</small>",
            f"{proy:.0f}% target · {r['aktivitas']} aktivitas tercatat", "🎯", wr,
            min(proy, 100)), unsafe_allow_html=True)

    # ---------------- insight ----------------
    with aman("Kartu insight"):
        ins = susun_insight(rekap, resp, r, sisa_hari)
        if ins:
            st.markdown('<div style="height:.7rem"></div>', unsafe_allow_html=True)
            cols = st.columns(len(ins))
            for col, d in zip(cols, ins):
                col.markdown(kartu_insight(d), unsafe_allow_html=True)

    st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)

    t1, t2, t3, t4, t5 = st.tabs(
        ["Ringkasan", "Leaderboard", "Tren & Pola", "Breakdown", "Tindak Lanjut"])

    # ---------------- ringkasan ----------------
    with t1, aman("Ringkasan"):
        podium = rekap[rekap["Aktual KM"] > 0].nlargest(3, "Aktual KM")
        if len(podium) >= 3:
            judul("Podium Periode Ini")
            pc = st.columns(3)
            for col, (medali, warna), (_, row) in zip(
                    pc, [("🥇", "#A16207"), ("🥈", "#475569"), ("🥉", "#9A3412")],
                    podium.iterrows()):
                col.markdown(kartu_podium(
                    medali, row["Nama"], row["Aktual KM"],
                    f"{row['Pencapaian %']:.0f}% target · {int(row['Total Aktivitas'])} aktivitas",
                    warna), unsafe_allow_html=True)
            st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)

        a, b = st.columns([1, 1.4])
        with a:
            judul("Status Pencapaian", f"On Track = minimal {ratio * 100:.0f}% target")
            st.plotly_chart(g_donat_status(rekap), width="stretch")
        with b:
            judul("Status per Divisi", "Komposisi karyawan di tiap divisi")
            st.plotly_chart(g_status_divisi(rekap), width="stretch")

        belum = int((rekap["Status"] == "Belum Mulai").sum())
        tert = int((rekap["Status"] == "Tertinggal").sum())
        if belum or tert:
            st.markdown(
                f'<div class="note warn"><b>Perlu tindak lanjut.</b> {belum} karyawan '
                f'belum submit sama sekali dan {tert} tertinggal dari pace ideal. '
                f'Sisa {sisa_hari} hari di periode ini — daftar lengkap ada di tab '
                f'<b>Tindak Lanjut</b>.</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="note ok"><b>Semua karyawan on track atau sudah mencapai '
                'target.</b> Tidak ada yang perlu di-follow-up periode ini.</div>',
                unsafe_allow_html=True)

        a, b = st.columns(2)
        with a:
            judul("Sebaran Pencapaian", "Berapa banyak peserta di tiap rentang target")
            f = g_sebaran(rekap)
            st.plotly_chart(f, width="stretch") if f else st.info("Belum ada aktivitas.")
        with b:
            judul("Kontribusi per Jenis Aktivitas")
            f = g_jenis(rekap)
            st.plotly_chart(f, width="stretch") if f else st.info("Belum ada aktivitas.")

    # ---------------- leaderboard ----------------
    with t2, aman("Leaderboard"):
        judul("Peringkat Peserta",
              f"Top {top_n} berdasarkan jarak · warna batang = persentase target")
        f = g_leaderboard(rekap, top_n)
        st.plotly_chart(f, width="stretch") if f else st.info(
            "Belum ada peserta yang submit pada periode ini.")

        cari = st.text_input("Cari nama", placeholder="Ketik nama karyawan…",
                             label_visibility="collapsed")
        board = rekap[rekap["Aktual KM"] > 0].copy()
        board.insert(0, "#", range(1, len(board) + 1))
        if cari.strip():
            board = board[board["Nama"].str.contains(cari.strip(), case=False, na=False)]
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
                    "Pencapaian", format="%.0f%%", min_value=0, max_value=100)})

    # ---------------- tren ----------------
    with t3, aman("Tren & Pola"):
        judul("Tren Aktivitas Harian",
              "Batang = jarak per hari · area = akumulasi periode berjalan")
        if resp.empty:
            st.info("Belum ada aktivitas tercatat pada periode ini.")
        else:
            st.plotly_chart(
                g_tren(resp, start, end, r["total_target"] / total_hari if total_hari else None),
                width="stretch")

            harian = resp.groupby("Tanggal")[COL_KM].sum()
            m = st.columns(4)
            m[0].metric("Hari dengan aktivitas", f"{harian.size} / {berjalan}")
            m[1].metric("Hari terproduktif", f"{harian.idxmax():%d %b}",
                        f"{harian.max():.1f} km")
            m[2].metric("Rata-rata per hari kalender",
                        f"{harian.sum() / berjalan:.1f} km" if berjalan else "-")
            m[3].metric("Rata-rata per aktivitas", f"{resp[COL_KM].mean():.2f} km")

            st.markdown('<div style="height:.6rem"></div>', unsafe_allow_html=True)
            a, b = st.columns(2)
            with a:
                judul("Pola Hari dalam Seminggu", "Kapan karyawan paling banyak bergerak")
                f = g_hari(resp)
                if f:
                    st.plotly_chart(f, width="stretch")
            with b:
                judul("Jam Submit", "Distribusi waktu pengisian form")
                f = g_jam(resp)
                st.plotly_chart(f, width="stretch") if f else st.info(
                    "Kolom Timestamp tidak tersedia.")

            judul("Konsistensi Peserta",
                  f"Jarak harian · top {min(20, resp['Nama'].nunique())} peserta")
            f = g_heatmap(resp, start, end)
            if f:
                st.plotly_chart(f, width="stretch")

    # ---------------- breakdown ----------------
    with t4, aman("Breakdown"):
        a, b = st.columns(2)
        with a:
            judul("Total Jarak per Divisi")
            st.plotly_chart(g_divisi(rekap), width="stretch")
        with b:
            judul("Partisipasi per Entitas")
            st.plotly_chart(g_entitas(rekap), width="stretch")

        judul("Ringkasan Divisi")
        g = (rekap.groupby("Divisi", observed=False)
             .agg(Karyawan=("Peserta", "size"),
                  Aktif=("Aktual KM", lambda s: int((s > 0).sum())),
                  Tercapai=("Status", lambda s: int((s == "Tercapai").sum())),
                  **{"Total KM": ("Aktual KM", "sum"),
                     "Rata2 Pencapaian %": ("Pencapaian %", "mean")}).reset_index())
        g["Partisipasi %"] = g["Aktif"] / g["Karyawan"] * 100
        st.dataframe(
            g.sort_values("Total KM", ascending=False), hide_index=True, width="stretch",
            column_config={
                "Total KM": st.column_config.NumberColumn(format="%.1f km"),
                "Rata2 Pencapaian %": st.column_config.NumberColumn(format="%.0f%%"),
                "Partisipasi %": st.column_config.ProgressColumn(
                    format="%.0f%%", min_value=0, max_value=100)})

        judul("Perbandingan Entitas")
        g2 = (rekap.groupby("Entitas", observed=False)
              .agg(Karyawan=("Peserta", "size"),
                   Aktif=("Aktual KM", lambda s: int((s > 0).sum())),
                   Tercapai=("Status", lambda s: int((s == "Tercapai").sum())),
                   **{"Total KM": ("Aktual KM", "sum"),
                      "Total Aktivitas": ("Total Aktivitas", "sum")}).reset_index())
        g2["Partisipasi %"] = g2["Aktif"] / g2["Karyawan"] * 100
        g2["KM per Karyawan"] = g2["Total KM"] / g2["Karyawan"]
        st.dataframe(
            g2, hide_index=True, width="stretch",
            column_config={
                "Total KM": st.column_config.NumberColumn(format="%.1f km"),
                "KM per Karyawan": st.column_config.NumberColumn(format="%.2f km"),
                "Partisipasi %": st.column_config.ProgressColumn(
                    format="%.0f%%", min_value=0, max_value=100)})

    # ---------------- tindak lanjut ----------------
    with t5, aman("Tindak Lanjut"):
        judul("Daftar Tindak Lanjut",
              "Karyawan yang perlu diingatkan sebelum periode berakhir")
        fu = rekap[rekap["Status"].isin(["Belum Mulai", "Tertinggal"])].copy()
        fu = fu.sort_values(["Status", "Sisa KM"], ascending=[True, False])
        if fu.empty:
            st.success("Tidak ada karyawan yang perlu di-follow-up. 🎉")
        else:
            fu["KM/hari agar tercapai"] = fu["Sisa KM"] / max(sisa_hari, 1)
            st.dataframe(
                fu[["Nama", "Entitas", "Jabatan", "Divisi", "Status", "Aktual KM",
                    "Target KM", "Sisa KM", "KM/hari agar tercapai",
                    "Aktivitas Terakhir"]],
                hide_index=True, width="stretch",
                column_config={
                    "Aktual KM": st.column_config.NumberColumn(format="%.2f km"),
                    "Target KM": st.column_config.NumberColumn(format="%.0f km"),
                    "Sisa KM": st.column_config.NumberColumn(format="%.2f km"),
                    "KM/hari agar tercapai": st.column_config.NumberColumn(format="%.2f km"),
                    "Aktivitas Terakhir": st.column_config.DateColumn(format="DD MMM YYYY")})
            st.download_button(
                "⬇️ Unduh daftar tindak lanjut (CSV)",
                fu.to_csv(index=False).encode("utf-8"),
                file_name=f"follow_up_{pilih.replace(' ', '_')}.csv", mime="text/csv")

        judul("Verifikasi Data", "Entri yang sebaiknya dicek sebelum rekap dikunci")
        anom = find_anomali(resp, periode)
        if anom.empty:
            st.markdown('<div class="note ok">Tidak ada anomali terdeteksi pada '
                        'periode ini.</div>', unsafe_allow_html=True)
        else:
            st.dataframe(anom, hide_index=True, width="stretch",
                         column_config={"Tanggal": st.column_config.DateColumn(
                             format="DD MMM YYYY")})

        judul("Log Aktivitas", "Seluruh submission pada periode terpilih")
        detail = resp[["Tanggal", "Nama", "Entitas", "Divisi", "Jenis", COL_KM,
                       COL_BUKTI, COL_TS]].sort_values(COL_TS, ascending=False)
        st.dataframe(
            detail, hide_index=True, width="stretch",
            column_config={
                "Tanggal": st.column_config.DateColumn(format="DD MMM YYYY"),
                COL_TS: st.column_config.DatetimeColumn("Waktu Submit",
                                                        format="DD MMM YYYY HH:mm"),
                COL_KM: st.column_config.NumberColumn("Jarak", format="%.2f km"),
                COL_BUKTI: st.column_config.LinkColumn("Bukti Strava",
                                                       display_text="Buka")})

        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Unduh rekap per karyawan (CSV)",
                           rekap.to_csv(index=False).encode("utf-8"),
                           file_name=f"rekap_{pilih.replace(' ', '_')}.csv",
                           mime="text/csv", width="stretch")
        d2.download_button("⬇️ Unduh log aktivitas (CSV)",
                           detail.to_csv(index=False).encode("utf-8"),
                           file_name=f"log_{pilih.replace(' ', '_')}.csv",
                           mime="text/csv", width="stretch")


if __name__ == "__main__":
    main()
