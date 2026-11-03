# Demo / simulasi di subdomain (mis. `demo.dafashionerp.cloud`)

Demo **terpisah total dari produksi**:

| | Produksi | Demo |
|---|---|---|
| Database | container `mongo`, DB `$DB_NAME` | container `mongo-demo`, DB `dahost_demo` (volume sendiri) |
| Rahasia login (JWT) | `deploy/.env` | `deploy/demo/.env` (dibuat otomatis, beda) |
| Unggahan / backup | volume `uploads`, `backups` | `demo_uploads`, `demo_backups` |
| Frontend | build untuk domain produksi | build sendiri untuk domain demo |

Yang dipakai bersama hanya **Caddy** (pintu HTTPS): ia membaca `deploy/caddy-sites/*.caddy`.

Pengamanan demo:
- **Kata sandi pintu (basic auth)** untuk membuka halaman. `/api` tidak memakai pintu karena header-nya dipakai login aplikasi.
- **Semua kata sandi akun diganti** saat data dimuat.
- Notifikasi WhatsApp/email dimatikan.
- AI nonaktif.
- `noindex` supaya tidak muncul di Google.

## Pasang (sekali)
1. DNS: tambah **A record** `demo` → IP VPS.
2. Di VPS jalankan `bash deploy/backup.sh && bash deploy/update.sh`, supaya Caddy membaca folder `caddy-sites`.
3. Pasang demo dengan `bash deploy/demo/demo.sh pasang demo.dafashionerp.cloud`.
   - Anda akan diminta nama dan kata sandi pintu.
   - Build butuh beberapa menit.
4. Kirim arsip data ke `deploy/demo/data/`, lalu jalankan `bash deploy/demo/demo.sh muat-data deploy/demo/data/<arsip>.archive.gz`.
   - Anda akan diminta kata sandi baru untuk semua akun demo.

## Sehari-hari
- `bash deploy/demo/demo.sh update` — demo ikut kode terbaru. Jalankan sesudah `deploy/update.sh`.
- `bash deploy/demo/demo.sh status`
- `bash deploy/demo/demo.sh muat-data <arsip>` — kembalikan data demo ke awal (data demo lama dihapus).
- `bash deploy/demo/demo.sh hapus` — hapus demo beserta datanya. Produksi tidak tersentuh.

`deploy/demo/.env`, `deploy/demo/data/`, dan `deploy/caddy-sites/*.caddy` tidak masuk git.
