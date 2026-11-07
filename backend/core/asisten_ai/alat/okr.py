"""Alat BACA Asisten AI: daftar OKR (Tahap B, 8 Nov 2026; agen operasi).

Pendukung alat tindakan `perbarui_key_result` (butuh id key result + nilai sekarang) dan `buat_objektif_okr`
(cek objektif yang sudah ada). Sumber = endpoint layar OKR Tracker `GET /api/management/okr/objectives`.
"""
from __future__ import annotations

from core.asisten_ai.alat_base import alat

_BATAS_OBJEKTIF = 40
_BATAS_KR = 10


def _r(v, n=1):
    try:
        return round(float(v or 0), n)
    except (TypeError, ValueError):
        return 0.0


@alat(
    name="daftar_okr",
    kind="read",
    label="Membaca OKR",
    description=(
        "Daftar objektif OKR yang aktif (bukan arsip) dari layar OKR Tracker, beserta key result-nya: id, judul, "
        "jenis (number/percentage/currency/binary), target, nilai capaian sekarang, satuan, dan progres (%). "
        "Progres key result = nilai/target (maks. 100%); progres objektif = rata-rata key result; kesehatan "
        "on_track ≥70%, at_risk ≥40%, off_track <40%. Saring dengan `periode` (mis. 2026-Q4) atau `departemen`. "
        "Pakai id key result dari sini untuk alat perbarui_key_result."),
    input_schema={
        "type": "object",
        "properties": {
            "periode": {"type": "string", "pattern": r"^\d{4}(-Q[1-4]|-H[12])?$",
                        "description": "Periode OKR, mis. 2026-Q4, 2026-H2, 2026."},
            "departemen": {"type": "string", "maxLength": 80},
        },
        "required": [],
        "additionalProperties": False,
    },
    domain="umum",
)
async def daftar_okr(ctx, args: dict) -> dict:
    params = {"include_key_results": True, "limit": 200}
    if args.get("periode"):
        params["period"] = args["periode"]
    if args.get("departemen"):
        params["department"] = args["departemen"]
    data = ((await ctx.api("GET", "/api/management/okr/objectives", params=params)) or {}).get("data") or []
    out = []
    for o in data[:_BATAS_OBJEKTIF]:
        krs = o.get("key_results") or []
        out.append({
            "id": o.get("id"), "judul": o.get("title"), "periode": o.get("period"),
            "departemen": o.get("department"), "penanggung_jawab": o.get("owner_name"),
            "prioritas": o.get("priority"), "status": o.get("status"),
            "progres_persen": _r(o.get("progress")), "kesehatan": o.get("health"),
            "key_results": [{"id": k.get("id"), "judul": k.get("title"), "jenis": k.get("metric_type"),
                             "target": _r(k.get("target_value"), 2), "nilai_sekarang": _r(k.get("current_value"), 2),
                             "satuan": k.get("unit"), "catatan": (k.get("notes") or "")[:200] or None}
                            for k in krs[:_BATAS_KR]],
            **({"key_result_lain": len(krs) - _BATAS_KR} if len(krs) > _BATAS_KR else {}),
        })
    hasil = {"jumlah_objektif": len(data), "objektif": out}
    if len(data) > _BATAS_OBJEKTIF:
        hasil["catatan"] = f"Hanya {_BATAS_OBJEKTIF} objektif pertama yang ditampilkan; saring dengan periode."
    return {"hasil": hasil, "_sumber": "OKR Tracker"}
