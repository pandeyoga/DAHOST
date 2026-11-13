# ruff: noqa: F401
"""
operations_import.py — Data Import & Template Endpoints
Endpoints: /api/import-data, /api/import-template

Refactored: Session #11.19 Phase 3.2 (extracted from operations.py 2354 LOC monolith)
"""
from routes.shared import lolos_centang  # 14 Nov 2026 (tahap 2): centang owner dihormati
import logging
from fastapi import APIRouter, Request, HTTPException
from database import get_db
from auth import require_auth, check_role, log_activity, hash_password, generate_password
from routes.shared import new_id, now, parse_date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["operations-import"])


# ─── IMPORT DATA ─────────────────────────────────────────────────────────────
@router.post("/import-data")
async def import_data(request: Request):
    user = await require_auth(request)
    if not (check_role(user, ['admin']) or lolos_centang(user)):
        raise HTTPException(403, 'Forbidden')
    db = get_db()
    body = await request.json()
    import_type = body.get('type', '')
    data_rows = body.get('data', [])
    imported = 0
    errors = []
    vendor_accounts = []
    if import_type == 'products':
        for row in data_rows:
            try:
                prod_id = new_id()
                prod = {'id': prod_id, 'product_code': row.get('product_code', ''),
                        'product_name': row.get('product_name', ''), 'category': row.get('category', ''),
                        'cmt_price': float(row.get('cmt_price', 0) or 0),
                        'selling_price': float(row.get('selling_price', 0) or 0),
                        'status': 'active', 'created_at': now(), 'updated_at': now()}
                await db.products.insert_one(prod)
                # Import variants if provided
                for v in row.get('variants', []):
                    await db.product_variants.insert_one({
                        'id': new_id(), 'product_id': prod_id,
                        'product_code': prod['product_code'], 'product_name': prod['product_name'],
                        'sku': v.get('sku', ''), 'size': v.get('size', ''), 'color': v.get('color', ''),
                        'status': 'active', 'created_at': now()})
                imported += 1
            except Exception as e:
                errors.append(f"Row {imported+1}: {str(e)}")
    elif import_type == 'garments':
        for row in data_rows:
            try:
                gid = new_id()
                code_slug = (row.get('garment_code', gid)).lower()
                code_slug = ''.join(c for c in code_slug if c.isalnum())
                email = f"vendor.{code_slug}@garment.com"
                raw_pw = generate_password(10)
                await db.users.insert_one({'id': new_id(), 'name': row.get('garment_name', ''),
                    'email': email, 'password': hash_password(raw_pw), 'role': 'vendor',
                    'vendor_id': gid, 'status': 'active', 'created_at': now(), 'updated_at': now()})
                # 2026-11-07 KEAMANAN: sandi awal TIDAK disimpan teks biasa (dulu `vendor_password_plain`).
                # Ditampilkan SEKALI di respons impor (`vendor_accounts`), sama seperti POST /api/garments.
                row = {k: v for k, v in row.items() if 'password' not in str(k).lower()}
                await db.garments.insert_one({'id': gid, **row, 'status': 'active',
                    'login_email': email, 'created_at': now(), 'updated_at': now()})
                vendor_accounts.append({'garment_id': gid, 'garment_name': row.get('garment_name', ''),
                                        'email': email, 'password': raw_pw})
                imported += 1
            except Exception as e:
                errors.append(f"Row {imported+1}: {str(e)}")
    elif import_type == 'production-pos':
        # 2026-11-06 (T6): jalur lama ini menulis PO Draf tanpa validasi master (vendor `garments`,
        # item tanpa model/varian) dan layar mengirim FormData ke endpoint JSON ini sehingga tidak
        # pernah berhasil. Impor PO kini SATU jalur: Data Transfer `po_berjalan` (pratinjau per baris,
        # PO dikonfirmasi lewat jalur PO resmi + surat jalan saldo awal).
        raise HTTPException(410, detail={
            "deprecated": True,
            "use": "/api/data-transfer/import/po_berjalan",
            "message": "Impor PO lewat tombol Impor PO berjalan (Data Transfer) di layar PO Produksi.",
        })
    elif import_type == 'accessories':
        # DEPRECATED Sprint A.0 — redirect to rahaza_materials (type='accessory')
        logger.warning("[DEPRECATED-NOOP] import accessories — use /api/acc/items instead")
        raise HTTPException(410, detail={
            "deprecated": True,
            "use": "/api/acc/items (POST)",
            "message": "Import accessories via legacy collection is deprecated. Use /api/acc/items with type='accessory'."
        })
    else:
        raise HTTPException(400, f"Unknown import type: {import_type}")
    await log_activity(user['id'], user['name'], 'Import', import_type, f"Imported {imported} records")
    out = {'imported': imported, 'errors': errors, 'type': import_type}
    if vendor_accounts:
        out['vendor_accounts'] = vendor_accounts  # sekali tampil; tidak disimpan di DB
    return out


@router.get("/import-template")
async def import_template(request: Request):
    await require_auth(request)
    ttype = request.query_params.get('type', '')
    templates = {
        'products': {'columns': ['product_code', 'product_name', 'category', 'cmt_price', 'selling_price'],
                     'variant_columns': ['sku', 'size', 'color'], 'example': {'product_code': 'PRD-001', 'product_name': 'T-Shirt Basic', 'category': 'Shirt', 'cmt_price': 5000, 'selling_price': 15000}},
        'garments': {'columns': ['garment_code', 'garment_name', 'location', 'contact_person', 'phone', 'monthly_capacity'],
                     'example': {'garment_code': 'VND-001', 'garment_name': 'PT Garmen Jaya', 'location': 'Jakarta', 'contact_person': 'Budi', 'phone': '08123456789'}},
        'production-pos': {'columns': ['po_number', 'customer_name', 'vendor_id', 'po_date', 'deadline', 'notes'],
                           'item_columns': ['product_name', 'sku', 'size', 'color', 'serial_number', 'qty', 'selling_price', 'cmt_price'],
                           'example': {'po_number': 'PO-001', 'customer_name': 'Buyer Corp'}},
        'accessories': {'columns': ['code', 'name', 'category', 'unit', 'description'],
                        'example': {'code': 'ACC-001', 'name': 'Kancing', 'category': 'Trimming', 'unit': 'pcs'}},
    }
    if ttype not in templates:
        return {'available_types': list(templates.keys())}
    return templates[ttype]
