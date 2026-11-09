"""core.impor_analisis — **analisis hasil impor dengan bukti angka** (bahan AI analis, butir 5).

Setiap temuan dihitung KODE dari data yang benar-benar tersimpan oleh sesi impor + rekap harian
resmi (`core.ukuran_penjualan`); AI hanya membaca dan menafsirkan hasil ini (alat Asisten AI
`analisis_impor`). Temuan yang dicari (permintaan owner 9 Nov 2026):

* omzet harian naik/turun tajam — di luar ±2 simpangan baku 28 hari sebelumnya;
* pesanan batal melonjak — pangsa batal ≥ 2× dan ≥ 5 poin dari 28 hari sebelumnya;
* SKU belum tertaut katalog — banyak baris & omzet yang belum bisa dihitung HPP/stoknya;
* biaya iklan aneh — kampanye berbiaya besar tanpa pendapatan, ROAS < 1, biaya per pesanan
  > 3× median, total biaya jauh dari periode sebelumnya;
* subsidi platform (diskon yang dibiayai platform) — pangsa terhadap omzet;
* selisih omzet pesanan vs laporan penghasilan (pencairan) pada periode yang sama;
* kualitas data — baris ditolak/duplikat/peringatan dari sesi impor.

Tidak ada data pembeli dalam keluaran.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from core import ukuran_penjualan as U

JENDELA_HARI = 28
SIGMA = 2.0
ORDER_TYPES = ("marketplace_orders", "orders")
ADS_TYPES = ("shopee_ads_cpc", "tiktok_gmv_max", "ads")


def _d(v: Any) -> Optional[str]:
    return U.kunci_tanggal(v)


def _rp(v: Any) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _fmt(v: float) -> str:
    return "Rp" + f"{round(v):,}".replace(",", ".")


def _temuan(jenis: str, tingkat: str, judul: str, kalimat: str, angka: dict, toko: str = "") -> dict:
    return {"jenis": jenis, "tingkat": tingkat, "judul": judul, "kalimat": kalimat, "angka": angka, "toko": toko}


async def _sesi(db, ids: Sequence[str]) -> List[dict]:
    if not ids:
        return []
    out = await db.marketing_data_import_sessions.find(
        {"id": {"$in": list(ids)}},
        {"_id": 0, "id": 1, "source_type": 1, "source_label": 1, "account_id": 1, "account_name": 1,
         "filename": 1, "status": 1, "committed_count": 1, "updated_count": 1, "rejected_count": 1,
         "skipped_duplicates": 1, "total_rows": 1, "row_notes": 1, "committed_at": 1}).to_list(len(ids) + 5)
    return out


async def _analisis_pesanan(db, s: dict, temuan: List[dict]) -> dict:
    aid = s.get("account_id")
    toko = s.get("account_name") or aid
    orders = await db.marketing_orders.find(
        {"_import_session_id": s["id"]},
        {"_id": 0, "order_date": 1, "status": 1, "revenue_product": 1, "platform_discount_total": 1,
         "items": 1, "paid_at": 1, "status_assumed": 1, "_source_type": 1, "_seed_origin": 1}).to_list(25000)
    if not orders:
        return {"pesanan": 0}
    tgl = sorted({_d(o.get("order_date")) for o in orders} - {None})
    dihitung = [o for o in orders if U.dihitung_omzet(o)]
    batal = [o for o in orders if str(o.get("status") or "").lower() in U.STATUS_BATAL]
    omzet = sum(_rp(o.get("revenue_product")) for o in dihitung)
    subsidi = sum(_rp(o.get("platform_discount_total")) for o in dihitung)
    items = [it for o in orders for it in (o.get("items") or [])]
    lepas = [it for it in items if not it.get("catalog_item_id")]
    omzet_lepas = sum(_rp(it.get("sku_subtotal_after_discount")) for it in lepas)
    out = {"pesanan": len(orders), "pesanan_dihitung": len(dihitung), "omzet": round(omzet),
           "batal": len(batal), "dari": tgl[0] if tgl else None, "sampai": tgl[-1] if tgl else None,
           "subsidi_platform": round(subsidi), "sku_baris": len(items), "sku_belum_tertaut": len(lepas),
           "omzet_sku_belum_tertaut": round(omzet_lepas)}
    if lepas:
        pangsa = round(len(lepas) / max(1, len(items)) * 100, 1)
        temuan.append(_temuan(
            "sku_belum_tertaut", "tinggi" if pangsa >= 20 else "sedang",
            "SKU belum tertaut katalog",
            f"{len(lepas)} dari {len(items)} baris SKU ({pangsa}%) belum tertaut item katalog; omzetnya "
            f"{_fmt(omzet_lepas)} tetap masuk, tetapi HPP & stoknya belum terhitung. Lengkapi di layar Pemetaan SKU.",
            {"baris": len(lepas), "dari_baris": len(items), "persen": pangsa, "omzet": round(omzet_lepas)}, toko))
    if omzet and subsidi:
        p = round(subsidi / omzet * 100, 1)
        temuan.append(_temuan(
            "subsidi_platform", "info", "Diskon yang dibiayai platform",
            f"Diskon yang dibiayai platform {_fmt(subsidi)} ({p}% omzet) ikut omzet dan diganti platform saat "
            "pencairan — cek angka ini di laporan penghasilan.", {"nilai": round(subsidi), "persen": p}, toko))
    if not tgl or not aid:
        return out
    # ── omzet harian vs 28 hari sebelumnya (rekap resmi) ────────────────────────
    a = (date.fromisoformat(tgl[0]) - timedelta(days=JENDELA_HARI)).isoformat()
    rows, _dup = await U.baca_rekap(db, [aid], a, tgl[-1])
    by = {r["date"]: r for r in rows}
    sebelum = [by[d]["omzet"] for d in sorted(by) if d < tgl[0]]
    if len(sebelum) >= 7:
        rata = statistics.mean(sebelum)
        sd = statistics.pstdev(sebelum)
        for d in tgl:
            r = by.get(d)
            if not r or sd <= 0:
                continue
            z = (r["omzet"] - rata) / sd
            if abs(z) >= SIGMA:
                arah = "naik" if z > 0 else "turun"
                temuan.append(_temuan(
                    "omzet_tajam", "sedang", f"Omzet {d} {arah} tajam",
                    f"Omzet {d} {_fmt(r['omzet'])}, rata-rata {JENDELA_HARI} hari sebelumnya {_fmt(rata)} "
                    f"(simpangan {_fmt(sd)}; {abs(z):.1f}× simpangan). Periksa apakah ada kampanye, gangguan, "
                    "atau impor ganda.", {"tanggal": d, "omzet": round(r["omzet"]), "rata": round(rata),
                                          "simpangan": round(sd), "z": round(z, 2)}, toko))
    else:
        out["catatan_pembanding"] = f"Rekap sebelum {tgl[0]} baru {len(sebelum)} hari — pembanding omzet butuh ≥ 7 hari."
    # ── lonjakan batal ─────────────────────────────────────────────────────────
    lalu = await db.marketing_orders.find(
        {"account_id": aid, "_import_session_id": {"$ne": s["id"]}},
        {"_id": 0, "order_date": 1, "status": 1}).to_list(50000)
    lalu = [o for o in lalu if a <= (_d(o.get("order_date")) or "") < tgl[0]]
    if len(lalu) >= 20 and orders:
        p_lalu = sum(1 for o in lalu if str(o.get("status") or "").lower() in U.STATUS_BATAL) / len(lalu) * 100
        p_kini = len(batal) / len(orders) * 100
        out["persen_batal"], out["persen_batal_sebelumnya"] = round(p_kini, 1), round(p_lalu, 1)
        if p_kini >= 2 * max(p_lalu, 0.1) and p_kini - p_lalu >= 5:
            temuan.append(_temuan(
                "batal_melonjak", "tinggi", "Pesanan batal melonjak",
                f"{len(batal)} dari {len(orders)} pesanan berkas ini batal ({p_kini:.1f}%), dibanding "
                f"{p_lalu:.1f}% pada {JENDELA_HARI} hari sebelumnya.",
                {"batal": len(batal), "pesanan": len(orders), "persen": round(p_kini, 1),
                 "persen_sebelumnya": round(p_lalu, 1)}, toko))
    # ── selisih vs laporan penghasilan ─────────────────────────────────────────
    setoran = await db[U.SETTLEMENTS].find(
        {"account_id": aid, "period_from": {"$lte": tgl[-1]}, "period_to": {"$gte": tgl[0]}},
        {"_id": 0, "gross_sales": 1, "period_from": 1, "period_to": 1, "settlement_id": 1}).to_list(200)
    if setoran:
        p_a = min(str(x.get("period_from")) for x in setoran)
        p_b = max(str(x.get("period_to")) for x in setoran)
        bruto = sum(_rp(x.get("gross_sales")) for x in setoran)
        rows2, _ = await U.baca_rekap(db, [aid], p_a, p_b)
        rek = sum(r["omzet"] for r in rows2)
        if rek:
            selisih = round((bruto - rek) / rek * 100, 1)
            out["selisih_setoran_persen"] = selisih
            temuan.append(_temuan(
                "selisih_setoran", "sedang" if abs(selisih) >= 5 else "info",
                "Omzet pesanan vs laporan penghasilan",
                f"Periode {p_a} s/d {p_b}: penjualan di laporan penghasilan {_fmt(bruto)}, omzet rekap pesanan "
                f"{_fmt(rek)} (selisih {selisih}%). Selisih wajar bila ada pesanan yang belum dilepas dananya.",
                {"setoran": round(bruto), "rekap": round(rek), "persen": selisih, "dari": p_a, "sampai": p_b}, toko))
    return out


async def _analisis_iklan(db, s: dict, temuan: List[dict]) -> dict:
    toko = s.get("account_name") or s.get("account_id")
    rows = await db.marketing_ads_data.find(
        {"_import_session_id": s["id"]},
        {"_id": 0, "campaign_name": 1, "spend": 1, "revenue": 1, "conversions": 1, "cost_per_order": 1,
         "period_start": 1, "period_end": 1, "date": 1, "roas": 1}).to_list(25000)
    if not rows:
        return {"baris": 0}
    biaya = sum(_rp(r.get("spend")) for r in rows)
    pend = sum(_rp(r.get("revenue")) for r in rows)
    out = {"baris": len(rows), "biaya": round(biaya), "pendapatan_iklan": round(pend),
           "roas": round(pend / biaya, 2) if biaya else None}
    per: Dict[str, Dict[str, float]] = {}
    for r in rows:
        k = str(r.get("campaign_name") or "-")
        p = per.setdefault(k, {"biaya": 0.0, "pendapatan": 0.0, "pesanan": 0.0})
        p["biaya"] += _rp(r.get("spend"))
        p["pendapatan"] += _rp(r.get("revenue"))
        p["pesanan"] += float(r.get("conversions") or 0)
    boros = [(k, v) for k, v in per.items() if v["biaya"] >= max(0.1 * biaya, 1) and v["pendapatan"] < v["biaya"]]
    for k, v in sorted(boros, key=lambda kv: -kv[1]["biaya"])[:5]:
        roas = round(v["pendapatan"] / v["biaya"], 2) if v["biaya"] else 0
        temuan.append(_temuan(
            "iklan_boros", "tinggi" if v["pendapatan"] == 0 else "sedang", f"Kampanye “{k[:60]}” rugi",
            f"Biaya {_fmt(v['biaya'])} ({round(v['biaya'] / biaya * 100, 1)}% biaya berkas) dengan pendapatan iklan "
            f"{_fmt(v['pendapatan'])} (ROAS {roas}).", {"kampanye": k[:80], "biaya": round(v["biaya"]),
                                                       "pendapatan": round(v["pendapatan"]), "roas": roas}, toko))
    cpo = [(_rp(r.get("spend")) / float(r["conversions"])) for r in rows if float(r.get("conversions") or 0) > 0]
    if len(cpo) >= 5:
        med = statistics.median(cpo)
        mahal = [x for x in cpo if med > 0 and x > 3 * med]
        if mahal:
            temuan.append(_temuan(
                "biaya_per_pesanan", "sedang", "Biaya per pesanan tidak wajar",
                f"{len(mahal)} baris iklan berbiaya per pesanan > 3× median ({_fmt(med)}); tertinggi {_fmt(max(mahal))}.",
                {"baris": len(mahal), "median": round(med), "tertinggi": round(max(mahal))}, toko))
    # pembanding periode sebelumnya (panjang sama)
    tgl = sorted({str(r.get("period_start") or _d(r.get("date")) or "")[:10] for r in rows} - {""})
    akhir = sorted({str(r.get("period_end") or _d(r.get("date")) or "")[:10] for r in rows} - {""})
    if tgl and akhir and s.get("account_id"):
        a, b = date.fromisoformat(tgl[0]), date.fromisoformat(akhir[-1])
        n = (b - a).days + 1
        pa, pb = (a - timedelta(days=n)).isoformat(), (a - timedelta(days=1)).isoformat()
        lalu = await db.marketing_ads_data.find(
            {"account_id": s["account_id"], "_import_session_id": {"$ne": s["id"]}},
            {"_id": 0, "spend": 1, "date": 1, "period_start": 1}).to_list(50000)
        b_lalu = sum(_rp(x.get("spend")) for x in lalu
                     if pa <= (str(x.get("period_start") or "")[:10] or _d(x.get("date")) or "") <= pb)
        out["biaya_periode_sebelumnya"] = round(b_lalu)
        if b_lalu > 0 and (biaya >= 2 * b_lalu or biaya <= 0.5 * b_lalu):
            temuan.append(_temuan(
                "biaya_iklan_berubah", "sedang", "Biaya iklan berubah tajam",
                f"Biaya iklan {_fmt(biaya)} untuk {tgl[0]} s/d {akhir[-1]}, sedangkan {n} hari sebelumnya {_fmt(b_lalu)}.",
                {"biaya": round(biaya), "sebelumnya": round(b_lalu), "dari": tgl[0], "sampai": akhir[-1]}, toko))
    return out


async def _analisis_retur(db, s: dict, temuan: List[dict]) -> dict:
    rows = await db.marketing_returns.find(
        {"_import_session_id": s["id"]},
        {"_id": 0, "refund_amount": 1, "reason": 1, "goods_returned": 1, "status": 1}).to_list(25000)
    alasan: Dict[str, int] = {}
    for r in rows:
        alasan[str(r.get("reason") or "lainnya")] = alasan.get(str(r.get("reason") or "lainnya"), 0) + 1
    return {"retur": len(rows), "nilai_refund": round(sum(_rp(r.get("refund_amount")) for r in rows)),
            "tanpa_barang_kembali": sum(1 for r in rows if r.get("goods_returned") is False),
            "alasan_teratas": sorted(alasan.items(), key=lambda kv: -kv[1])[:5]}


def _kualitas(s: dict, temuan: List[dict]) -> dict:
    tot = int(s.get("total_rows") or 0)
    ditolak = int(s.get("rejected_count") or 0)
    out = {"baris_berkas": tot, "masuk": int(s.get("committed_count") or 0),
           "diperbarui": int(s.get("updated_count") or 0), "duplikat": int(s.get("skipped_duplicates") or 0),
           "ditolak": ditolak}
    if ditolak:
        alasan: Dict[str, int] = {}
        for n in s.get("row_notes") or []:
            if n.get("action") == "ditolak":
                for w in (n.get("why") or [])[:1]:
                    alasan[str(w)[:90]] = alasan.get(str(w)[:90], 0) + 1
        top = sorted(alasan.items(), key=lambda kv: -kv[1])[:3]
        out["alasan_ditolak"] = top
        temuan.append(_temuan(
            "baris_ditolak", "tinggi" if tot and ditolak / max(1, tot) >= 0.1 else "sedang",
            f"{ditolak} baris {s.get('source_label') or ''} ditolak".strip(),
            "Alasan terbanyak: " + "; ".join(f"{a} ({n}×)" for a, n in top) if top else "Lihat unduhan baris bermasalah.",
            {"ditolak": ditolak, "baris": tot}, s.get("account_name") or ""))
    return out


async def analisis_sesi(db, session_ids: Sequence[str]) -> dict:
    """Analisis beberapa sesi impor (paket atau sesi tunggal). Hanya sesi yang sudah tersimpan
    yang punya angka tersimpan; sesi yang belum disimpan dilaporkan kualitas datanya saja."""
    temuan: List[dict] = []
    per: List[dict] = []
    for s in await _sesi(db, session_ids):
        item = {"sesi_id": s["id"], "jenis": s.get("source_label"), "source_type": s.get("source_type"),
                "toko": s.get("account_name"), "berkas": s.get("filename"), "status": s.get("status"),
                "kualitas": _kualitas(s, temuan)}
        if s.get("status") == "committed":
            if s.get("source_type") in ORDER_TYPES:
                item["pesanan"] = await _analisis_pesanan(db, s, temuan)
            elif s.get("source_type") in ADS_TYPES:
                item["iklan"] = await _analisis_iklan(db, s, temuan)
            elif s.get("source_type") == "returns":
                item["retur"] = await _analisis_retur(db, s, temuan)
        per.append(item)
    urut = {"tinggi": 0, "sedang": 1, "info": 2}
    temuan.sort(key=lambda t: urut.get(t["tingkat"], 3))
    return {"dibuat": datetime.utcnow().isoformat() + "Z", "sesi": per, "temuan": temuan,
            "jumlah_temuan": {k: sum(1 for t in temuan if t["tingkat"] == k) for k in urut},
            "definisi": ("Omzet = omzet produk sesudah diskon penjual (diskon yang dibiayai platform ikut omzet), "
                         "pesanan batal & belum dibayar tidak dihitung; pembanding = rekap harian resmi "
                         f"{JENDELA_HARI} hari sebelum tanggal berkas; ±{SIGMA:g} simpangan baku.")}
