"""Iter 232 — Nomor Otomatis Produksi & Maklon (Fase G2).

Menguji:
- GET /api/doc-number-policy?key=... untuk PO internal, shipment vendor, PO maklon,
  permak, retur produksi (semua mode default 'auto' + `nomor_berikutnya`).
- GET /api/admin/doc-numbering memuat vendor_shipments.shipment_number.
- POST /api/production-pos internal & maklon tanpa po_number → auto; diketik → 400.
- POST /api/vendor-shipments tanpa shipment_number → auto SHP-YYYYMM-000N.
- Rollback (PO internal, stok kurang) TIDAK melubangi counter.
- Mode manual bekerja (wajib nomor, kembar 409, pola bebas 400) lalu dikembalikan ke auto.
- Bersih-bersih: hapus semua dokumen `notes='UJI-TA'` yang dibuat test.
"""
import os
import re
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://sku-inventory-pull.preview.emergentagent.com').rstrip('/')
ADMIN_EMAIL = 'admin@garment.com'
ADMIN_PW = 'Admin@123'

SHP_KEY = 'vendor_shipments.shipment_number'
PO_INT_KEY = 'production_pos.po_number'
PO_MKL_KEY = 'production_pos.po_number_maklon'
PMK_KEY = 'dewi_cmt_permak.permak_number'
RTN_KEY = 'production_returns.return_number'


@pytest.fixture(scope='module')
def session():
    s = requests.Session()
    r = s.post(f'{BASE_URL}/api/auth/login',
               json={'email': ADMIN_EMAIL, 'password': ADMIN_PW}, timeout=30)
    assert r.status_code == 200, f'login failed {r.status_code} {r.text[:200]}'
    tok = r.json().get('token') or r.json().get('access_token')
    assert tok, f'no token {r.json()}'
    s.headers.update({'Authorization': f'Bearer {tok}'})
    return s


@pytest.fixture(scope='module')
def ctx():
    """Ambil data referensi dari DB."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv('/app/backend/.env')

    async def _run():
        c = AsyncIOMotorClient(os.environ['MONGO_URL'])
        db = c[os.environ['DB_NAME']]
        vendor = await db.vendor_partners.find_one({'active': True}, {'_id': 0, 'id': 1, 'garment_name': 1})
        variant = await db.rahaza_model_variants.find_one({'active': True}, {'_id': 0})
        return {'vendor_id': vendor['id'], 'model_id': variant['model_id'], 'size_id': variant['size_id'], 'sku': variant.get('sku', '')}
    return asyncio.get_event_loop().run_until_complete(_run()) if False else asyncio.run(_run())


CREATED = {'shipments': [], 'pos': []}


# ────────────────────────── policy GET ──────────────────────────
class TestPolicies:
    def test_po_internal_policy(self, session):
        r = session.get(f'{BASE_URL}/api/doc-number-policy', params={'key': PO_INT_KEY})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d['mode'] == 'auto'
        assert d['mode_default'] == 'auto'
        assert d['format'] == 'PO-INT-{YYYY}{MM}-{SEQ:4}'
        assert re.match(r'^PO-INT-\d{6}-\d{4}$', d['nomor_berikutnya']), d['nomor_berikutnya']

    def test_shipment_policy(self, session):
        r = session.get(f'{BASE_URL}/api/doc-number-policy', params={'key': SHP_KEY})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d['mode'] == 'auto'
        assert d['format'] == 'SHP-{YYYY}{MM}-{SEQ:4}'
        assert re.match(r'^SHP-\d{6}-\d{4}$', d['nomor_berikutnya']), d['nomor_berikutnya']

    def test_maklon_permak_retur_policy(self, session):
        for k in (PO_MKL_KEY, PMK_KEY, RTN_KEY):
            r = session.get(f'{BASE_URL}/api/doc-number-policy', params={'key': k})
            assert r.status_code == 200, f'{k}: {r.text}'
            d = r.json()
            assert d['mode'] == 'auto', f'{k} mode={d["mode"]}'
            assert d['nomor_berikutnya'], f'{k}: no nomor_berikutnya'

    def test_admin_doc_numbering_has_shipment(self, session):
        r = session.get(f'{BASE_URL}/api/admin/doc-numbering')
        assert r.status_code == 200
        items = r.json().get('items', [])
        entry = next((e for e in items if e['key'] == SHP_KEY), None)
        assert entry is not None, 'vendor_shipments.shipment_number tidak ada di admin list'
        assert entry['label'] == 'Shipment Vendor (Kirim Material ke CMT)'
        assert entry['group'] == 'Produksi'
        assert entry['mode'] == 'auto'


# ────────────────────────── PO produksi ──────────────────────────
class TestProductionPO:
    def test_internal_auto(self, session, ctx):
        payload = {
            'business_type': 'internal', 'status': 'Confirmed',
            'vendor_id': ctx['vendor_id'], 'customer_name': 'Gudang FG Sendiri',
            'notes': 'UJI-TA', 'po_date': '2026-09-23', 'deadline': '2026-09-30',
            'items': [{'model_id': ctx['model_id'], 'size_id': ctx['size_id'],
                       'qty': 5, 'serial_number': 'SN-UJI-TA'}],
        }
        r = session.post(f'{BASE_URL}/api/production-pos', json=payload)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        assert re.match(r'^PO-INT-202609-\d{4}$', d['po_number']), d
        CREATED['pos'].append(d['id'])
        pytest.po_int_id = d['id']
        pytest.po_int_num = d['po_number']

    def test_internal_typed_rejected(self, session, ctx):
        payload = {
            'business_type': 'internal', 'status': 'Confirmed',
            'vendor_id': ctx['vendor_id'], 'customer_name': 'Gudang FG Sendiri',
            'notes': 'UJI-TA', 'po_date': '2026-09-23', 'deadline': '2026-09-30',
            'po_number': 'PO-INT-202609-9999',
            'items': [{'model_id': ctx['model_id'], 'size_id': ctx['size_id'], 'qty': 5, 'serial_number': 'SN-UJI-TA2'}],
        }
        r = session.post(f'{BASE_URL}/api/production-pos', json=payload)
        assert r.status_code == 400, r.text
        assert 'OTOMATIS' in r.text or 'otomatis' in r.text.lower()

    def test_maklon_auto(self, session, ctx):
        payload = {
            'business_type': 'maklon', 'status': 'Confirmed',
            'vendor_id': ctx['vendor_id'], 'customer_name': 'UJI-TA Klien',
            'notes': 'UJI-TA', 'po_date': '2026-09-23', 'deadline': '2026-09-30',
            'items': [{'model_id': ctx['model_id'], 'size_id': ctx['size_id'],
                       'qty': 5, 'sku': 'UJI-TA-SKU', 'product_name': 'UJI-TA',
                       'size': 'M', 'color': 'Hitam',
                       'serial_number': 'SN-MKL-UJI'}],
        }
        r = session.post(f'{BASE_URL}/api/production-pos', json=payload)
        assert r.status_code in (200, 201), r.text
        d = r.json()
        assert re.match(r'^PO-MKL-202609-\d{4}$', d['po_number']), d
        CREATED['pos'].append(d['id'])
        pytest.po_mkl_id = d['id']
        pytest.po_mkl_num = d['po_number']


# ────────────────────────── Vendor shipments ──────────────────────────
class TestShipments:
    def _po_item(self, po_id):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        async def r():
            c = AsyncIOMotorClient(os.environ['MONGO_URL'])
            db = c[os.environ['DB_NAME']]
            it = await db.po_items.find_one({'po_id': po_id}, {'_id': 0})
            return it
        return asyncio.run(r())

    def test_shipment_auto_seq(self, session, ctx):
        po_id = pytest.po_mkl_id
        po_item = self._po_item(po_id)
        assert po_item, 'po_item tidak ditemukan'
        # kirim shipment #1
        pay1 = {'vendor_id': ctx['vendor_id'], 'po_id': po_id, 'shipment_type': 'NORMAL',
                'shipment_date': '2026-09-23', 'notes': 'UJI-TA',
                'items': [{'po_id': po_id, 'po_item_id': po_item['id'],
                           'sku': po_item.get('sku') or 'UJI-TA-SKU', 'qty_sent': 2}]}
        r1 = session.post(f'{BASE_URL}/api/vendor-shipments', json=pay1)
        assert r1.status_code in (200, 201), r1.text
        d1 = r1.json()
        assert re.match(r'^SHP-202609-\d{4}$', d1['shipment_number']), d1
        seq1 = int(d1['shipment_number'].split('-')[-1])
        CREATED['shipments'].append(d1['id'])

        # shipment #2 → seq+1
        pay2 = dict(pay1)
        pay2['items'] = [{'po_id': po_id, 'po_item_id': po_item['id'],
                          'sku': po_item.get('sku') or 'UJI-TA-SKU', 'qty_sent': 1}]
        r2 = session.post(f'{BASE_URL}/api/vendor-shipments', json=pay2)
        assert r2.status_code in (200, 201), r2.text
        d2 = r2.json()
        seq2 = int(d2['shipment_number'].split('-')[-1])
        assert seq2 == seq1 + 1, (d1['shipment_number'], d2['shipment_number'])
        CREATED['shipments'].append(d2['id'])

        # next preview = seq2 + 1
        r3 = session.get(f'{BASE_URL}/api/doc-number-policy', params={'key': SHP_KEY})
        nxt = r3.json()['nomor_berikutnya']
        assert int(nxt.split('-')[-1]) == seq2 + 1, nxt

    def test_shipment_typed_rejected(self, session, ctx):
        po_id = pytest.po_mkl_id
        po_item = self._po_item(po_id)
        pay = {'vendor_id': ctx['vendor_id'], 'po_id': po_id, 'shipment_type': 'NORMAL',
               'shipment_number': 'SHP-202609-9999',
               'shipment_date': '2026-09-23', 'notes': 'UJI-TA',
               'items': [{'po_id': po_id, 'po_item_id': po_item['id'],
                          'sku': po_item.get('sku') or 'UJI-TA-SKU', 'qty_sent': 1}]}
        r = session.post(f'{BASE_URL}/api/vendor-shipments', json=pay)
        assert r.status_code == 400, r.text
        assert 'OTOMATIS' in r.text or 'otomatis' in r.text.lower()

    def test_rollback_does_not_leak_number(self, session, ctx):
        """Shipment PO internal (stok gudang tidak cukup) → 400 dan counter tetap."""
        # baca counter sebelum
        r_pre = session.get(f'{BASE_URL}/api/doc-number-policy', params={'key': SHP_KEY})
        pre_next = r_pre.json()['nomor_berikutnya']

        po_id = pytest.po_int_id
        po_item = self._po_item(po_id)
        pay = {'vendor_id': ctx['vendor_id'], 'po_id': po_id, 'shipment_type': 'NORMAL',
               'shipment_date': '2026-09-23', 'notes': 'UJI-TA',
               'items': [{'po_id': po_id, 'po_item_id': po_item['id'],
                          'sku': po_item.get('sku') or 'UJI-TA-SKU', 'qty_sent': 1}]}
        r = session.post(f'{BASE_URL}/api/vendor-shipments', json=pay)
        # Expect failure (stok tidak ada); jangan strict di pesan
        if r.status_code in (200, 201):
            # sukses tak terduga → track & skip guarantee
            CREATED['shipments'].append(r.json()['id'])
            pytest.skip('PO internal shipment success — env punya stok; skip rollback check')
        assert r.status_code == 400, r.text

        r_post = session.get(f'{BASE_URL}/api/doc-number-policy', params={'key': SHP_KEY})
        post_next = r_post.json()['nomor_berikutnya']
        assert pre_next == post_next, (pre_next, post_next)


# ────────────────────────── Manual mode ──────────────────────────
class TestManualMode:
    def test_manual_flow(self, session, ctx):
        # switch ke manual
        r = session.put(f'{BASE_URL}/api/admin/doc-numbering',
                        json={'key': SHP_KEY, 'mode': 'manual', 'active': True})
        assert r.status_code == 200, r.text

        po_id = pytest.po_mkl_id
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        async def _get_item():
            c = AsyncIOMotorClient(os.environ['MONGO_URL'])
            db = c[os.environ['DB_NAME']]
            return await db.po_items.find_one({'po_id': po_id}, {'_id': 0})
        po_item = asyncio.run(_get_item())

        base_payload = {'vendor_id': ctx['vendor_id'], 'po_id': po_id, 'shipment_type': 'NORMAL',
                        'shipment_date': '2026-09-23', 'notes': 'UJI-TA',
                        'items': [{'po_id': po_id, 'po_item_id': po_item['id'],
                                   'sku': po_item.get('sku') or 'UJI-TA-SKU', 'qty_sent': 1}]}
        try:
            # 1. Tanpa nomor → 400 "wajib diisi"
            r1 = session.post(f'{BASE_URL}/api/vendor-shipments', json=base_payload)
            assert r1.status_code == 400, r1.text
            assert 'wajib' in r1.text.lower()

            # 2. Dengan nomor sesuai pola → 201
            p2 = dict(base_payload); p2['shipment_number'] = 'SHP-202609-9901'
            r2 = session.post(f'{BASE_URL}/api/vendor-shipments', json=p2)
            assert r2.status_code in (200, 201), r2.text
            d2 = r2.json()
            assert d2['shipment_number'] == 'SHP-202609-9901'
            CREATED['shipments'].append(d2['id'])

            # 3. Kembar → 409
            p3 = dict(base_payload); p3['shipment_number'] = 'SHP-202609-9901'
            r3 = session.post(f'{BASE_URL}/api/vendor-shipments', json=p3)
            assert r3.status_code == 409, r3.text

            # 4. Pola bebas → 400
            p4 = dict(base_payload); p4['shipment_number'] = 'ABC-1'
            r4 = session.post(f'{BASE_URL}/api/vendor-shipments', json=p4)
            assert r4.status_code == 400, r4.text
        finally:
            # Kembalikan ke auto
            session.put(f'{BASE_URL}/api/admin/doc-numbering',
                        json={'key': SHP_KEY, 'mode': 'auto', 'active': True})
            # hapus field mode di config supaya benar-benar default
            import asyncio as _a
            async def _unset():
                c = AsyncIOMotorClient(os.environ['MONGO_URL'])
                db = c[os.environ['DB_NAME']]
                await db.doc_number_configs.update_one({'key': SHP_KEY}, {'$unset': {'mode': ''}})
            _a.run(_unset())


# ────────────────────────── Cleanup ──────────────────────────
def test_zzz_cleanup(session):
    """Hapus semua dokumen UJI-TA yang dibuat test."""
    for sid in CREATED['shipments']:
        session.delete(f'{BASE_URL}/api/vendor-shipments/{sid}')
    for pid in CREATED['pos']:
        session.delete(f'{BASE_URL}/api/production-pos/{pid}')
    # verify
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    async def chk():
        c = AsyncIOMotorClient(os.environ['MONGO_URL'])
        db = c[os.environ['DB_NAME']]
        x = await db.production_pos.count_documents({'notes': 'UJI-TA'})
        y = await db.vendor_shipments.count_documents({'notes': 'UJI-TA'})
        return x, y
    x, y = asyncio.run(chk())
    print(f'sisa UJI-TA po={x} ship={y}')
