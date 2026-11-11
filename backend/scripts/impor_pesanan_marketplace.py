"""Impor ekspor PESANAN Seller Center (Shopee/TikTok) lewat jalur yang SAMA dengan Marketing › Impor Data.

KENAPA: owner menyerahkan ekspor pesanan toko (11 Nov 2026) untuk diimpor sekali ke server. Skrip ini tidak
punya aturan sendiri — ia memanggil fungsi rute impor yang dipakai layar (`routes.marketing_data_import`
upload → rencana → simpan), jadi semua penjaga berlaku sama persis: penjaga platform & gudang toko, kunci
periode, kunci pesanan (pesanan yang sama DIPERBARUI, tidak dobel), rekap harian, tautan SKU kode model.

Bawaan PRATINJAU: tiap berkas diunggah sebagai draf, rencananya dicetak (baru/diperbarui/ditolak), lalu
drafnya dihapus — tidak ada pesanan yang tersimpan. `--apply` menyimpan dengan "Perbarui yang lama". Urutkan
berkas dari yang LAMA ke yang TERBARU (mis. 28 hari → 7 hari → harian) supaya status terakhir yang menang.

Hanya mencetak angka (baris, pesanan, omzet, tautan SKU) — tidak pernah data pembeli.

Runbook (VPS) — berkas disalin ke container lalu dihapus sesudahnya:
    docker exec dahost-backend-1 mkdir -p /tmp/impor
    docker cp <berkas> dahost-backend-1:/tmp/impor/
    docker exec dahost-backend-1 python scripts/impor_pesanan_marketplace.py --toko SHP-01 /tmp/impor/a.xlsx ...
    docker exec dahost-backend-1 python scripts/impor_pesanan_marketplace.py --toko SHP-01 /tmp/impor/a.xlsx ... --apply
    docker exec dahost-backend-1 rm -rf /tmp/impor
`--gudang-platform "NAMA"` mengisi "Gudang Platform" toko (Kelola Akun) bila masih KOSONG, sebelum impor —
supaya berkas toko lain tertolak otomatis. Hanya ditulis bersama `--apply`.
"""
import argparse
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

AKTOR = {"id": "skrip-impor-pesanan", "email": "system", "role": "superadmin",
         "name": "Skrip impor pesanan marketplace (atas OK owner)"}


class _Req:
    """Permintaan minimal untuk fungsi rute: hanya `state.user`."""

    def __init__(self):
        class _S:
            pass
        self.state = _S()
        self.state.user = dict(AKTOR)


def _rp(v) -> str:
    return "Rp" + f"{float(v or 0):,.0f}".replace(",", ".")


async def _siapkan_rute():
    import routes.marketing_data_import as md

    async def _auth(req=None, *_a, **_k):
        if req is not None and getattr(req, "state", None) is not None:
            req.state.user = dict(AKTOR)
        return dict(AKTOR)

    md.require_auth = _auth          # skrip berjalan di dalam server, bukan lewat HTTP
    return md


async def _isi_gudang(db, akun: dict, gudang: str, apply: bool) -> None:
    lama = str(akun.get("platform_warehouse_name") or "").strip()
    if lama:
        print(f"  Gudang Platform toko sudah terisi '{lama}' — tidak diubah.")
        return
    if not apply:
        print(f"  Gudang Platform toko kosong → akan diisi '{gudang}' (dengan --apply).")
        return
    await db.marketing_platform_accounts.update_one(
        {"id": akun["id"]}, {"$set": {"platform_warehouse_name": gudang}})
    akun["platform_warehouse_name"] = gudang
    print(f"  Gudang Platform toko diisi '{gudang}'.")


async def jalankan(kode_toko: str, berkas: list, apply: bool, gudang: str = "") -> int:
    from starlette.datastructures import UploadFile

    from database import get_db
    md = await _siapkan_rute()
    db = get_db()
    akun = await db.marketing_platform_accounts.find_one({"account_code": kode_toko}, {"_id": 0})
    if not akun:
        print(f"Toko '{kode_toko}' tidak ada.")
        return 2
    print(f"[impor-pesanan] DB={os.environ.get('DB_NAME')} · toko {akun.get('account_code')} "
          f"'{akun.get('account_name')}' ({akun.get('platform')}) · "
          f"{'SIMPAN' if apply else 'PRATINJAU'}")
    if gudang:
        await _isi_gudang(db, akun, gudang, apply)
    if not apply and len(berkas) > 1:
        print("  (Pratinjau menilai tiap berkas sendiri-sendiri: pesanan yang juga ada di berkas sebelumnya "
              "baru terlihat 'diperbarui' saat disimpan berurutan.)")

    galat = 0
    for path in berkas:
        nama = os.path.basename(path)
        with open(path, "rb") as fh:
            raw = fh.read()
        req = _Req()
        try:
            up = await md.upload(req, file=UploadFile(file=io.BytesIO(raw), filename=nama),
                                 source_type="marketplace_orders", account_id=akun["id"],
                                 host_id=None, creator_id=None, catalog_id=None,
                                 live_session_id=None, period_start=None, period_end=None)
        except Exception as e:  # noqa: BLE001 — HTTPException penjaga: pesannya sudah kalimat staf
            print(f"- {nama}: DITOLAK saat unggah — {getattr(e, 'detail', e)}")
            galat += 1
            continue
        sid = up["session"]["id"]
        rencana = await md.plan(sid, req, on_duplicate="update", skip_warnings=False, only=None,
                                q=None, page=1, page_size=1)
        c = rencana.get("counts") or {}
        print(f"- {nama}: {c.get('total', 0)} pesanan → baru {c.get('baru', 0)}, diperbarui "
              f"{c.get('diperbarui', 0)}, sebagian {c.get('sebagian', 0)}, dilewati "
              f"{c.get('dilewati', 0)}, ditolak {c.get('ditolak', 0)}")
        for b in rencana.get("blockers") or []:
            print(f"    PENGHALANG: {b.get('message') if isinstance(b, dict) else b}")
        if not apply:
            await md.delete_session(sid, req)
            continue
        if rencana.get("blockers"):
            galat += 1
            continue
        res = await md.commit(sid, req, md.CommitIn(on_duplicate="update"))
        tk = res.get("tautan_kode_model") or {}
        rk = res.get("daily_rollup") or {}
        print(f"    disimpan: baru {res.get('inserted')}, diperbarui {res.get('updated')}, ditolak "
              f"{res.get('rejected')} · SKU tertaut kode model {tk.get('ditautkan', 0)} "
              f"({tk.get('pesanan_diperbarui', 0)} pembaruan pesanan) · rekap harian {rk.get('dates', 0)} hari, "
              f"omzet produk {_rp(rk.get('revenue_product'))}")
    return 1 if galat else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--toko", required=True, help="kode toko, mis. SHP-01")
    ap.add_argument("--gudang-platform", default="", help="isi Gudang Platform toko bila kosong")
    ap.add_argument("--apply", action="store_true", help="simpan (bawaan: pratinjau)")
    ap.add_argument("berkas", nargs="+", help="berkas ekspor, urut dari lama ke terbaru")
    a = ap.parse_args()
    return asyncio.run(jalankan(a.toko, a.berkas, a.apply, a.gudang_platform.strip()))


if __name__ == "__main__":
    sys.exit(main())
