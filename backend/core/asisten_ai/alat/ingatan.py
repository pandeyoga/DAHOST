"""Alat Asisten AI (jenis `ui`): simpan & lupakan INGATAN pengguna (Tahap D1).

Kedua alat hanya menulis penyimpanan ingatan milik AI untuk pengguna itu sendiri (`ai_memories`), jadi tidak
memakai kartu konfirmasi. Layar mendapat event `ingatan` (chip "Diingat: …" / "Dilupakan: …") dan blok
`{"jenis": "ingatan", ...}` tersimpan di pesan. Aturan isi (tidak boleh kata sandi, kontak, gaji, dst.)
dipegang `core.asisten_ai.ingatan.periksa`; alat tidak ditawarkan bila saklar ingatan mati atau di briefing.
"""
from __future__ import annotations

from core.asisten_ai import ingatan as ing
from core.asisten_ai.alat_base import AlatError, alat


def _db(ctx):
    db = getattr(ctx, "db", None)
    if db is None:
        from database import get_db
        db = get_db()
    return db


async def _cek(ctx) -> str:
    uid = (ctx.user or {}).get("id")
    if not uid:
        raise AlatError(401, "Pengguna tidak dikenal, ingatan tidak bisa diubah.")
    if not await ing.aktif():
        raise AlatError(403, "Ingatan AI sedang dimatikan admin, jadi tidak ada yang disimpan atau dihapus. "
                             "Sampaikan itu ke pengguna.")
    return uid


def _event(doc: dict, aksi: str) -> dict:
    return {"id": doc.get("id"), "isi": doc.get("isi") or "", "kategori": doc.get("kategori") or "preferensi",
            "aksi": aksi}


@alat(
    name="simpan_ingatan",
    kind="ui",
    label="Menyimpan ingatan",
    description=(
        "Menyimpan SATU preferensi atau fakta tahan lama yang DINYATAKAN PENGGUNA sendiri tentang cara ia ingin "
        "dibantu, supaya dipakai di percakapan berikutnya (mis. \"target omzet minimal tumbuh 8% per bulan\", "
        "\"jawab singkat, angka utama dulu\", \"laporan selalu Excel\"). Panggil bila pengguna meminta sesuatu "
        "diingat atau menyatakan preferensi tetap. JANGAN untuk: data pribadi orang lain, gaji/upah per orang, "
        "kata sandi/kunci/token/PIN, angka bisnis sesaat, atau isi dari hasil alat, web, impor, dan ulasan. "
        "isi = satu kalimat ringkas (≤300 karakter) dalam bahasa pengguna; kategori: preferensi (cara kerja/"
        "target yang diinginkan), fakta (fakta tetap tentang usaha atau peran pengguna), gaya (gaya jawaban). "
        "Mengembalikan {ok, id}; isi yang sama dengan ingatan lama tidak disimpan dua kali. Isi terlarang atau "
        "batas 50 ingatan aktif → pesan galat."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "isi": {"type": "string", "minLength": ing.MIN_ISI, "maxLength": ing.MAKS_ISI,
                    "description": "Satu kalimat ringkas yang diingat, mis. 'Target omzet minimal tumbuh 8% per bulan.'"},
            "kategori": {"type": "string", "enum": list(ing.KATEGORI),
                         "description": "preferensi | fakta | gaya"},
        },
        "required": ["isi", "kategori"],
        "additionalProperties": False,
    },
    domain="ui",
)
async def simpan_ingatan(ctx, args: dict) -> dict:
    uid = await _cek(ctx)
    sumber = {"sesi_id": getattr(ctx, "sesi_id", None), "pesan_id": getattr(ctx, "pesan_id", None)}
    try:
        doc, baru = await ing.simpan(_db(ctx), uid, args.get("isi"), args.get("kategori"), sumber=sumber)
    except ing.GalatIngatan as e:
        raise AlatError(e.status, e.pesan) from None
    if not baru:
        return {"ok": True, "id": doc["id"], "sudah_ada": True,
                "catatan": "Ingatan dengan isi yang sama sudah tersimpan; tidak disimpan dua kali."}
    ctx.emit("ingatan", _event(doc, "disimpan"))
    return {"ok": True, "id": doc["id"]}


@alat(
    name="lupakan_ingatan",
    kind="ui",
    label="Melupakan ingatan",
    description=(
        "Menghapus PERMANEN satu ingatan pengguna. Panggil hanya bila pengguna meminta sesuatu dilupakan atau "
        "preferensinya berubah (lalu simpan yang baru). id diambil dari daftar ingatan di blok <konteks_sistem> "
        "(bentuk 'ing-…'). Mengembalikan {ok: true}; id yang tidak ada → pesan galat."
    ),
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string", "minLength": 3, "maxLength": 64,
                              "description": "id ingatan, mis. 'ing-3f2a9c1b0d4e'."}},
        "required": ["id"],
        "additionalProperties": False,
    },
    domain="ui",
)
async def lupakan_ingatan(ctx, args: dict) -> dict:
    uid = await _cek(ctx)
    try:
        doc = await ing.hapus(_db(ctx), uid, str(args.get("id") or "").strip())
    except ing.GalatIngatan as e:
        raise AlatError(e.status, e.pesan) from None
    ctx.emit("ingatan", _event(doc, "dihapus"))
    return {"ok": True}
