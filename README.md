# Healthy Employee Movement Program — Dashboard

Dashboard monitoring harian aktivitas olahraga karyawan TPB & GTN, dibangun dari
submission Google Form (Walking / Running + bukti Strava).

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Buka `http://localhost:8501`, lalu pilih sumber data di sidebar.

## Sumber data

**1. Upload file Excel** (default, paling aman)
Google Sheet → *File → Download → Microsoft Excel (.xlsx)* → upload di sidebar.
Sheet dideteksi otomatis: tab yang punya kolom `Timestamp` + `Jarak Tempuh Aktivitas (Km)`
dianggap sebagai form responses, tab lain yang punya `Nama Karyawan` dipakai sebagai
master karyawan.

**2. Google Sheet — service account** (dipakai saat deploy)
Sheet tetap private, cukup di-share ke email service account. Konfigurasi lewat
`st.secrets` (`[gsheet]` + `[gcp_service_account]`). Lihat `DEPLOY.md` untuk langkah
lengkapnya dan `.streamlit/secrets.toml.example` untuk formatnya.

**3. Google Sheet — link publik**
Sheet harus di-share **Anyone with the link → Viewer**. Isi Sheet ID dan GID tab.

Mode 2 dan 3 di-cache 5 menit — tekan **🔄 Refresh data** di sidebar untuk memuat ulang.
Mode service account membaca tanggal sebagai serial number, jadi kebal terhadap
perbedaan locale sheet (dd/mm vs mm/dd) — lebih andal daripada mode CSV.

## Struktur data yang diharapkan

Tab **Form Responses**:

| Kolom | Keterangan |
|---|---|
| `Timestamp` | waktu submit |
| `Nama Karyawan` | format `NAMA - (TPB.DDMMYYYY-NIK) - JABATAN` |
| `Kategori` | mis. `Running ( Berlari ), Target 15 Km/bulan` |
| `Tanggal Aktifitas` | tanggal aktivitas |
| `Jarak Tempuh Aktivitas (Km)` | angka |
| `Bulan Target` | mis. `Agustus 2026` |
| `Screenshot Aktivitas Strava` | link bukti |

Tab **master karyawan** (opsional tapi disarankan): minimal kolom `Nama Karyawan`
berisi seluruh roster. Tanpa tab ini, angka partisipasi hanya dihitung dari
karyawan yang sudah pernah submit — bukan dari total karyawan.

Yang di-derive otomatis dari string nama: **entitas** (TPB/GTN), **NIK**,
**tanggal bergabung**, **jabatan**, dan **divisi** (pengelompokan jabatan ada di
fungsi `map_divisi()` — sesuaikan kalau struktur organisasi berubah).
Target bulanan di-parse dari teks `Kategori`, jadi kalau target diubah di Google
Form, dashboard ikut menyesuaikan tanpa perlu edit kode.

## Logika status

Ambang *pace* dihitung proporsional terhadap hari berjalan di bulan tersebut
(zona waktu WITA):

```
pace_ideal = target_bulanan × (hari_berjalan / total_hari_bulan)
```

| Status | Kondisi |
|---|---|
| **Tercapai** | aktual ≥ target bulanan |
| **On Track** | aktual ≥ pace ideal |
| **Tertinggal** | 0 < aktual < pace ideal |
| **Belum Mulai** | belum ada submission |

Karyawan yang belum pernah submit belum ketahuan kategorinya, jadi targetnya
memakai nilai *Target default* di sidebar (default 7 km, mengikuti Walking).

## Isi dashboard

- **Ringkasan** — 5 KPI (partisipasi, total jarak, pencapaian target, pace vs ideal,
  jumlah aktivitas), donat status, status per divisi, partisipasi per entitas,
  kontribusi per jenis aktivitas
- **Leaderboard** — peringkat visual + tabel lengkap dengan progress bar pencapaian
- **Tren Harian** — jarak per hari, kumulatif vs garis pace ideal, heatmap konsistensi
- **Breakdown** — agregasi per divisi dan per entitas
- **Detail & Tindak Lanjut** — daftar follow-up berisi sisa KM dan **KM/hari yang
  dibutuhkan** agar target tercapai, panel verifikasi data, log aktivitas dengan
  link bukti Strava, dan tombol unduh CSV

## Panel verifikasi data

Dijalankan otomatis tiap periode, menandai: submit ganda di tanggal yang sama,
tanggal aktivitas di luar bulan target, jarak outlier (di atas Q3 + 3×IQR), dan
entri tanpa link screenshot. Berguna untuk dicek sebelum rekap bulanan dikunci.

## Deploy

Langkah lengkap ke Streamlit Community Cloud ada di **[DEPLOY.md](DEPLOY.md)**.

> Dashboard ini memuat nama, NIK, dan jabatan karyawan. Repo GitHub-nya **harus private**
> supaya app-nya ikut private, dan daftar viewer diatur dari App settings → Sharing.

Container mana pun juga bisa:

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```
