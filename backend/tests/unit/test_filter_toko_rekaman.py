"""Filter toko Marketing menyeluruh (owner, 14 Nov 2026: "penerapan filtering berdasarkan toko di marketing
belum sepenuhnya").

Kasus nyata: PIC Mar'atus membuat kreator FATMALA FASHION yang ditautkan ke tokonya (OB) DAN ke toko Rina,
sehingga kreator itu muncul di akun Rina; daftar kreator sama sekali tidak disaring, dan rute ber-id
(`/orders/{id}`, `/kol/creators/{id}`, …) tidak pernah memeriksa toko rekamannya.

Yang diuji:
1. GERBANG CAKUPAN — setiap rute ber-parameter di `/api/marketing` & `/api/dewi/kreator-requests` (dibaca
   dari sumber lewat AST, tanpa mengimpor server) wajib ada di `core.marketing_record_scope.ATURAN` atau
   `BEBAS` (dengan alasan). Rute baru yang lupa didaftarkan membuat uji ini gagal.
2. Daftar kreator tersaring; mengubah kreator bersama mempertahankan tautan PIC lain.
3. Rekaman toko lain → 404 (tanpa membocorkan keberadaannya); peran semua-toko tidak berubah.
4. Middleware: peran buatan owner bernama "PIC Toko" ikut dijaga, alias `/api/v1/marketing` juga.
"""
import ast
import asyncio
import glob
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("JWT_SECRET", "uji-hermetik-secret")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "uji")

from fastapi import HTTPException  # noqa: E402

from _fake_mongo import FakeDB, FakeRequest  # noqa: E402
from core import marketing_account_scope as scope  # noqa: E402
from core import marketing_record_scope as rekaman  # noqa: E402

ROUTES = BACKEND / "routes"
METODE = {"get", "post", "put", "patch", "delete"}


# ══ 1. GERBANG CAKUPAN ══════════════════════════════════════════════════════
def _prefix_router(call):
    if not isinstance(call, ast.Call):
        return None
    f = call.func
    nama = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
    if nama != "APIRouter":
        return None
    for kw in call.keywords:
        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return ""


def rute_sumber():
    """{(METODE, pola lengkap)} dari dekorator `@router.<metode>(...)` + `APIRouter(prefix=...)`, termasuk
    router yang diimpor dari berkas lain (`from routes.marketing_kol_shared import router`)."""
    berkas = sorted(glob.glob(str(ROUTES / "marketing_*.py"))) + [str(ROUTES / "dewi_kreator_requests.py")]
    pohon, router, impor = {}, {}, {}
    for p in berkas:
        mod = os.path.basename(p)[:-3]
        t = ast.parse(open(p, encoding="utf-8").read())
        pohon[mod], router[mod], impor[mod] = t, {}, {}
        for node in t.body:
            if isinstance(node, ast.Assign):
                pre = _prefix_router(node.value)
                if pre is not None:
                    for tg in node.targets:
                        if isinstance(tg, ast.Name):
                            router[mod][tg.id] = pre
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("routes."):
                for a in node.names:
                    impor[mod][a.asname or a.name] = (node.module.split(".", 1)[1], a.name)

    def prefix(mod, nama, dalam=0):
        if nama in router.get(mod, {}):
            return router[mod][nama]
        if dalam < 5 and nama in impor.get(mod, {}):
            return prefix(*impor[mod][nama], dalam + 1)
        return None

    out = set()
    for mod, t in pohon.items():
        for node in ast.walk(t):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in METODE
                        and isinstance(d.func.value, ast.Name) and d.args and isinstance(d.args[0], ast.Constant)):
                    pre = prefix(mod, d.func.value.id)
                    if pre is not None:
                        out.add((d.func.attr.upper(), pre + str(d.args[0].value)))
    return out


def _rute_berparameter():
    return sorted((m, p) for m, p in rute_sumber() if "{" in p and rekaman.dijaga(p))


def test_semua_rute_berparameter_dijaga_atau_dibebaskan():
    rute = _rute_berparameter()
    pola = {p for _, p in rute}
    # pembaca AST tidak boleh diam-diam berhenti melihat rute
    assert len(rute) >= 190, len(rute)
    for wajib in ("/api/marketing/orders/{order_id}", "/api/marketing/kol/creators/{creator_id}",
                  "/api/marketing/livehost/{host_id}", "/api/dewi/kreator-requests/{request_id}",
                  "/api/marketing/catalogs/{catalog_id}/items/{item_id}"):
        assert wajib in pola, wajib
    lupa = sorted({f"{m} {p}  →  {kunci}" for m, p in rute for _, kunci in rekaman.parameter_rute(p)
                   if kunci not in rekaman.ATURAN and kunci not in rekaman.BEBAS})
    assert not lupa, ("Rute ber-id baru belum didaftarkan di core.marketing_record_scope (ATURAN = cara "
                      "menemukan tokonya, atau BEBAS + alasan):\n" + "\n".join(lupa))


def test_tidak_ada_aturan_basi_dan_alasan_bebas_terisi():
    kunci_dipakai = {k for _, p in _rute_berparameter() for _, k in rekaman.parameter_rute(p)}
    basi = sorted(set(rekaman.kunci_tabel()) - kunci_dipakai)
    assert not basi, f"kunci tabel tanpa rute: {basi}"
    assert not set(rekaman.ATURAN) & set(rekaman.BEBAS)
    assert all(len(alasan) > 20 for alasan in rekaman.BEBAS.values())


# ══ DATA UJI ════════════════════════════════════════════════════════════════
MARATUS = {"id": "u-maratus", "name": "Mar'atus", "email": "maratus@x.id", "role": "pic_toko", "status": "active"}
RINA = {"id": "u-rina", "name": "Rina", "email": "rina@x.id", "role": "PIC Toko", "status": "active"}
OWNER = {"id": "u-owner", "name": "Owner", "email": "owner@x.id", "role": "owner", "status": "active"}
SPV = {"id": "u-spv", "name": "SPV", "email": "spv@x.id", "role": "spv_marketing", "status": "active"}
KONTEN = {"id": "u-konten", "name": "Konten", "email": "konten@x.id", "role": "Content Creator", "status": "active"}
RND = {"id": "u-rnd", "name": "RnD", "email": "rnd@x.id", "role": "rnd_staff", "status": "active"}


def _db():
    db = FakeDB()
    db.users.docs = [dict(u) for u in (MARATUS, RINA, OWNER, SPV, KONTEN, RND)]
    db.marketing_platform_accounts.docs = [
        {"id": "a-ob", "account_name": "Shopee OB", "account_code": "OB-SHP", "status": "active",
         "pic_user_id": "u-maratus"},
        {"id": "a-rina", "account_name": "TikTok Daluna", "account_code": "DL-TTK", "status": "active",
         "pic_user_id": "u-rina"},
        {"id": "a-lain", "account_name": "Shopee GHS", "account_code": "GHS-SHP", "status": "active"},
    ]
    db.marketing_kol_creators.docs = [
        {"id": "c-fatmala", "name": "FATMALA FASHION", "creator_code": "KOL-FAT", "status": "active",
         "assigned_account_ids": ["a-ob", "a-rina"], "created_at": "2026-11-14"},
        {"id": "c-ob", "name": "Kreator OB", "creator_code": "KOL-OB", "status": "active",
         "assigned_account_ids": ["a-ob"], "created_at": "2026-11-13"},
        {"id": "c-rina", "name": "Kreator Rina", "creator_code": "KOL-RN", "status": "active",
         "assigned_account_ids": ["a-rina"], "created_at": "2026-11-12"},
        {"id": "c-bebas", "name": "Belum ditugaskan", "creator_code": "KOL-BB", "status": "active",
         "assigned_account_ids": [], "created_at": "2026-11-11"},
    ]
    db.marketing_orders.docs = [
        {"id": "o-ob", "order_id": "SHP-1", "account_id": "a-ob"},
        {"id": "o-rina", "order_id": "TTK-1", "account_id": "a-rina"},
    ]
    db.marketing_returns.docs = [{"id": "r-ob", "account_id": "a-ob", "status": "pending"}]
    db.marketing_product_launches.docs = [
        {"id": "l-ob", "account_id": "a-ob", "target_account_ids": ["a-ob", "a-rina"]},
    ]
    db.marketing_catalogs.docs = [{"id": "k-ob", "account_id": "a-ob"}, {"id": "k-rina", "account_id": "a-rina"}]
    db.marketing_catalog_bulk_runs.docs = [{"id": "run-1", "catalog_ids": ["k-ob", "k-rina"]}]
    db.marketing_livehost_scripts.docs = [{"id": "s-global", "account_id": None}, {"id": "s-ob", "account_id": "a-ob"}]
    db.marketing_livehosts.docs = [{"id": "h-ob", "name": "Host OB", "assigned_account_ids": ["a-ob"]}]
    return db


def _run(coro):
    return asyncio.run(coro)


def _vis(db, user):
    return _run(scope.visible_account_ids(db, user))


# ══ 2. KREATOR: daftar tersaring + tautan bersama dipertahankan ══════════════
def _kc(monkeypatch, db, user):
    import auth
    import routes.marketing_kol_creators as kc

    async def _auth(req):
        req.state.user = user
        return user
    monkeypatch.setattr(kc, "require_auth", _auth)
    monkeypatch.setattr(kc, "get_db", lambda: db)
    monkeypatch.setattr(auth, "get_db", lambda: db)
    return kc


def test_peran_kustom_pic_toko_berlingkup():
    db = _db()
    assert scope.berlingkup_toko(RINA)                      # "PIC Toko" → pic_toko
    assert _vis(db, RINA) == ["a-rina"]
    assert _run(scope.toko_lingkup(db, RND)) is None        # peran lain: daftar lama tidak disaring
    assert _run(scope.toko_lingkup(db, OWNER)) is None


def test_daftar_kreator_rina_tidak_memuat_kreator_toko_mar_atus(monkeypatch):
    db = _db()
    kc = _kc(monkeypatch, db, RINA)
    out = _run(kc.list_creators(FakeRequest(), status=None, account_id=None, page=1, limit=20))
    by = {c["id"]: c for c in out["creators"]}
    assert set(by) == {"c-fatmala", "c-rina"}               # c-ob (hanya toko OB) & c-bebas tidak tampil
    assert by["c-fatmala"]["assigned_account_ids"] == ["a-rina"]   # tautan toko OB tidak ditampilkan
    # meminta toko orang lain lewat filter → kosong, bukan bocor
    out = _run(kc.list_creators(FakeRequest(), status=None, account_id="a-ob", page=1, limit=20))
    assert out["creators"] == []


def test_peran_semua_toko_melihat_semua_kreator(monkeypatch):
    for user in (OWNER, SPV, KONTEN):
        db = _db()
        kc = _kc(monkeypatch, db, user)
        out = _run(kc.list_creators(FakeRequest(), status=None, account_id=None, page=1, limit=20))
        assert len(out["creators"]) == 4, user["role"]
        fat = next(c for c in out["creators"] if c["id"] == "c-fatmala")
        assert fat["assigned_account_ids"] == ["a-ob", "a-rina"]


def test_rina_mengubah_kreator_bersama_tautan_mar_atus_tetap(monkeypatch):
    from routes.marketing_kol_shared import CreatorUpdate
    db = _db()
    kc = _kc(monkeypatch, db, RINA)
    # layar Rina hanya menampilkan tokonya → body hanya berisi a-rina
    _run(kc.update_creator("c-fatmala", CreatorUpdate(assigned_account_ids=["a-rina"], notes="x"), FakeRequest()))
    assert db.marketing_kol_creators.docs[0]["assigned_account_ids"] == ["a-ob", "a-rina"]
    # Rina melepas tokonya sendiri → tautan Mar'atus tetap ada
    _run(kc.update_creator("c-fatmala", CreatorUpdate(assigned_account_ids=[]), FakeRequest()))
    assert db.marketing_kol_creators.docs[0]["assigned_account_ids"] == ["a-ob"]
    # menautkan toko yang tidak dipegang → 403 dengan nama tokonya
    with pytest.raises(HTTPException) as e:
        _run(kc.update_creator("c-rina", CreatorUpdate(assigned_account_ids=["a-rina", "a-lain"]), FakeRequest()))
    assert e.value.status_code == 403 and "Shopee GHS" in e.value.detail


def test_mar_atus_tidak_bisa_menautkan_kreator_ke_toko_rina(monkeypatch):
    from routes.marketing_kol_shared import CreatorCreate
    db = _db()
    kc = _kc(monkeypatch, db, MARATUS)
    with pytest.raises(HTTPException) as e:
        _run(kc.create_creator(CreatorCreate(name="Baru", creator_code="KOL-NEW",
                                             assigned_account_ids=["a-ob", "a-rina"]), FakeRequest()))
    assert e.value.status_code == 403 and "TikTok Daluna" in e.value.detail
    with pytest.raises(HTTPException) as e:
        _run(kc.create_creator(CreatorCreate(name="Baru", creator_code="KOL-NEW"), FakeRequest()))
    assert e.value.status_code == 400                       # tanpa toko → hilang dari daftarnya sendiri
    _run(kc.create_creator(CreatorCreate(name="Baru", creator_code="KOL-NEW",
                                         assigned_account_ids=["a-ob"]), FakeRequest()))
    assert db.marketing_kol_creators.docs[-1]["assigned_account_ids"] == ["a-ob"]


def test_manajer_marketing_mengganti_tautan_apa_adanya(monkeypatch):
    from routes.marketing_kol_shared import CreatorUpdate
    db = _db()
    kc = _kc(monkeypatch, db, SPV)
    _run(kc.update_creator("c-fatmala", CreatorUpdate(assigned_account_ids=["a-lain"]), FakeRequest()))
    assert db.marketing_kol_creators.docs[0]["assigned_account_ids"] == ["a-lain"]


# ══ 3. PENJAGA REKAMAN: satu tabel ═══════════════════════════════════════════
def _cek(db, user, metode, pola, **params):
    return _run(rekaman.periksa_rute(db, _vis(db, user), metode, pola, params))


def test_rekaman_toko_lain_dijawab_404():
    db = _db()
    o = "/api/marketing/orders/{order_id}"
    t = _cek(db, RINA, "GET", o, order_id="o-ob")
    assert t and t.status == 404 and t.detail == rekaman.PESAN_TIDAK_ADA
    assert _cek(db, RINA, "GET", o, order_id="SHP-1").status == 404       # nomor pesanan marketplace juga
    assert _cek(db, RINA, "GET", o, order_id="o-rina") is None
    assert _cek(db, RINA, "PATCH", o + "/status", order_id="o-ob").status == 404
    assert _cek(db, RINA, "GET", o, order_id="tidak-ada") is None          # 404 urusan route
    k = "/api/marketing/kol/creators/{creator_id}"
    assert _cek(db, RINA, "GET", k, creator_id="c-ob").status == 404
    assert _cek(db, RINA, "PUT", k, creator_id="c-fatmala") is None        # kreator bersama boleh diubah
    assert _cek(db, RINA, "GET", k, creator_id="c-bebas").status == 404
    assert _cek(db, RINA, "PUT", "/api/marketing/kol/creators/{creator_id}/incentive",
                creator_id="c-ob").status == 404
    assert _cek(db, RINA, "GET", "/api/marketing/livehost/{host_id}", host_id="h-ob").status == 404


def test_aturan_khusus_tabel():
    db = _db()
    pl = "/api/marketing/product-launches/{launch_id}"
    assert _cek(db, RINA, "GET", "/api/marketing/product-launches/{launch_id}", launch_id="l-ob") is None
    assert _cek(db, RINA, "PUT", pl, launch_id="l-ob").status == 404       # sasaran tidak boleh mengubah
    assert _cek(db, MARATUS, "PUT", pl, launch_id="l-ob") is None
    run = "/api/marketing/catalog-tools/runs/{run_id}/undo"
    assert _cek(db, RINA, "POST", run, run_id="run-1").status == 404       # menyentuh katalog toko lain
    sc = "/api/marketing/livehost/scripts/{script_id}"
    assert _cek(db, RINA, "GET", sc, script_id="s-global") is None          # skrip global milik bersama
    assert _cek(db, RINA, "GET", sc, script_id="s-ob").status == 404
    assert _cek(db, RINA, "GET", "/api/marketing/webhooks/events/{event_id}", event_id="e1").status == 403
    t = _cek(db, RINA, "POST", "/api/marketing/accounts/{account_key}/sync", account_key="OB-SHP")
    assert t.status == 403 and "Shopee OB" in t.detail                      # kode toko, bukan hanya id
    assert _cek(db, RINA, "POST", "/api/marketing/accounts/{account_key}/sync", account_key="DL-TTK") is None


def test_rujukan_kreator_di_body():
    db = _db()
    vis = _vis(db, RINA)
    assert _run(rekaman.periksa_rujukan(db, vis, {"creator_id": "c-ob"}, "/api/marketing/kol/sessions")).status == 403
    assert _run(rekaman.periksa_rujukan(db, vis, {"creator_id": "c-fatmala"})) is None
    assert _run(rekaman.periksa_rujukan(db, vis, {"creator_id": "c-bebas"})) is None    # belum milik toko
    assert _run(rekaman.periksa_rujukan(db, vis, {"host_ids": ["h-ob"]})).status == 403
    assert _run(rekaman.periksa_rujukan(db, vis, {"creator_id": "c-ob"}, "/api/marketing/samples")) is None


def test_aksi_tugas_tidak_bisa_menyentuh_retur_toko_lain():
    import routes.marketing_tasks as mt
    db = _db()
    with pytest.raises(HTTPException) as e:
        _run(mt._assert_related_visible(db, RINA, "marketing_returns", "r-ob", "Return"))
    assert e.value.status_code == 404
    _run(mt._assert_related_visible(db, MARATUS, "marketing_returns", "r-ob", "Return"))
    _run(mt._assert_related_visible(db, OWNER, "marketing_returns", "r-ob", "Return"))


# ══ 4. MIDDLEWARE ujung ke ujung ═════════════════════════════════════════════
@pytest.fixture
def klien(monkeypatch):
    import auth
    import database
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from middleware.marketing_scope_guard import MarketingScopeGuardMiddleware

    db = _db()
    monkeypatch.setattr(auth, "get_db", lambda: db)
    monkeypatch.setattr(database, "get_db", lambda: db)
    auth.bump_rbac_cache()
    app = FastAPI()

    @app.get("/api/marketing/orders/{order_id}")
    async def _order(order_id: str):
        return {"ok": True, "order_id": order_id}

    @app.post("/api/marketing/kol/sessions")
    async def _sesi(body: dict):
        return {"ok": True}

    # urutan sama dengan server.py: penerjemah /api/v1 di DALAM penjaga lingkup toko
    from middleware.api_v1 import APIv1PathRewriteMiddleware
    app.add_middleware(APIv1PathRewriteMiddleware)
    app.add_middleware(MarketingScopeGuardMiddleware)
    c = TestClient(app)

    def panggil(user, metode, url, **kw):
        h = {"Authorization": f"Bearer {auth.create_token(user)}"}
        return c.request(metode, url, headers=h, **kw)
    yield panggil
    auth.bump_rbac_cache()


def test_middleware_peran_pic_toko_kustom_dijaga(klien):
    r = klien(RINA, "GET", "/api/marketing/orders/o-ob")
    assert r.status_code == 404 and r.json()["detail"] == rekaman.PESAN_TIDAK_ADA
    assert klien(RINA, "GET", "/api/marketing/orders/o-rina").status_code == 200
    # alias v1 dulu melewati penjaga
    assert klien(RINA, "GET", "/api/v1/marketing/orders/o-rina").status_code == 200
    r = klien(RINA, "GET", "/api/v1/marketing/orders/o-ob")
    assert r.status_code == 404 and r.json().get("scope_guard") is True
    assert klien(RINA, "POST", "/api/marketing/kol/sessions", json={"creator_id": "c-ob"}).status_code == 403
    assert klien(RINA, "POST", "/api/marketing/kol/sessions",
                 json={"creator_id": "c-fatmala", "account_id": "a-rina"}).status_code == 200
    assert klien(RINA, "POST", "/api/marketing/kol/sessions",
                 json={"creator_id": "c-fatmala", "account_id": "a-ob"}).status_code == 403


def test_middleware_peran_semua_toko_tidak_berubah(klien):
    for user in (OWNER, SPV, KONTEN, MARATUS):
        assert klien(user, "GET", "/api/marketing/orders/o-ob").status_code == 200, user["role"]
    assert klien(OWNER, "POST", "/api/marketing/kol/sessions", json={"creator_id": "c-ob"}).status_code == 200
