# Deploy DA ERP (DAHOST) ke VPS — sekali jalan

| Item | Nilai |
|---|---|
| Repo | https://github.com/pandeyoga/DAHOST (branch `main`) |
| VPS | Ubuntu 26.04 LTS · `187.77.116.148` |
| Domain | `dafashionerp.cloud` (+ `www` redirect) |
| SSL | Let's Encrypt via Caddy — **auto-renew**, email `pk.yogaswastika@gmail.com` |
| Stack | Docker Compose: MongoDB 7 · FastAPI · React (nginx) · Caddy |
| Login awal | `admin@garment.com` / `Admin@123` (di-seed otomatis oleh backend — segera ganti) |

## 0. DNS (lakukan lebih dulu, di panel domain)

```
A   dafashionerp.cloud        187.77.116.148
A   www.dafashionerp.cloud    187.77.116.148
```
Jika pakai Cloudflare: mode **DNS only** (awan abu-abu), bukan Proxied.

## 1. Kode untuk terminal VPS

```bash
ssh root@187.77.116.148
```

**Opsi A — folder `deploy/` sudah ada di repo DAHOST:**
```bash
apt-get update -y && apt-get install -y git
git clone https://github.com/pandeyoga/DAHOST.git /opt/dahost
bash /opt/dahost/deploy/install_vps.sh
```

**Opsi B — kirim skrip langsung (repo belum punya `deploy/`):**
```bash
# dari laptop:
scp deploy/install_vps.sh root@187.77.116.148:/root/
# di VPS:
bash /root/install_vps.sh
```
(atau `nano /root/install_vps.sh`, tempel isi skrip, simpan, lalu `bash /root/install_vps.sh`).

Skrip mandiri: ia meng-clone repo ke `/opt/dahost`, membuat sendiri semua berkas Docker/Caddy,
membuat `deploy/.env` (JWT_SECRET acak, **tanpa variabel Emergent**), build, jalankan, tunggu
`/api/health`, tunggu HTTPS, pasang cron backup 02:00 WIB.

Nilai bawaan sudah `dafashionerp.cloud` / `pk.yogaswastika@gmail.com`. Untuk domain lain:
```bash
DOMAIN=lain.com ACME_EMAIL=x@y.com bash install_vps.sh
```

## 2. Kenapa aman dari "emergent lib"

* `requirements.txt` difilter di dalam image: baris `emergentintegrations` dan `litellm` **dibuang**.
* `backend/routes/marketing_ai_content_tools.py` mengimpor `emergentintegrations` di level modul → tanpa
  penanganan backend **gagal start**. Skrip memasang **stub** kecil (`deploy/emergent_stub/`) yang hanya
  menyediakan kelas `OpenAIImageGeneration`; fitur AI-image akan mengembalikan pesan "tidak tersedia",
  modul lain tidak terpengaruh. `emergentintegrations.llm.chat` sengaja tidak di-stub sehingga `ai_llm.py`
  memakai jalur Anthropic langsungnya (opsional, isi `ANTHROPIC_API_KEY` bila ingin fitur AI).
* `@emergentbase/visual-edits` (devDependency dari aset Emergent) dihapus sebelum `yarn install`.
* `deploy/.env` diverifikasi: skrip berhenti bila ada variabel `EMERGENT*`.
* `backend/.env` & `frontend/.env` tidak dipakai; semua env dari `docker-compose.yml` (`MONGO_URL`,
  `DB_NAME`, `JWT_SECRET`, `CORS_ORIGINS`, `REACT_APP_BACKEND_URL`, `WEBAUTHN_*`, `ALLOW_DEMO_SEED=false`).

## 3. Operasional

```bash
bash /opt/dahost/deploy/update.sh                    # tarik kode terbaru + rebuild + restart (data aman)
cd /opt/dahost/deploy && docker compose ps           # status
cd /opt/dahost/deploy && docker compose logs -f backend
cd /opt/dahost/deploy && docker compose logs -f caddy   # status sertifikat SSL
bash /opt/dahost/deploy/backup.sh                    # backup manual → deploy/backups/
bash /opt/dahost/deploy/backup.sh restore deploy/backups/<file>.archive.gz
REGEN=1 bash /opt/dahost/deploy/install_vps.sh       # tulis ulang berkas deploy yang dibuat skrip
```

Volume Docker: `mongo_data` (database), `uploads` (`/app/uploads`), `backups` (`/app/backups`),
`caddy_data` (sertifikat). `docker compose down` **tanpa** `-v` tidak menghapus data.

## 4. Catatan

* Jangan "Save to GitHub" dari sesi Emergent ini ke repo DAHOST (isi `/app` di sesi ini adalah template
  kosong). Cukup salin folder `deploy/` ke repo DAHOST bila ingin skrip ikut ter-version.
* Skrip ini **belum dijalankan/diverifikasi** di VPS (sesuai permintaan). Bila build gagal, kirim 80 baris
  terakhir output — titik rawan yang sudah diberi pengaman: pin pip yang tidak tersedia (fallback per paket),
  RAM kecil saat build React (swap 3GB otomatis bila RAM < 3.5GB), DNS belum propagasi (Caddy retry otomatis).
