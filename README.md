# DA37 ERP — CV. Dewi Aditya

ERP full-stack garmen (produksi internal + maklon/CMT, gudang, keuangan/akunting, HRIS, marketing, portal vendor/klien).
Stack: **FastAPI + MongoDB (Motor)** · **React 19 (CRA/craco, static bundle)** · Caddy/Docker di VPS.

> **BAHASA:** selalu berkomunikasi dengan user dalam **Bahasa Indonesia**.
> **DATA = data klien nyata** (`seed/DA_SEED_GOLIVE.archive.gz`), bukan demo — `ALLOW_DEMO_SEED=false`.

## Mulai di sini (agent / developer baru)
| Urutan | Dokumen | Isi |
|---|---|---|
| 1 | `AGENT_QUICKSTART.md` | Setup mesin: clone → `backend/.env` (+`JWT_SECRET`) → deps → restore seed go-live → `yarn build` |
| 2 | `HANDOFF.md` | Penunjuk pekerjaan berikutnya + status singkat |
| 3 | `memory/PLAN_PERBAIKAN_AUDIT.md` | Rencana perbaikan hasil audit (FASE 0–5) + tabel status §F |
| 4 | `memory/PRD.md` | Log sesi terkini (paling atas) & riwayat produk |
| 5 | `DOCS_INDEX.md` | Peta seluruh dokumen aktif vs arsip |
| 6 | `AGENT_DEVELOPMENT_RULES.md`, `memory/ENGINEERING_GUARDRAILS.md`, `design_guidelines.md` | Aturan teknik & desain |

Riwayat blok status lama README (2026-05 → 2026-09) dipindah ke **`docs/CHANGELOG_SESI.md`** (arsip, tidak diubah).

## Menjalankan (preview / lokal)
```bash
# env: backend/.env wajib MONGO_URL, DB_NAME, JWT_SECRET; opsional EMERGENT_LLM_KEY, ALLOW_SESSION_TOKEN_IN_QUERY (bawaan 1)
bash scripts/_setup_deps.sh                      # pip (melewati pin emergentintegrations/litellm)
cd frontend && yarn install --frozen-lockfile && cd ..
bash scripts/seed_golive_restore.sh --force      # data klien nyata → DB_NAME
cd backend && python ../scripts/seed_test_accounts.py   # akun uji uji.{role}@dewiaditya.id / Dewi@123
bash scripts/rebuild_frontend.sh                 # frontend = static bundle (JANGAN craco start)
sudo supervisorctl restart backend
```
Health: `GET /api/health`. Login superadmin: `admin@garment.com` / `Admin@123` (rate-limit 5 gagal/akun).
Kredensial uji: `memory/test_credentials.md`, karyawan nyata: `memory/SEED_CREDENTIALS.md`.

## Verifikasi & gate
| Perintah | Isi |
|---|---|
| `bash scripts/gate.sh` (`--full`) | Gate integritas data + regresi (receipt: `memory/GATE_RECEIPT.md`) |
| `python3 scripts/audit_authz.py --gate` | T-01: endpoint tulis tanpa gerbang tidak boleh naik (baseline 0) |
| `python3 scripts/check_collection_writers.py --gate` | T-03/T-17: koleksi dibaca-tanpa-penulis (baseline 21) |
| `python3 scripts/check_unbounded_queries.py --gate` | T-21: `to_list(None)` tidak boleh naik |
| `cd backend && python -m pytest tests/unit -n 0 -q` | Uji hermetik `core/*` + `auth` (tanpa Mongo) |
| `cd backend && set -a && . .env && set +a && python ../tests/test_fase{1,2,23,3,4}_*.py` | Uji API per fase plan audit |
| `cd backend && python migrations/ensure_indexes.py` | Indeks Mongo idempoten (dipanggil `deploy/update.sh`; boot via `ENSURE_INDEXES=1`) |
| CI GitHub (`.github/workflows/ci.yml`) | ruff (F821/F811/F401/E9) · pytest unit · 3 gate statis · `yarn install --frozen-lockfile && yarn build` |

Uji frontend Jest **tidak ada** lagi di repo (klaim lama "204 uji" = arsip); uji FE = build CI.

## Struktur singkat
```
backend/      server.py (include_router + gerbang peran per router), routes/, core/ (logika SSOT), services/, migrations/, tests/unit/
frontend/     src/components/erp/** (modul per domain), build/ disajikan statis
scripts/      gate.sh, audit_authz.py, check_*.py, seed_*.sh/py, bootstrap.sh, rebuild_frontend.sh
tests/        test_fase*.py (API), legacy/ (skrip uji lama, termasuk legacy/backend_root/ dari akar backend/)
deploy/       docker-compose.yml, Caddyfile, update.sh, README_DEPLOY.md
memory/       PRD.md, PLAN_PERBAIKAN_AUDIT.md, test_credentials.md, dokumen analisis
docs/         CHANGELOG_SESI.md, PLAN_FASE*.md, user-guide/, archive/
```

## Konvensi wajib
- Semua endpoint diawali `/api`; URL/port/kredensial hanya dari `.env`.
- Peran eksternal (`vendor`, `cmt_vendor`, `buyer`, `klien_maklon`) ditolak di router internal lewat `dependencies=` di `server.py` (`core/authz.py`).
- Konstanta peran dari `core/roles.py` (`FINANCE_ROLES`, `APPROVER_ROLES`, …) — jangan tulis daftar peran lokal.
- Unduhan lewat `window.open`/`<a href>` memakai **download-token** (`POST /api/auth/download-token`, 5 menit, `aud=download`), bukan token sesi di query string.
- Setelah uji yang mengubah data: `bash scripts/seed_golive_restore.sh --force`.
