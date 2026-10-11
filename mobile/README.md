# mobile/ — kerangka Expo, BELUM DIMULAI

Folder ini adalah kerangka `create-expo-app` bawaan (36 berkas) **tanpa satu pun panggilan ke `/api`**
ERP DA (audit T-26). Ia tidak dibangun, tidak di-deploy, dan tidak dipakai pengguna.

Bila aplikasi mobile benar-benar dimulai:
1. Pakai `REACT_APP_BACKEND_URL`/`EXPO_PUBLIC_API_URL` dari env, jangan hardcode.
2. Autentikasi memakai `POST /api/auth/login` (JWT) — sama dengan web.
3. Mulai dari layar absensi (`/api/rahaza/attendance/*`) dan Portal Saya (`/api/portal-saya/*`).

Sampai saat itu, folder ini boleh diabaikan (atau dihapus) tanpa memengaruhi sistem.
