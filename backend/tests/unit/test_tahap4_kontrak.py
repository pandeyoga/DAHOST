"""Tahap 4 · pola P1/P6 (6 Nov 2026) — kontrak layar ↔ server.

P1 = layar membaca kunci yang tidak dikembalikan server / mengirim body yang tidak dibaca server.
P6 = layar mengabaikan penolakan server (tanpa cek `res.ok`, lalu "berhasil" / popup ditutup).

Setiap uji mengikat DUA sisi: perilaku server (dijalankan dengan Mongo palsu atau dibaca dari tanda
tangan rute) DAN kunci yang dipakai layar (dibaca dari sumber JSX). Bila salah satu sisi berganti nama
tanpa sisi lainnya, uji ini gagal. Semua data SINTETIS.
"""
import asyncio
import inspect
import os
import re
import sys
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
import routes.dashboard_routes as dash  # noqa: E402
import routes.dewi_cmt_component_requests as dcr  # noqa: E402
import routes.file_storage as fs  # noqa: E402
import routes.marketing_shared as msh  # noqa: E402
import routes.marketing_task_templates as mtt  # noqa: E402
import routes.marketing_tasks as mt  # noqa: E402
import routes.rahaza_inventory_stock as ris  # noqa: E402
import routes.rahaza_variants as rv  # noqa: E402
import routes.vendor_shipment as vs  # noqa: E402
from routes.communication import channel_messages as cm  # noqa: E402
from utils import scheduler as sch  # noqa: E402

FE = REPO / "frontend" / "src" / "components" / "erp"
USER = {"id": "u-uji", "name": "Staf Uji", "email": "uji@contoh.test", "role": "admin"}


def run(c):
    return asyncio.run(c)


def jsx(rel: str, comments: bool = False) -> str:
    """Sumber JSX; tanpa komentar `// ...` (komentar perbaikan menyebut nama lama)."""
    p = FE / rel
    if not p.is_file():
        pytest.skip("frontend/src tidak tersedia")
    src = p.read_text(encoding="utf-8")
    return src if comments else re.sub(r"(?m)(^|\s)//.*$", r"\1", src)


def body_keys_read(fn) -> set:
    """Kunci body yang dibaca handler: body.get("k") / body["k"] / (body or {}).get("k")."""
    src = inspect.getsource(fn)
    return set(re.findall(r"""body(?:\s+or\s+\{\}\))?\.get\(\s*['"](\w+)['"]""", src)) | \
        set(re.findall(r"""body\[\s*['"](\w+)['"]\s*\]""", src))


def route_paths(router) -> set:
    return {(r.path, m) for r in router.routes for m in getattr(r, "methods", set())}


async def _noop(*a, **k):
    return None


def _req(user=USER, body=None):
    r = FakeRequest(body)
    r.state.user = user
    return r


# ══════════════════════════════════════════════════════════════════════════════
# P1-1 · Order Cutting: daftar varian per model
# ══════════════════════════════════════════════════════════════════════════════
def test_cutting_varian_dibaca_dari_kunci_variants(monkeypatch):
    db = FakeDB()
    db.rahaza_models.docs = [{"id": "m-1", "code": "UJ-01", "name": "Model Uji"}]
    db.rahaza_model_variants.docs = [
        {"id": "v-1", "model_id": "m-1", "active": True, "color_code": "HTM", "color_name": "HITAM",
         "size_id": "s-1", "size_code": "M", "sku": "UJ-01-HTM-M"},
    ]

    async def _auth(_r):
        return USER
    monkeypatch.setattr(rv, "get_db", lambda: db)
    monkeypatch.setattr(rv, "require_auth", _auth)
    out = run(rv.list_model_variants("m-1", FakeRequest()))
    assert "variants" in out and "items" not in out
    v = out["variants"][0]
    # field yang dipakai onPickVariant ada di dokumen varian
    assert v["color_name"] == "HITAM" and v["size_code"] == "M" and v["size_id"] == "s-1"

    src = jsx("cutting/CuttingOrdersModule.jsx")
    block = src[src.index("/api/rahaza/models/${id}/variants"):][:600]
    assert "d?.variants" in block and "d?.items" not in block


# ══════════════════════════════════════════════════════════════════════════════
# P1-2 · Gudang: penyesuaian cepat stok (QuickAdjustPopover)
# ══════════════════════════════════════════════════════════════════════════════
def test_penyesuaian_cepat_mengirim_kunci_yang_dibaca_server():
    server = body_keys_read(ris.material_adjust)
    assert {"material_id", "location_id", "qty", "reason"} <= server
    src = jsx("RahazaStockModule.jsx")
    block = src[src.index("function QuickAdjustPopover"):]
    block = block[block.index("/api/rahaza/material-adjust"):][:900]
    sent = set(re.findall(r"^\s*(\w+)\s*[:,]", block[block.index("JSON.stringify({"):block.index("}),")],
                          re.M))
    assert "qty_delta" not in block and "notes:" not in block.split("JSON.stringify")[1][:300]
    assert {"material_id", "location_id", "qty", "reason"} <= sent <= server


# ══════════════════════════════════════════════════════════════════════════════
# P1-3 · Lampiran PO/pengiriman (FileAttachmentPanel) + logo perusahaan
# ══════════════════════════════════════════════════════════════════════════════
def test_lampiran_unggah_hapus_dan_daftar_sesuai_server(monkeypatch):
    # server: entity_type/entity_id dibaca dari QUERY, hapus = DELETE /api/attachments/{id}
    sig = inspect.signature(fs.upload_file)
    assert type(sig.parameters["entity_type"].default).__name__ == "Query"
    assert ("/api/attachments/{att_id}", "DELETE") in route_paths(fs.router)
    assert not any(p == "/api/upload" and m == "DELETE" for p, m in route_paths(fs.router))
    up_src = inspect.getsource(fs.upload_file)
    for k in ("original_filename", "storage_path", "created_at"):
        assert f"'{k}'" in up_src

    src = jsx("engine/FileAttachmentPanel.jsx")
    assert "apiPost(`/upload?${qs}`" in src and "entity_type=${encodeURIComponent(entityType)}" in src
    assert "formData.append('entity_type'" not in src
    assert "apiDelete(`/attachments/${att.id}`)" in src and "/upload?id=" not in src
    for gone in ("att.original_name}", "att.file_ext", "att.public_path"):
        assert gone not in src
    assert "a.original_filename" in src and "a.storage_path" in src and "att.created_at" in src

    # daftar lampiran: yang sudah dihapus (soft delete) tidak muncul lagi, terbaru di atas
    db = FakeDB()
    db.attachments.docs = [
        {"id": "a1", "entity_type": "production_po", "entity_id": "po-1", "is_deleted": False,
         "created_at": "2026-11-01T01:00:00"},
        {"id": "a2", "entity_type": "production_po", "entity_id": "po-1", "is_deleted": True,
         "created_at": "2026-11-02T01:00:00"},
        {"id": "a3", "entity_type": "production_po", "entity_id": "po-1", "is_deleted": False,
         "created_at": "2026-11-03T01:00:00"},
    ]

    class _Q:
        query_params = {"entity_type": "production_po", "entity_id": "po-1"}

    async def _auth(_r):
        return USER
    monkeypatch.setattr(dash, "get_db", lambda: db)
    monkeypatch.setattr(dash, "require_auth", _auth)
    out = run(dash.get_attachments(_Q()))
    assert [a["id"] for a in out] == ["a3", "a1"]


def test_logo_perusahaan_memakai_storage_path():
    src = jsx("CompanySettingsModule.jsx")
    block = src[src.index("/api/upload?entity_type=company_logo"):][:700]
    assert "data.storage_path" in block and "/api/uploads/${data.storage_path}" in block
    assert "data.filepath" not in block and "data.url ||" not in block
    assert "if (!res.ok" in block
    # /api/uploads/<path> melayani berkas yang sama (put_object menulis ke /app/uploads/<path>)
    import storage
    assert storage.put_object.__doc__ and "url" in inspect.getsource(storage.put_object)
    assert '"/api/uploads/{path}"' in inspect.getsource(storage.put_object).replace("f\"", "\"")


# ══════════════════════════════════════════════════════════════════════════════
# P1-4 · Komunikasi: kirim berkas ke channel
# ══════════════════════════════════════════════════════════════════════════════
def test_pesan_berkas_memakai_field_datar_yang_disimpan_server():
    server = body_keys_read(cm.send_channel_message)
    assert {"message_type", "file_url", "file_name", "file_size"} <= server
    assert "attachments" not in server
    src = jsx("communication-hub/Composer.jsx")
    block = src[src.index("const uploadData = await res.json();"):][:900]
    assert "message_type: 'file'" in block and "file_url: uploadData.file_url" in block
    assert "attachments:" not in block


# ══════════════════════════════════════════════════════════════════════════════
# P1-5 · Marketing: Tugas & Template Tugas (model pydantic kehilangan field → 500)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def mdb(monkeypatch):
    db = FakeDB()

    async def _auth(_r):
        return USER
    for mod in (mt, mtt):
        monkeypatch.setattr(mod, "get_db", lambda: db)
        monkeypatch.setattr(mod, "require_auth", _auth)
        monkeypatch.setattr(mod, "log_activity", _noop)
    return db


def test_buat_tugas_dengan_payload_layar(mdb):
    # bentuk payload CreateTaskDialog.jsx (tanpa toko untuk tipe selain data_entry)
    payload = {
        "title": "Cek ulasan", "description": None, "task_type": "review", "priority": "medium",
        "assigned_to": None, "account_id": None, "due_date": "2026-11-07T10:00:00+07:00",
        "checklist": [{"item": "baca ulasan", "completed": False}], "recurrence": "one-time",
        "related_entity": "review", "related_entity_id": "rv-1", "related_form_data": None,
        "action_type": "review_content",
    }
    out = run(mt.create_task(msh.TaskCreate(**payload), _req()))
    t = mdb.marketing_tasks.docs[0]
    assert out["task"]["id"] == t["id"]
    assert t["checklist"] == payload["checklist"] and t["related_entity_id"] == "rv-1"
    assert t["action_type"] == "review_content" and t["account_id"] is None and t["recurrence"] == "one-time"
    # sisi layar: kunci yang dikirim semuanya dikenal model
    src = jsx("CreateTaskDialog.jsx")
    block = src[src.index("const payload = {"):src.index("const res = await fetch(`${API}/api/marketing/tasks`")]
    sent = set(re.findall(r"^\s*(\w+)\s*[:,]", block.split("{", 1)[1], re.M))
    assert sent and sent <= set(msh.TaskCreate.model_fields)


def test_simpan_dan_selesaikan_tugas_dengan_payload_layar(mdb):
    mdb.marketing_tasks.docs = [{"id": "t-1", "title": "Uji", "status": "to_do", "action_type": "manual_check",
                                 "checklist": []}]
    upd = {"title": "Uji", "description": "", "priority": "high", "status": "in_progress", "due_date": None,
           "completion_notes": "sedang dikerjakan", "checklist": [{"item": "a", "completed": True}]}
    run(mt.update_task("t-1", msh.TaskUpdate(**upd), _req()))
    t = mdb.marketing_tasks.docs[0]
    assert t["status"] == "in_progress" and t["checklist"] == upd["checklist"]
    assert t["completion_notes"] == "sedang dikerjakan"

    act = msh.TaskCompleteAction(**{"action_data": {}, "completion_notes": "beres"})
    out = run(mt.complete_task_action("t-1", act, _req()))
    assert out["result"]["success"] is True
    assert mdb.marketing_tasks.docs[0]["status"] == "done"
    assert mdb.marketing_tasks.docs[0]["completion_notes"] == "beres"
    for rel, anchor in (("TaskDetailDrawer.jsx", "complete-action`"),
                        ("marketing/DailyReportModule.jsx", "complete-action`")):
        block = jsx(rel)
        block = block[block.index(anchor):][:500]
        sent = set(re.findall(r"^\s*(\w+)\s*:", block[block.index("JSON.stringify({"):block.index("}),")], re.M))
        assert sent and sent <= set(msh.TaskCompleteAction.model_fields), (rel, sent)


def test_template_tugas_dengan_payload_layar_dan_jadwal_mingguan(mdb, monkeypatch):
    payload = {
        "template_name": "Rekap mingguan", "title": "Rekap toko", "description": None,
        "task_type": "reporting", "priority": "medium", "recurrence": "weekly",
        "recurrence_config": {"frequency": "weekly", "time": "09:00", "auto_create": True,
                              "days_of_week": ["wednesday"]},
        "default_assigned_role": "staff_marketing", "is_active": True, "checklist_template": ["unduh laporan"],
    }
    out = run(mtt.create_task_template(msh.TaskTemplateCreate(**payload), _req()))
    tpl = mdb.marketing_task_templates.docs[0]
    assert out["template"]["template_name"] == "Rekap mingguan"
    rc = tpl["recurrence_config"]
    assert payload["recurrence_config"].items() <= rc.items() and None not in rc.values()  # tanpa kunci None
    src = jsx("TaskTemplatesModule.jsx")
    block = src[src.index("const payload = {"):src.index("const url = isEdit")]
    sent = set(re.findall(r"^\s*(\w+)\s*[:,]", block.split("{", 1)[1], re.M))
    assert sent and sent <= set(msh.TaskTemplateCreate.model_fields)
    # update (aktifkan ulang) memakai model yang sama
    run(mtt.update_task_template(tpl["id"], msh.TaskTemplateCreate(**{**payload, "is_active": False}), _req()))
    assert mdb.marketing_task_templates.docs[0]["is_active"] is False
    mdb.marketing_task_templates.docs[0]["is_active"] = True

    # scheduler: days_of_week berisi NAMA hari (layar), bukan day_of_week angka
    monkeypatch.setattr(sch, "get_db", lambda: mdb)
    mdb.marketing_task_templates.docs += [
        {"id": "tpl-lama", "is_active": True, "recurrence": "weekly", "recurrence_config": {"day_of_week": 2},
         "title": "format lama", "checklist_template": []},
        {"id": "tpl-mati", "is_active": True, "recurrence": "daily",
         "recurrence_config": {"auto_create": False}, "title": "otomatis dimatikan"},
    ]
    monkeypatch.setattr(sch, "today_wib", lambda: date(2026, 11, 4))   # Rabu
    run(sch.job_auto_create_tasks_from_templates())
    made = {t.get("template_id") for t in mdb.marketing_tasks.docs}
    assert made == {tpl["id"], "tpl-lama"}
    monkeypatch.setattr(sch, "today_wib", lambda: date(2026, 11, 5))   # Kamis
    before = len(mdb.marketing_tasks.docs)
    run(sch.job_auto_create_tasks_from_templates())
    assert len(mdb.marketing_tasks.docs) == before


# ══════════════════════════════════════════════════════════════════════════════
# P1-6 · Permintaan komponen CMT: catatan ubah status disimpan
# ══════════════════════════════════════════════════════════════════════════════
def test_catatan_ubah_status_komponen_cmt_disimpan(monkeypatch):
    db = FakeDB()
    db.dewi_cmt_component_requests.docs = [{"id": "r-1", "status": "pending"}]
    monkeypatch.setattr(dcr, "get_db", lambda: db)
    out = run(dcr.set_status("r-1", {"status": "cutting", "notes": "mulai shift pagi"}, USER))
    assert out["ok"] is True
    doc = db.dewi_cmt_component_requests.docs[0]
    assert doc["status"] == "cutting" and doc["status_note"] == "mulai shift pagi"
    assert "notes" in body_keys_read(dcr.set_status)
    assert "detail.status_note" in jsx("CMTComponentRequestModule.jsx")
    with pytest.raises(HTTPException):
        run(dcr.set_status("r-1", {"status": "pending"}, USER))   # mundur tetap ditolak


# ══════════════════════════════════════════════════════════════════════════════
# P1-7 · Rute yang tidak ada / body yang diabaikan
# ══════════════════════════════════════════════════════════════════════════════
def test_item_pengiriman_vendor_dari_detail_pengiriman():
    paths = {p for p, _m in route_paths(vs.router)}
    assert "/api/vendor-shipments/{sid}" in paths and "/api/vendor-shipment-items" not in paths
    src = jsx("engine/VendorProductionJobs.jsx")
    assert "/vendor-shipment-items" not in src
    assert "apiGet(`/vendor-shipments/${shipmentId}`)" in src and "data?.items" in src


def test_pembalikan_akrual_tidak_menjanjikan_tanggal_hari_ini():
    import routes.rahaza_accruals as acc
    import routes.rahaza_posting as rp
    assert ".json()" not in inspect.getsource(acc.reverse_accrual)   # server tidak membaca body
    assert "date(period_date.year, period_date.month, 1)" in inspect.getsource(rp.post_accrual_reversal)
    src = jsx("AccrualsModule.jsx")
    assert "reversal_date" not in src and "per hari ini" not in src
    assert "tanggal 1 bulan sesudah periode akrual" in src


# ══════════════════════════════════════════════════════════════════════════════
# P6 · aksi yang dulu "berhasil" walau server menolak
# ══════════════════════════════════════════════════════════════════════════════
_BARE = re.compile(r"^\s*await\s+(?:fetch|api|kpi|API)\(", re.M)


def _bare_then_success(src: str) -> list:
    """`await fetch(...)` yang hasilnya dibuang lalu (≤8 baris) toast.success / tutup popup."""
    lines = src.split("\n")
    bad = []
    for i, ln in enumerate(lines):
        if _BARE.match(ln):
            nxt = "\n".join(lines[i:i + 9])
            if re.search(r"toast\.success\(|setShow\w*\(false\)|setConfirm\w*\(null\)|fetch\w*\(\);", nxt):
                bad.append(i + 1)
    return bad


@pytest.mark.parametrize("rel", [
    "RnDCostingTab.jsx", "RnDHPPCalculatorModule.jsx", "RnDPatternModule.jsx", "RnDRevisionsTab.jsx",
    "RnDTechPackModule.jsx", "HRATSModule.jsx", "HROnboardingModule.jsx", "HRKPIModule.jsx",
    "HROrgChartModule.jsx", "UserManagementModule.jsx", "TokoCSReturnsModule.jsx", "HRLMSModule.jsx",
    "PDFConfigModule.jsx", "ReceivingModule.jsx",
])
def test_tidak_ada_sukses_tanpa_cek_jawaban_server(rel):
    src = jsx(rel)
    # seed/demo dibiarkan (bukan alur harian) — dihitung terpisah
    bad = [n for n in _bare_then_success(src) if "/seed" not in src.split("\n")[n - 1]]
    assert bad == [], f"{rel}: baris {bad}"


def test_sukses_hanya_bila_server_menerima():
    checks = {
        "AccessSyncModule.jsx": "if (!r.ok) throw new Error(j.detail",
        "PredictiveMaintenanceModule.jsx": "if (!r.ok) throw new Error(data?.detail",
        "RahazaLeaveModule.jsx": "if (!r.ok) { toast.error(",
        "UserManagementModule.jsx": "if (!(await okOrToast(r, 'Gagal menyimpan pengguna'))) return;",
        "HREmployeeModule.jsx": "if (!up) return;",
        "engine/ProductionPOModule.jsx": "PO tersimpan, tetapi aksesoris gagal disimpan",
        "MaklonBuyerCatalogModule.jsx": "tetapi varian SKU gagal dibuat",
    }
    for rel, needle in checks.items():
        assert needle in jsx(rel), rel
    src = jsx("HRATSModule.jsx")
    blk = src[src.index("const r = await api(`/candidates`, { method: 'POST'"):][:400]
    assert blk.index("if (!r.ok || !d.ok)") < blk.index("cvFile")


def test_server_menolak_tugas_tanpa_tipe_valid_tetap_400(mdb):
    """Model yang dilonggarkan tidak melonggarkan validasi handler."""
    with pytest.raises(HTTPException) as e:
        run(mt.create_task(msh.TaskCreate(task_type="lain", title="x"), _req()))
    assert e.value.status_code == 400
