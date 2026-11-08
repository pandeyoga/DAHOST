"""
CV. Dewi Aditya — System Configuration API
Generic key/value settings stored in MongoDB, editable via UI.

Used for:
- Maklon: QC reject threshold, invoice prefix, tax %, payment terms default
- Notifications: WA/Telegram bot tokens, channels (configurable, NOT hardcoded)
- Marketplace: Shopee/Tokopedia API credentials (configurable)

Collection: dewi_system_config
Schema: { key, value, category, label, description, data_type, is_secret, updated_at, updated_by }
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime, timezone
from database import get_db
from auth import require_auth
from core.authz import only
from core.roles import SYSTEM_CONFIG_ROLES

router = APIRouter(prefix='/api/dewi/system/config', tags=['Dewi-System-Config'])

# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT CONFIG SCHEMA (for initial render in UI)
# ══════════════════════════════════════════════════════════════════════════════

# 2026-11-03 (saklar PKP): kunci yang PENSIUN — tidak dibaca kode lagi & disembunyikan dari daftar.
# `maklon_tax_pct` (PPN invoice maklon 11%) digantikan Status Pajak perusahaan (core.tax_status):
# non-PKP tidak memungut PPN, PKP = 12% × DPP 11/12. Dokumen lama di DB dibiarkan (tidak dihapus).
# 2026-11-06 (pola P5): `hpp_overhead_pct` (15%) PENSIUN — keputusan owner: overhead pabrik tidak masuk HPP, dan
# tidak ada kode yang membacanya; setelan yang tampil hanya menyesatkan.
# 2026-11-07 (Tahap 6, SY4): `notification_whatsapp_provider` PENSIUN — tidak dibaca kode mana pun; notifikasi
# WhatsApp memakai Fonnte (Pusat Notifikasi), jadi pilihan "twilio | waba_cloud | wabots" hanya menyesatkan.
RETIRED_KEYS = {'maklon_tax_pct', 'hpp_overhead_pct', 'notification_whatsapp_provider'}

# 2026-11-07 (Tahap 5, audit form) — setelan teks yang nilainya HARUS salah satu kode tetap.
# Dulu diketik bebas ("30 hari" untuk termin) sehingga pembaca kode (`TERM_DAYS`) diam-diam jatuh
# ke nilai cadangan. Pilihan dikirim ke layar (`choices`) dan nilai lain ditolak saat disimpan.
CONFIG_CHOICES = {
    'maklon_payment_terms_default': [
        {'value': 'net_7', 'label': '7 hari setelah tagihan'},
        {'value': 'net_14', 'label': '14 hari setelah tagihan'},
        {'value': 'net_30', 'label': '30 hari setelah tagihan'},
        {'value': 'net_60', 'label': '60 hari setelah tagihan'},
    ],
}


def choice_error(key: str, value) -> Optional[str]:
    """Pesan galat bila `value` bukan salah satu pilihan setelan `key` (None = sah)."""
    if key == 'intercompany_accessory_margin_pct':   # Tahap 8 fase 2: persen 0–100
        from core.intercompany import parse_margin
        try:
            parse_margin(value)
        except ValueError as e:
            return str(e)
        return None
    choices = CONFIG_CHOICES.get(key)
    if not choices:
        return None
    allowed = [c['value'] for c in choices]
    if str(value) in allowed:
        return None
    return ('nilai harus salah satu dari: '
            + ', '.join(c['label'] for c in choices))

DEFAULT_CONFIGS = [
    # 2026-09-24 — gate GDG-2 (progress produksi internal wajib MI issued) bisa dimatikan.
    {
        'key': 'production_require_material_issued',
        'value': False,
        'category': 'production',
        'label': 'Progress Produksi Wajib Material Issue "issued" (GDG-2)',
        'description': ('ON: Input progress job produksi INTERNAL ditolak bila gudang belum menyerahkan '
                        'material (Material Issue belum berstatus issued). OFF (bawaan sementara): '
                        'progress boleh diinput tanpa Material Issue.'),
        'data_type': 'boolean',
        'is_secret': False,
    },
    # 2026-09-23 — mode SEMENTARA: klien belum stock opname, produksi harus jalan.
    {
        'key': 'inventory_allow_negative',
        'value': True,
        'category': 'inventory',
        'label': 'Stok Boleh Minus (sementara, sebelum opname)',
        'description': ('ON: Kirim Material CMT, Pengeluaran Material, dan Cutting tetap jalan '
                        'walau stok kurang/belum ada baris — stok dipotong sampai minus dan '
                        'baris dibuat di gudang bawaan (A-* → Ruang Aksesoris, lainnya → gudang bahan). '
                        'Matikan setelah stock opname selesai agar aturan ketat kembali.'),
        'data_type': 'boolean',
        'is_secret': False,
    },
    # Maklon / Invoice / QC
    {
        'key': 'maklon_invoice_prefix',
        'value': 'INV-MKL',
        'category': 'maklon',
        'label': 'Prefix Invoice Maklon',
        'description': 'Prefix untuk nomor invoice order maklon. Contoh INV-MKL → INV-MKL-2026-0001',
        'data_type': 'string',
        'is_secret': False,
    },
    {
        'key': 'maklon_payment_terms_default',
        'value': 'net_30',
        'category': 'maklon',
        'label': 'Payment Terms Default',
        'description': 'Termin pembayaran bawaan invoice maklon (jatuh tempo setelah tagihan terbit).',
        'data_type': 'string',
        'is_secret': False,
    },
    # Tahap 8 fase 2 (keputusan owner K5): aksesoris DA untuk PO maklon dijual ke CV Sukma seharga HPP + margin ini.
    # Hanya admin/owner/superadmin yang bisa mengubah (SYSTEM_CONFIG_ROLES, sama dengan setelan sistem lain).
    {
        'key': 'intercompany_accessory_margin_pct',
        'value': 0.0,
        'category': 'maklon',
        'label': 'Margin Aksesoris ke CV Sukma (%)',
        'description': ('Aksesoris/bahan CV Dewi Aditya yang dipakai pesanan maklon dijual ke CV Sukma seharga harga '
                        'pokok (rata-rata) ditambah margin ini. 0 = seharga pokok. Berlaku untuk nota aksesoris berikutnya.'),
        'data_type': 'number',
        'is_secret': False,
    },
    {
        'key': 'maklon_qc_reject_threshold_pct',
        'value': 5.0,
        'category': 'maklon',
        'label': 'QC Reject Threshold (%)',
        'description': 'Ambang batas reject rate QC maklon. Di atas nilai ini akan memicu alert',
        'data_type': 'number',
        'is_secret': False,
    },
    # CMT Operasional (Maklon CMT Operasional Plan — Fase 0 fondasi)
    {
        'key': 'maklon_cmt_buffer_days',
        'value': 3,
        'category': 'maklon',
        'label': 'Buffer Target CMT (hari)',
        'description': 'Selisih hari antara Deadline Mitra/Buyer (delivery_deadline) dan Target CMT. '
                       'Target CMT = delivery_deadline − buffer. Dipakai monitoring KEJAR CMT.',
        'data_type': 'number',
        'is_secret': False,
    },
    {
        'key': 'maklon_cmt_late_grace_days',
        'value': 5,
        'category': 'maklon',
        'label': 'Grace Telat CMT (hari, H+N)',
        'description': 'Ambang "TELAT": job dianggap telat bila melewati Target CMT lebih dari N hari '
                       '(mis. H+5). Di bawahnya berstatus "mendekati deadline".',
        'data_type': 'number',
        'is_secret': False,
    },
    {
        'key': 'maklon_permak_return_grace_days',
        'value': 3,
        'category': 'maklon',
        'label': 'Grace Kembali Permak (hari, H+N)',
        'description': 'Penanda H+N untuk permak/retur ke CMT: bila melewati return_deadline lebih dari N hari, '
                       'permak ditandai perlu tindakan (mis. H+3).',
        'data_type': 'number',
        'is_secret': False,
    },

    # HPP (2026-11-06: `hpp_overhead_pct` dicabut — overhead tidak masuk HPP, lihat RETIRED_KEYS)
    {
        'key': 'hpp_profit_margin_pct',
        'value': 20.0,
        'category': 'hpp',
        'label': 'Target Margin Profit (%)',
        'description': 'Target margin profit default untuk kalkulasi harga jual',
        'data_type': 'number',
        'is_secret': False,
    },

    # Notifications (configurable, not hardcoded)
    {
        'key': 'notification_whatsapp_enabled',
        'value': False,
        'category': 'notification',
        'label': 'Aktifkan Notifikasi WhatsApp',
        'description': 'Enable/disable integrasi WhatsApp (Twilio/WABA) untuk notifikasi',
        'data_type': 'boolean',
        'is_secret': False,
    },
    # `notification_whatsapp_provider` dicabut 2026-11-07 (SY4) — lihat RETIRED_KEYS.
    {
        'key': 'notification_whatsapp_api_key',
        'value': '',
        'category': 'notification',
        'label': 'WhatsApp API Key / Token',
        'description': 'Token atau Auth Key provider WhatsApp',
        'data_type': 'string',
        'is_secret': True,
    },
    {
        'key': 'notification_whatsapp_sender',
        'value': '',
        'category': 'notification',
        'label': 'Nomor / Sender WhatsApp',
        'description': 'Nomor sender terdaftar, contoh whatsapp:+6281xxxxxxx',
        'data_type': 'string',
        'is_secret': False,
    },
    {
        'key': 'notification_telegram_enabled',
        'value': False,
        'category': 'notification',
        'label': 'Aktifkan Notifikasi Telegram',
        'description': 'Enable/disable Telegram Bot untuk notifikasi',
        'data_type': 'boolean',
        'is_secret': False,
    },
    {
        'key': 'notification_telegram_bot_token',
        'value': '',
        'category': 'notification',
        'label': 'Telegram Bot Token',
        'description': 'Token dari @BotFather',
        'data_type': 'string',
        'is_secret': True,
    },
    {
        'key': 'notification_telegram_chat_id',
        'value': '',
        'category': 'notification',
        'label': 'Telegram Chat ID Default',
        'description': 'Chat ID tujuan notifikasi (grup/user)',
        'data_type': 'string',
        'is_secret': False,
    },

    # Marketplace integration (Phase 5 — configurable di sini supaya tidak hardcode)
    {
        'key': 'marketplace_shopee_enabled',
        'value': False,
        'category': 'marketplace',
        'label': 'Aktifkan Integrasi Shopee',
        'description': 'Enable Shopee Open API',
        'data_type': 'boolean',
        'is_secret': False,
    },
    {
        'key': 'marketplace_shopee_partner_id',
        'value': '',
        'category': 'marketplace',
        'label': 'Shopee Partner ID',
        'description': 'Partner ID dari Shopee Open Platform',
        'data_type': 'string',
        'is_secret': False,
    },
    {
        'key': 'marketplace_shopee_partner_key',
        'value': '',
        'category': 'marketplace',
        'label': 'Shopee Partner Key',
        'description': 'Partner Key (secret) dari Shopee Open Platform',
        'data_type': 'string',
        'is_secret': True,
    },
    {
        'key': 'marketplace_tokopedia_enabled',
        'value': False,
        'category': 'marketplace',
        'label': 'Aktifkan Integrasi Tokopedia',
        'description': 'Enable Tokopedia API',
        'data_type': 'boolean',
        'is_secret': False,
    },
    {
        'key': 'marketplace_tokopedia_client_id',
        'value': '',
        'category': 'marketplace',
        'label': 'Tokopedia Client ID',
        'description': 'Client ID aplikasi Tokopedia',
        'data_type': 'string',
        'is_secret': False,
    },
    {
        'key': 'marketplace_tokopedia_client_secret',
        'value': '',
        'category': 'marketplace',
        'label': 'Tokopedia Client Secret',
        'description': 'Client Secret aplikasi Tokopedia',
        'data_type': 'string',
        'is_secret': True,
    },
]


class ConfigUpdate(BaseModel):
    value: Any

# ══════════════════════════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════════════════════════

def _mask_secret(doc: dict) -> dict:
    """Mask secret values for non-admin returns."""
    doc.pop('_id', None)
    if doc.get('is_secret') and doc.get('value'):
        val = str(doc['value'])
        if len(val) > 4:
            doc['value_masked'] = '•' * (len(val) - 4) + val[-4:]
        else:
            doc['value_masked'] = '••••'
        # Keep original value only for admins (caller can check role)
    return doc

async def ensure_defaults(db):
    """Make sure all default configs exist (idempotent)."""
    existing_keys = set()
    async for doc in db.dewi_system_config.find({}, {'key': 1, '_id': 0}):
        existing_keys.add(doc['key'])

    to_insert = []
    now = datetime.now(timezone.utc)
    for cfg in DEFAULT_CONFIGS:
        if cfg['key'] not in existing_keys:
            to_insert.append({
                **cfg,
                'updated_at': now,
                'updated_by': 'system_init',
            })
    if to_insert:
        await db.dewi_system_config.insert_many(to_insert)
    return len(to_insert)

async def get_config_value(db, key: str, default: Any = None):
    """Helper for other modules to read a config value safely."""
    doc = await db.dewi_system_config.find_one({'key': key})
    if not doc or doc.get('value') is None:
        return default
    return doc['value']

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get('')
async def list_configs(
    category: Optional[str] = None,
    user: dict = Depends(require_auth),
):
    db = get_db()
    await ensure_defaults(db)

    is_admin = user.get('role') in ('admin', 'superadmin') or 'admin' in (user.get('roles') or [])
    query = {'category': category} if category else {}
    items = await db.dewi_system_config.find(query).sort([('category', 1), ('key', 1)]).to_list(length=500)

    out = []
    for doc in items:
        if doc.get('key') in RETIRED_KEYS:
            continue
        cleaned = {**doc}
        if cleaned.get('key') in CONFIG_CHOICES:
            cleaned['choices'] = CONFIG_CHOICES[cleaned['key']]
            # keterangan lama di DB berisi kode mentah ("net_7 | net_14 …") — pakai teks terbaru
            cleaned['description'] = next(
                (c['description'] for c in DEFAULT_CONFIGS if c['key'] == cleaned['key']),
                cleaned.get('description'))
        _mask_secret(cleaned)
        # Hide raw secret value if not admin
        if cleaned.get('is_secret') and not is_admin:
            cleaned.pop('value', None)
        out.append(cleaned)
    from utils.waktu import mongo_utc  # 8 Nov 2026: updated_at (datetime naif dari Mongo) dikirim berzona UTC
    return mongo_utc(out)

@router.get('/categories')
async def list_categories(user: dict = Depends(require_auth)):
    db = get_db()
    await ensure_defaults(db)
    cats = await db.dewi_system_config.distinct('category')
    return sorted(cats)

@router.get('/{key}')
async def get_config(key: str, user: dict = Depends(require_auth)):
    db = get_db()
    await ensure_defaults(db)
    doc = await db.dewi_system_config.find_one({'key': key})
    if not doc:
        raise HTTPException(404, f'Config {key} tidak ditemukan')
    is_admin = user.get('role') in ('admin', 'superadmin') or 'admin' in (user.get('roles') or [])
    doc.pop('_id', None)
    _mask_secret(doc)
    if doc.get('is_secret') and not is_admin:
        doc.pop('value', None)
    from utils.waktu import mongo_utc
    return mongo_utc(doc)

# 2026-11-07 (Tahap 6, SY2 — keputusan owner): MENGUBAH pengaturan sistem (termasuk kunci rahasia) hanya
# admin / owner / superadmin. Dulu semua peran internal boleh. Membaca tetap seperti semula (rahasia disamarkan
# untuk non-admin); layar menampilkan mode baca saja bagi peran lain.
@router.put('/{key}', dependencies=only(*SYSTEM_CONFIG_ROLES))
async def update_config(key: str, payload: ConfigUpdate, user: dict = Depends(require_auth)):
    db = get_db()
    # 2026-11-02 (K15): Langkah 2 (potong stok dari impor) tidak boleh menyala bersama Scan Keluar.
    from core.scan_out import langkah2_guard
    blocked = langkah2_guard(key, payload.value)
    if blocked:
        raise HTTPException(409, blocked)
    existing = await db.dewi_system_config.find_one({'key': key})
    if not existing:
        raise HTTPException(404, f'Config {key} tidak ditemukan')

    # Coerce value to expected data_type
    dt = existing.get('data_type', 'string')
    new_value = payload.value
    try:
        if dt == 'number':
            new_value = float(new_value)
        elif dt == 'boolean':
            if isinstance(new_value, str):
                new_value = new_value.lower() in ('true', '1', 'yes', 'on')
            else:
                new_value = bool(new_value)
        elif dt == 'string':
            new_value = '' if new_value is None else str(new_value)
    except (ValueError, TypeError):
        raise HTTPException(400, f'Value tidak valid untuk data_type {dt}')
    bad = choice_error(key, new_value)
    if bad:
        raise HTTPException(400, f"{existing.get('label') or key}: {bad}")

    await db.dewi_system_config.update_one(
        {'key': key},
        {'$set': {
            'value': new_value,
            'updated_at': datetime.now(timezone.utc),
            'updated_by': user.get('name', 'System'),
        }}
    )
    return {'message': f'Config {key} diperbarui'}

class BulkUpdateIn(BaseModel):
    """Generic key/value bulk update. Accepts arbitrary additional fields."""
    model_config = {'extra': 'allow'}


@router.post('/bulk', dependencies=only(*SYSTEM_CONFIG_ROLES))  # SY2 — lihat update_config
async def bulk_update(payload: BulkUpdateIn, user: dict = Depends(require_auth)):
    """Update multiple configs in one call. payload = {key: value, ...}"""
    db = get_db()
    now = datetime.now(timezone.utc)
    updated = 0
    errors = []
    keys_list = list(payload.model_dump().keys())
    # Batch prefetch existing configs for all keys
    existing_configs_map = {}
    if keys_list:
        async for d in db.dewi_system_config.find(
            {'key': {'$in': keys_list}}, {'_id': 0}
        ):
            existing_configs_map[d['key']] = d
    from core.scan_out import langkah2_guard  # 2026-11-02 (K15)
    for key, value in payload.model_dump().items():
        if langkah2_guard(key, value):
            errors.append(f'{key}: {langkah2_guard(key, value)}')
            continue
        existing = existing_configs_map.get(key)
        if not existing:
            errors.append(f'{key}: tidak ditemukan')
            continue
        dt = existing.get('data_type', 'string')
        new_value = value
        try:
            if dt == 'number':
                new_value = float(new_value) if new_value != '' else 0
            elif dt == 'boolean':
                if isinstance(new_value, str):
                    new_value = new_value.lower() in ('true', '1', 'yes', 'on')
                else:
                    new_value = bool(new_value)
            elif dt == 'string':
                new_value = '' if new_value is None else str(new_value)
        except (ValueError, TypeError):
            errors.append(f'{key}: invalid type')
            continue
        bad = choice_error(key, new_value)
        if bad:
            errors.append(f"{existing.get('label') or key}: {bad}")
            continue
        await db.dewi_system_config.update_one(
            {'key': key},
            {'$set': {
                'value': new_value,
                'updated_at': now,
                'updated_by': user.get('name', 'System'),
            }}
        )
        updated += 1
    return {'updated': updated, 'errors': errors}
