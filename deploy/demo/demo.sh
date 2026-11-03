#!/usr/bin/env bash
# demo.sh — DEMO/SIMULASI di subdomain, TERPISAH dari produksi (database, rahasia login, uploads sendiri).
#   bash deploy/demo/demo.sh pasang demo.dafashionerp.cloud   → pertama kali: .env demo, kata sandi pintu, build, jalan
#   bash deploy/demo/demo.sh muat-data deploy/demo/data/<arsip>.archive.gz   → isi data demo (menimpa data demo lama)
#   bash deploy/demo/demo.sh update    → build ulang demo dengan kode terbaru (jalankan sesudah deploy/update.sh)
#   bash deploy/demo/demo.sh status
#   bash deploy/demo/demo.sh hapus     → hentikan & hapus demo beserta datanya (produksi tidak tersentuh)
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEMO_DIR="$APP_DIR/deploy/demo"
SITES_DIR="$APP_DIR/deploy/caddy-sites"
ENV_FILE="$DEMO_DIR/.env"
DC=(docker compose -f "$DEMO_DIR/docker-compose.yml" --env-file "$ENV_FILE")
PROD=(docker compose -f "$APP_DIR/deploy/docker-compose.yml" --env-file "$APP_DIR/deploy/.env")

die() { echo "!! $*" >&2; exit 1; }

reload_caddy() {
  "${PROD[@]}" exec -T caddy sh -c 'test -d /etc/caddy/sites' \
    || die "Caddy produksi belum membaca folder caddy-sites. Jalankan dulu: bash deploy/update.sh"
  "${PROD[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
  echo "==> Caddy dimuat ulang"
}

wait_backend() {
  echo -n "==> menunggu backend demo "
  for _ in $(seq 1 60); do
    if "${DC[@]}" exec -T backend-demo curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
      echo "OK"; return 0
    fi
    echo -n "."; sleep 4
  done
  "${DC[@]}" logs --tail=60 backend-demo; die "backend demo belum sehat"
}

indexes() {
  "${DC[@]}" exec -T backend-demo python migrations/ensure_indexes.py >/dev/null || echo "  ! ensure_indexes gagal" >&2
}

cmd="${1:-}"; shift || true
case "$cmd" in
  pasang)
    domain="${1:-}"
    [ -n "$domain" ] || die "pakai: bash deploy/demo/demo.sh pasang demo.dafashionerp.cloud"
    net="$(grep -s '^PROD_NETWORK=' "$ENV_FILE" | cut -d= -f2 || true)"
    docker network inspect "${net:-dahost_default}" >/dev/null 2>&1 \
      || die "jaringan produksi ${net:-dahost_default} tidak ada (produksi belum jalan?)"
    if [ ! -f "$ENV_FILE" ]; then
      umask 077
      printf 'DEMO_DOMAIN=%s\nDEMO_JWT_SECRET=%s\n' "$domain" "$(openssl rand -hex 32)" > "$ENV_FILE"
      echo "==> $ENV_FILE dibuat (rahasia JWT demo baru, beda dari produksi)"
    else
      sed -i "s|^DEMO_DOMAIN=.*|DEMO_DOMAIN=$domain|" "$ENV_FILE"
    fi
    read -rp "Nama pengguna kata sandi PINTU (mis. demo): " gate_user
    [[ "$gate_user" =~ ^[A-Za-z0-9_-]+$ ]] || die "nama pengguna pintu hanya huruf/angka/_/-"
    read -rsp "Kata sandi PINTU (min. 10 karakter): " gate_pw; echo
    [ ${#gate_pw} -ge 10 ] || die "kata sandi pintu terlalu pendek"
    hash="$(docker run --rm caddy:2-alpine caddy hash-password --plaintext "$gate_pw")"
    mkdir -p "$SITES_DIR"
    sed -e "s|__DOMAIN__|$domain|" -e "s|__USER__|$gate_user|" -e "s|__HASH__|$hash|" \
      "$DEMO_DIR/demo.caddy.template" > "$SITES_DIR/demo.caddy"
    echo "==> build & jalankan demo (frontend dibangun ulang untuk $domain — beberapa menit)"
    "${DC[@]}" up -d --build
    wait_backend; indexes; reload_caddy
    echo "SELESAI. Isi datanya: bash deploy/demo/demo.sh muat-data <arsip>"
    ;;
  muat-data)
    file="${1:-}"; [ -f "$file" ] || die "berkas arsip tidak ditemukan: $file"
    src="${SRC_DB:-dahost_erp}"
    echo "==> data demo lama DIHAPUS lalu diisi dari $file ($src → dahost_demo). Produksi tidak tersentuh."
    "${DC[@]}" exec -T mongo-demo mongosh --quiet dahost_demo --eval 'db.dropDatabase()' >/dev/null
    "${DC[@]}" exec -T mongo-demo mongorestore --archive --gzip --nsInclude="$src.*" \
      --nsFrom="$src.*" --nsTo="dahost_demo.*" < "$file"
    read -rsp "Kata sandi BARU untuk SEMUA akun demo (min. 12 karakter): " demo_pw; echo
    "${DC[@]}" exec -T -e DEMO_PASSWORD="$demo_pw" backend-demo python /app/scripts/demo_prepare.py --terapkan
    "${DC[@]}" restart backend-demo >/dev/null
    wait_backend; indexes
    echo "SELESAI. Buka https://$(grep '^DEMO_DOMAIN=' "$ENV_FILE" | cut -d= -f2)"
    ;;
  update)
    [ -f "$ENV_FILE" ] || die "demo belum dipasang"
    "${DC[@]}" up -d --build
    wait_backend; indexes
    ;;
  status)
    "${DC[@]}" ps
    "${DC[@]}" exec -T backend-demo curl -fsS http://127.0.0.1:8001/api/health && echo
    ;;
  hapus)
    read -rp "Ketik HAPUS untuk menghapus demo beserta datanya: " ok
    [ "$ok" = "HAPUS" ] || die "dibatalkan"
    "${DC[@]}" down -v
    rm -f "$SITES_DIR/demo.caddy"
    reload_caddy
    ;;
  *)
    sed -n '2,7p' "$0"; exit 1 ;;
esac
