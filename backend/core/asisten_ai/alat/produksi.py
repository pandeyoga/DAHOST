"""Alat baca Asisten AI — produksi & HPP per PO (Kontrak A). Angka dari endpoint Tahap 9 lewat `ctx.api`.

Sumber:
  * `GET /api/pantau/ringkasan?business_type=internal|maklon` — layar Pantau Produksi (alur barang, PO telat,
    deadline dekat, QC, biaya jahit/permak);
  * `GET /api/rahaza/hpp/po` dan `GET /api/rahaza/hpp/po/{po_id}` — HPP aktual per PO (potongan + aksesoris
    diserahkan + upah CMT + permak; biaya umum per pcs hanya informasi, tidak masuk HPP).
Jenis PO mengikuti CV bila tidak diminta: CV Dewi Aditya = internal, CV Sukma = maklon, Gabungan = keduanya.
Nama vendor CMT dan klien disamarkan (K27); nomor PO tetap tampil supaya bisa dicari di layar.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import AlatError, alat
from core.asisten_ai.alat._bantu_laporan import cv_aktif, label_cv, pangkas, rp, samaran

P_PANTAU = "/api/pantau/ringkasan"
P_HPP = "/api/rahaza/hpp/po"
LABEL_RISIKO = {"telat": "telat", "berisiko": "berisiko", "aman": "aman", "tanpa_deadline": "tanpa tenggat"}


def jenis_po(ctx, args: dict) -> list:
    j = (args or {}).get("jenis")
    if j in ("internal", "maklon"):
        return [j]
    return {"DA": ["internal"], "SMU": ["maklon"]}.get(cv_aktif(ctx), ["internal", "maklon"])


def _baris_po(r: dict, ps) -> dict:
    out = {"po": r.get("po_number"), "vendor": ps.code(r.get("vendor_name"), "vendor") if r.get("vendor_name") else None,
           "status": LABEL_RISIKO.get(r.get("risk"), r.get("risk")), "tenggat": r.get("deadline"),
           "sisa_hari": r.get("days_to_deadline"), "progres_pct": r.get("progress_pct"),
           "qty_pesan": r.get("ordered"), "lolos_qc": r.get("accepted")}
    return {k: v for k, v in out.items() if v is not None}


def _pantau(d: dict, ps) -> dict:
    kpi = d.get("kpi") or {}
    t = d.get("totals") or {}
    bal = d.get("balance") or {}
    biaya = d.get("biaya") or {}
    return {
        "indikator": {"po_berjalan": kpi.get("po_berjalan"), "qty_dipesan": kpi.get("qty_berjalan"),
                      "di_vendor_cmt": kpi.get("di_cmt"), "sedang_qc": kpi.get("in_qc"),
                      "po_telat": kpi.get("telat"), "po_berisiko": kpi.get("berisiko"),
                      "tingkat_reject_pct": kpi.get("reject_rate"), "progres_lolos_qc_pct": kpi.get("progress_pct"),
                      "lolos_qc": t.get("accepted")},
        "alur_barang": [{"tahap": a.get("label"), "qty": a.get("qty"), "dokumen": a.get("docs"),
                         "satuan_dokumen": a.get("doc_label")} for a in d.get("alur") or []],
        "keseimbangan": {"semua_cocok": bal.get("all_ok"),
                         "tidak_cocok": [{"cek": c.get("label"), "selisih": c.get("diff"),
                                          "po_terkait": c.get("offender_count")}
                                         for c in bal.get("checks") or [] if not c.get("ok")][:6]},
        "po_telat_atau_berisiko": [_baris_po(r, ps) for r in (d.get("overdue") or [])[:12]],
        "tenggat_14_hari": [_baris_po(r, ps) for r in (d.get("upcoming") or [])[:10]],
        "selesai": {"qc_hari_ini": (d.get("done") or {}).get("qc_today"),
                    "qc_periode": (d.get("done") or {}).get("qc_window"),
                    "job_selesai_periode": (d.get("done") or {}).get("jobs_window")},
        "job": d.get("jobs"),
        "nomor_seri_dobel": (d.get("duplicate_serials") or {}).get("count"),
        "biaya": {"ongkos_jahit": rp(biaya.get("ongkos_jahit")), "biaya_permak": rp(biaya.get("biaya_permak")),
                  "permak_aktif": biaya.get("permak_aktif"), "permintaan_komponen_kurang": biaya.get("komponen_kurang")},
    }


@alat(
    name="pantau_produksi_ringkas",
    kind="read",
    label="Membaca pantauan produksi",
    description=(
        "Ringkasan Pantau Produksi untuk PO yang sedang berjalan: indikator (PO berjalan, qty dipesan, di vendor "
        "CMT, sedang QC, PO telat/berisiko, tingkat reject %, progres lolos QC %), alur barang per tahap, cek "
        "keseimbangan qty, daftar PO telat/berisiko dan tenggat ≤14 hari (nomor PO, sisa hari, progres), QC & job "
        "selesai dalam N hari, nomor seri dobel, dan biaya jahit/permak. 'jenis' internal (Portal Produksi) atau "
        "maklon (Portal Maklon); kosong = mengikuti CV aktif. Nama vendor disamarkan (VND-xxx)."),
    input_schema={"type": "object", "properties": {
        "jenis": {"type": "string", "enum": ["internal", "maklon"]},
        "hari": {"type": "integer", "minimum": 1, "maximum": 90, "description": "Jendela 'selesai' (bawaan 7 hari)."},
    }, "additionalProperties": False},
    domain="produksi",
)
async def pantau_produksi_ringkas(ctx, args: dict) -> dict:
    ps = samaran(ctx)
    hari = max(1, min(90, int((args or {}).get("hari") or 7)))
    hasil = {"cv": label_cv(cv_aktif(ctx)), "jendela_hari": hari}
    for j in jenis_po(ctx, args):
        d = await ctx.api("GET", P_PANTAU, params={"business_type": j, "days": hari})
        hasil[j] = {"per_tanggal": d.get("as_of"), **_pantau(d, ps)}
    hasil["_sumber"] = "Pantau Produksi"
    return pangkas(hasil)


def _po_hpp(f: dict, ps) -> dict:
    out = {"po": f.get("po_number"), "jenis": f.get("business_type"), "status": f.get("status"),
           "ditutup": f.get("closed"),
           "vendor": ps.code(f.get("vendor_name"), "vendor") if f.get("vendor_name") else None,
           "qty_pesan": f.get("qty_ordered"), "qty_lolos_qc": f.get("qty_accepted"),
           "komponen": {"potongan": rp(f.get("cut_cost")), "aksesoris": rp(f.get("accessory_cost")),
                        "upah_cmt": rp(f.get("cmt_cost")), "permak": rp(f.get("permak_cost"))},
           "total_hpp": rp(f.get("total_hpp")), "hpp_per_pcs": rp(f.get("hpp_per_pcs")) if f.get("hpp_per_pcs") else None}
    if f.get("business_type") == "maklon":
        out.update({"pendapatan": rp(f.get("revenue")), "margin": rp(f.get("margin")) if f.get("margin") is not None else None})
    elif f.get("selling_price_per_pcs"):
        out.update({"harga_jual_per_pcs": rp(f.get("selling_price_per_pcs")),
                    "margin_per_pcs": rp(f.get("margin_per_pcs")) if f.get("margin_per_pcs") is not None else None})
    if f.get("margin_pct") is not None:
        out["margin_pct"] = f.get("margin_pct")
    if f.get("items_missing_rate"):
        out["catatan"] = "Ada baris tanpa tarif upah CMT — HPP bisa kurang."
    return {k: v for k, v in out.items() if v is not None}


@alat(
    name="hpp_per_po",
    kind="read",
    label="Membaca HPP per PO",
    description=(
        "HPP aktual per PO produksi (internal dan/atau maklon): ringkasan (jumlah PO, total HPP, pcs lolos QC, HPP "
        "per pcs, biaya belum terserap, PO tanpa tarif; maklon: pendapatan, margin, margin %) dan PO dengan HPP "
        "terbesar beserta komponennya (potongan, aksesoris, upah CMT, permak; Rupiah). Isi 'nomor_po' untuk "
        "rincian satu PO (komponen per pcs & selisih). Biaya umum pabrik per pcs hanya informasi, tidak masuk "
        "HPP. Saring dengan status (open/closed) dan tanggal PO (dari/sampai)."),
    input_schema={"type": "object", "properties": {
        "jenis": {"type": "string", "enum": ["internal", "maklon"]},
        "nomor_po": {"type": "string", "description": "Nomor PO untuk rincian satu PO."},
        "status": {"type": "string", "enum": ["open", "closed"]},
        "dari": {"type": "string", "description": "Tanggal PO dari (TTTT-BB-HH)."},
        "sampai": {"type": "string", "description": "Tanggal PO sampai (TTTT-BB-HH)."},
    }, "additionalProperties": False},
    domain="produksi",
)
async def hpp_per_po(ctx, args: dict) -> dict:
    args = args or {}
    ps = samaran(ctx)
    jenis = jenis_po(ctx, args)
    bt = jenis[0] if len(jenis) == 1 else ""
    params = {"business_type": bt, "per_page": 100, "page": 1}
    for k_in, k_out in (("status", "status"), ("dari", "date_from"), ("sampai", "date_to"), ("nomor_po", "search")):
        if args.get(k_in):
            params[k_out] = str(args[k_in])[:60]
    d = await ctx.api("GET", P_HPP, params=params)
    s = d.get("summary") or {}
    items = d.get("items") or []
    hasil = {
        "cv": label_cv(cv_aktif(ctx)), "jenis": jenis,
        "ringkas": {"jumlah_po": s.get("po_count"), "total_hpp": rp(s.get("total_hpp")),
                    "pcs_lolos_qc": s.get("qty_accepted"),
                    "hpp_per_pcs": rp(s.get("hpp_per_pcs")) if s.get("hpp_per_pcs") else None,
                    "biaya_belum_terserap": rp(s.get("unabsorbed_cost")), "po_tanpa_tarif": s.get("missing_rate_pos")},
        "po_hpp_terbesar": [_po_hpp(f, ps) for f in sorted(items, key=lambda f: -float(f.get("total_hpp") or 0))[:15]],
    }
    if "revenue" in s:
        hasil["ringkas"].update({"pendapatan_maklon": rp(s.get("revenue")), "margin_maklon": rp(s.get("margin")),
                                 "margin_maklon_pct": s.get("margin_pct")})
    ov = d.get("overhead") or {}
    if ov:
        hasil["biaya_umum_informasi"] = {"bulan": ov.get("month"), "biaya_umum": rp(ov.get("overhead")),
                                         "pcs": ov.get("pcs"), "per_pcs": rp(ov.get("per_pcs")) if ov.get("per_pcs") else None,
                                         "catatan": "Tidak masuk HPP (keputusan owner)."}
    if d.get("capped"):
        hasil["catatan"] = "Hanya 500 PO terbaru yang dihitung; persempit dengan tanggal atau status."
    if args.get("nomor_po"):
        cocok = next((f for f in items if str(f.get("po_number") or "").lower() == str(args["nomor_po"]).lower()), None)
        if not cocok:
            raise AlatError(404, f"PO {args['nomor_po']} tidak ditemukan di HPP per PO.")
        det = await ctx.api("GET", f"{P_HPP}/{cocok['po_id']}")
        hasil["rincian_po"] = {
            **_po_hpp(det, ps),
            "komponen_per_pcs": [{"komponen": c.get("label"), "nilai": rp(c.get("amount")),
                                  "per_pcs": rp(c.get("per_pcs")) if c.get("per_pcs") is not None else None}
                                 for c in det.get("components") or []],
            "kekurangan_data": [str(g.get("label") or g.get("message") or g)[:140]
                                for g in (det.get("gaps") or [])[:8]],
        }
    hasil["_sumber"] = "HPP per PO"
    return pangkas(hasil, ("po_hpp_terbesar",))
