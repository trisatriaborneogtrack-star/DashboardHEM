# Healthy Employee Movement Program — Dashboard

Dashboard monitoring harian aktivitas olahraga karyawan TPB & GTN, dibangun dari
submission Google Form (Walking / Running + bukti Strava). Data dibaca langsung dari
Google Sheet, semua filter ada di halaman utama.

## Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Buka `http://localhost:8501`, lalu pilih sumber data di sidebar.

## Sumber data

Data dibaca **langsung dari Google Sheet**, dipilih otomatis tanpa opsi di UI:

1. Kalau `[gcp_service_account]` ada di `st.secrets` → **service account** (`gspread`).
   Sheet tetap private, cukup di-share ke email service account. Ini jalur yang
   disarankan.
2. Kalau tidak → **CSV export**. Sheet harus di-share *Anyone with the link → Viewer*.

Sheet ID dan nama tab diatur lewat `[gsheet]` di secrets; kalau kosong, dipakai nilai
default di `app.py`. Pada mode endpoint publik, tab master diambil lewat endpoint
`gviz` yang menerima **nama tab**, jadi gid-nya tidak perlu dicari manual.

**Tab master menentukan angka partisipasi.** Kalau tab itu gagal dibaca, roster hanya
berisi orang yang pernah submit — partisipasi jadi mendekati 100% dan karyawan yang
belum bergerak tidak muncul sama sekali. Dashboard mendeteksi kondisi ini dan
menampilkan peringatan; rinciannya ada di **⚙️ Pengaturan lanjutan → Diagnostik
sumber data**. Hasil dibaca dengan cache 5 menit — tombol **🔄 Muat ulang** di
baris filter memuat ulang paksa.

Mode service account membaca tanggal sebagai serial number, jadi kebal terhadap
perbedaan locale sheet (dd/mm vs mm/dd) — lebih andal daripada CSV export.

> `load_excel()` masih ada di `app.py` sebagai helper untuk pengujian dan debugging
> lokal, tapi tidak lagi terhubung ke UI.

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

## Tata letak

**Tanpa sidebar dan tanpa filter.** Seluruh karyawan selalu ditampilkan, supaya
angka partisipasi dan daftar "belum mulai" tidak pernah menyembunyikan siapa pun.
Kontrol yang tersisa:

- **Periode** — hanya muncul sebagai dropdown kalau sheet memuat lebih dari satu
  bulan; kalau cuma satu, ditampilkan sebagai label
- Tombol **🔄 Muat ulang**
- Expander **⚙️ Pengaturan lanjutan**: target default, info sumber data, tombol keluar

Di bawahnya: hero dengan progress bar periode → 5 kartu KPI → kartu insight otomatis
→ 5 tab.

## Isi dashboard

**KPI:** partisipasi, total jarak, capai target, pace vs ideal, dan **proyeksi akhir
bulan** (ekstrapolasi linear dari pace saat ini).

**Kartu insight otomatis:** divisi terdepan, peserta paling konsisten, hari paling
aktif dalam seminggu, dan jumlah karyawan yang belum mulai.

Perbandingan antar-entitas dan antar-divisi tetap tersedia di tab **Breakdown** —
sebagai informasi, bukan sebagai filter yang menyembunyikan data.

| Tab | Isi |
|---|---|
| **Ringkasan** | Podium 3 besar, donat status, status per divisi, sebaran pencapaian per rentang target, kontribusi per jenis aktivitas |
| **Status Karyawan** | Grafik 15 peserta teraktif + tabel **seluruh karyawan** (termasuk yang belum submit), dengan pencarian nama, progress bar, dan unduh CSV |
| **Tren & Pola** | Jarak harian + kumulatif vs pace ideal, pola hari dalam seminggu, distribusi jam submit, heatmap konsistensi |
| **Breakdown** | Agregasi per divisi dan per entitas |
| **Tindak Lanjut** | Daftar follow-up berisi sisa KM dan **KM/hari yang dibutuhkan**, panel verifikasi data, log aktivitas dengan link Strava, unduh CSV |

## Panel verifikasi data

Dijalankan otomatis tiap periode, menandai: submit ganda di tanggal yang sama,
tanggal aktivitas di luar bulan target, jarak outlier (di atas Q3 + 3×IQR), dan
entri tanpa link screenshot. Berguna untuk dicek sebelum rekap bulanan dikunci.

## Catatan pengembangan

- **Jangan pakai ekspresi telanjang.** `st.plotly_chart(f) if f else st.info(...)`
  ditangkap Streamlit magic, dan objek `DeltaGenerator` hasil kembaliannya dirender
  sebagai dokumentasi API ribuan baris di halaman. Pakai `tampil_grafik(fig, pesan)`.
  `[runner] magicEnabled = false` di `config.toml` jadi jaring pengaman kedua, dan
  `test/cek_magic.py` memeriksanya secara statis.
- **Warna cerah hanya untuk isian grafik.** Untuk teks, pakai varian `*_T`
  (`AMBER_T`, `EMERALD_T`, dst). Versi cerahnya berkontras 2–3:1 di latar putih —
  praktis tidak terbaca. Lihat `test/audit_kontras.py`.
- **Setiap panel dibungkus `aman()`** sehingga satu kegagalan tidak menghentikan
  seluruh halaman, dan traceback-nya tampil di tempat.
- **Tidak ada lapisan autentikasi di aplikasi.** Pembatasan akses sepenuhnya
  mengandalkan pengaturan sharing Streamlit Community Cloud.

## Deploy

Langkah lengkap ke Streamlit Community Cloud ada di **[DEPLOY.md](DEPLOY.md)**.

> Dashboard ini terbuka tanpa kata sandi. Kalau app di-set public di Streamlit,
> isinya bisa dilihat siapa pun dan terindeks mesin pencari. Untuk membatasi akses,
> set app jadi **private** dan daftarkan email penonton — lihat `DEPLOY.md`.

Container mana pun juga bisa:

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```
