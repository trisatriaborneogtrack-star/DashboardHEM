# Deploy ke Streamlit Community Cloud

## ⚠️ Baca ini dulu

Dashboard ini menampilkan **nama karyawan, NIK, dan jabatan** — data pribadi.
Streamlit Community Cloud menurunkan hak akses app dari repo GitHub-nya: repo publik →
**app publik dan bisa terindeks mesin pencari**. Jadi:

- **Repo GitHub harus PRIVATE**, supaya app-nya ikut private
- Community Cloud hanya mengizinkan **satu private app** per akun — kalau slot itu sudah
  terpakai app lain, app baru dari repo private tidak bisa dideploy sampai app lama
  dijadikan publik atau dihapus
- **Jangan pernah commit** file `.xlsx`/`.csv` data karyawan atau JSON service account.
  `.gitignore` di repo ini sudah memblokir keduanya

---

## 1. Siapkan repo

Isi repo (semuanya sudah ada di folder ini):

```
.
├── app.py
├── requirements.txt
├── .gitignore
├── DEPLOY.md
├── README.md
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example     ← contoh saja, yang asli JANGAN di-commit
```

```bash
cd folder-ini
git init
git add .
git commit -m "feat: dashboard HEMP 2026"
git branch -M main
git remote add origin https://github.com/<user>/hemp-dashboard.git
git push -u origin main
```

Buat repo-nya di GitHub sebagai **Private**.

Cek sebelum push:

```bash
git status --porcelain          # pastikan tidak ada .xlsx / .json ikut
git ls-files | grep -Ei '\.(xlsx|csv|json)$'   # harus kosong
```

---

## 2. Service account Google (biar sheet tetap private)

Tanpa ini, app cuma bisa mode upload manual — dan di cloud, file upload hilang tiap
session, jadi harus upload ulang terus. Service account bikin app baca sheet langsung
tanpa sheet-nya perlu dibuka ke publik.

1. Buka **console.cloud.google.com** → buat project (atau pakai yang ada)
2. **APIs & Services → Library** → aktifkan **Google Sheets API** dan **Google Drive API**
3. **APIs & Services → Credentials → Create credentials → Service account**
   - Nama bebas, mis. `dashboard-hemp`. Role tidak perlu diisi
4. Klik service account yang baru dibuat → tab **Keys → Add key → Create new key → JSON**
   → file JSON ter-download
5. Buka file JSON, salin nilai `client_email`
   (bentuknya `dashboard-hemp@<project>.iam.gserviceaccount.com`)
6. Di Google Sheet HEMP: **Share** → tempel email itu → beri akses **Viewer** → Send

Sheet tetap private. Yang dikasih akses cuma robot service account-nya.

---

## 3. Deploy

1. Buka **https://share.streamlit.io/new**
2. Isi:
   - **Repository**: `<user>/hemp-dashboard`
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - **App URL**: pilih subdomain, mis. `hemp-tpb-gtn`
3. Klik **Advanced settings → Secrets**, tempel isi berikut (ambil nilainya dari file
   JSON tadi):

```toml
[gsheet]
sheet_id = "1I30t7uLOzwBMVyq0k-Rfy1NTzGUFLbT9v37XeFjKbF0"
worksheet_responses = "Form Responses 1"
worksheet_roster = "Sheet1"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = """-----BEGIN PRIVATE KEY-----
...
-----END PRIVATE KEY-----
"""
client_email = "dashboard-hemp@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

   Di **Advanced settings** juga pilih **Python 3.11** atau 3.12.

4. **Deploy**. Build pertama sekitar 2–5 menit.

Kalau secrets terisi benar, sidebar otomatis menampilkan opsi
**"Google Sheet (service account)"** sebagai default dan langsung memuat data.

---

## 4. Atur siapa yang boleh lihat

App → **Manage app → Settings → Sharing**. Tambahkan email tim HR/management ke daftar
viewer satu per satu (belum ada opsi allow-list per domain). Mereka login pakai Google
atau lewat magic link yang dikirim ke email.

---

## Kalau ada masalah

| Gejala | Penyebab & solusi |
|---|---|
| `SpreadsheetNotFound` | Sheet belum di-share ke `client_email` service account, atau `sheet_id` salah |
| `APIError 403 ... has not been used` | Google Sheets API / Drive API belum diaktifkan di project |
| `WorksheetNotFound` | Nama tab di secrets tidak sama persis dengan di Google Sheet (case-sensitive, termasuk spasi) |
| Opsi service account tidak muncul di sidebar | Secrets belum tersimpan, atau blok `[gcp_service_account]` salah nama |
| `No module named 'gspread'` | `requirements.txt` belum ke-push — cek isinya lalu **Reboot app** |
| Error parsing private key | `private_key` harus pakai triple-quote `"""` dan baris-barisnya utuh |
| App "zzz / waking up" | Normal: app tidur setelah ~12 jam tanpa traffic, hidup lagi otomatis saat dibuka |
| Data tidak berubah padahal sheet sudah update | Cache 5 menit — klik **🔄 Refresh data** di sidebar |
| `MemoryError` / app restart | Limit ~1 GB. Untuk skala data ini seharusnya aman |

**Update dashboard:** cukup `git push` — Community Cloud rebuild otomatis.
Kalau perubahan menyentuh `requirements.txt`, lakukan **Reboot app** dari menu Manage app.

---

## Alternatif tanpa service account

Kalau setup Google Cloud terasa berat, mode **"Google Sheet (link publik)"** juga
tersedia — tapi sheet harus di-share *Anyone with the link → Viewer*. Untuk data yang
berisi nama dan NIK karyawan, ini tidak disarankan.
