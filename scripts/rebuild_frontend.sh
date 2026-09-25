#!/usr/bin/env bash
# =============================================================================
# rebuild_frontend.sh — rebuild the frontend static bundle & reload the server.
#
# WHY: This container is capped at 1 CPU core / 2GB RAM. We do NOT run the CRA
# dev server (it compiles ~567 files for ~5 min at 100% CPU and triggers a
# platform pod-restart loop). Instead we serve a prebuilt static bundle via
# frontend/static_server.js. Run this script after ANY change to frontend/src
# to make the change appear in the preview.
#
# See: /app/memory/PREVIEW_STABLE_MODE.md
# Usage: bash /app/scripts/rebuild_frontend.sh
# =============================================================================
set -uo pipefail
FE=/app/frontend
cd "$FE" || { echo "[rebuild] $FE not found"; exit 1; }

echo "[rebuild] $(date '+%T') building static bundle (nice -n 19, minify off, sourcemaps off)..."
echo "[rebuild] this takes a few minutes on 1 CPU core — the preview keeps serving the OLD build meanwhile."

# Simpan chunk build LAMA: tab yang masih memegang index.html lama tetap bisa memuat chunk-nya
# (mencegah "ChunkLoadError: Loading chunk … failed" sesaat setelah rebuild).
OLD_STATIC=""
if [ -d build/static ]; then OLD_STATIC=$(mktemp -d) && cp -r build/static/. "$OLD_STATIC"/; fi

if nice -n 19 yarn build > /tmp/fe_build.log 2>&1; then
  if [ -n "$OLD_STATIC" ]; then
    # hanya salin berkas yang TIDAK ada di build baru; buang chunk lama > 7 hari agar tidak menumpuk
    (cd "$OLD_STATIC" && find . -type f -mtime -7 | while read -r f; do [ -e "$FE/build/static/$f" ] || { mkdir -p "$FE/build/static/$(dirname "$f")"; cp -p "$f" "$FE/build/static/$f"; }; done)
    rm -rf "$OLD_STATIC"
    echo "[rebuild] chunk build lama dipertahankan (≤7 hari) untuk tab yang belum di-refresh."
  fi
  if [ -f build/index.html ] && grep -q 'text/javascript\|main\.\|static/js' build/index.html 2>/dev/null || [ -d build/static ]; then
    echo "[rebuild] build OK."
  else
    echo "[rebuild] build finished but output looks incomplete — check /tmp/fe_build.log"
  fi
  echo "[rebuild] reloading static server..."
  sudo supervisorctl restart frontend >/dev/null 2>&1
  sleep 3
  code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null)
  echo "[rebuild] DONE. frontend HTTP $code (200 = serving)"
else
  echo "[rebuild] BUILD FAILED — see /tmp/fe_build.log (last 20 lines):"
  tail -20 /tmp/fe_build.log
  echo "[rebuild] the previous build is still being served, so the preview is unaffected."
  exit 1
fi
