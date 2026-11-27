"""Migrasi 2026-11-27 — hapus bersih SATU pembelian salah input (PO → penerimaan → tagihan draf).

KENAPA: aplikasi belum punya tombol untuk membatalkan penerimaan yang sudah "diterima penuh" (PO diterima penuh tidak
bisa dibatalkan; Retur Pembelian membuat dokumen retur yang tidak pernah terjadi). Owner (27 Nov 2026) memilih "hapus
bersih" untuk PO-20261126-001 Alvino Tex Rp18 jt (1.000 yard Rayon Twill Motif) yang dibuat sebagai uji/salah input.

Yang dikembalikan per PO (`--po <nomor>`):
  * jurnal penerimaan (Dr Persediaan / Cr GRNI 2-1150) dibatalkan lewat `_void_je_by_source` — periode terbuka:
    status `voided` (nomornya tetap tercatat batal); periode tertutup: jurnal pembalik bertanggal hari ini;
  * stok yang masuk dikeluarkan lagi (baris stok yang lahir dari penerimaan ini dihapus bersama buku stoknya);
    mutasi bahan penerimaan dihapus;
  * HPP rata-rata bahan kembali ke harga sebelum penerimaan (riwayat HPP penerimaan dihapus);
  * pemakaian bahan SESUDAH penerimaan yang memakai HPP rata-rata turunan penerimaan ini (laporan progres cutting)
    dinilai ulang dengan HPP yang benar: nilai kain keluar, HPP/pcs potongan, HPP rata-rata potongan + riwayatnya, dan
    rekap nilai order cutting yang sudah Selesai;
  * tagihan draf dari penerimaan, dokumen penerimaan, PO, dan notifikasinya dihapus; satu catatan aktivitas ditulis.

Ditolak (tidak ada yang ditulis) bila: tagihan sudah diposting/dibayar/bernota debit, ada retur pembelian, roll kain
atau karantina dari penerimaan ini, aset tetap dari penerimaan ini, jurnal selisih nilai stok lama, atau bahan /
potongannya sudah bergerak dengan cara yang tidak bisa dinilai ulang otomatis (mis. opname, kirim ke CMT). Alasannya
dicetak.

Sifat: bawaan PRATINJAU. `--apply` menulis cadangan JSON semua dokumen yang disentuh lebih dulu ke `--cadangan`, baru
menulis. Backup DB tetap wajib sebelum `--apply` di VPS.

Runbook (VPS, sesudah disetujui owner):
    docker exec dahost-backend-1 python scripts/migrations/2026_11_27_hapus_pembelian_salah.py --po PO-20261126-001
    docker exec dahost-backend-1 python scripts/migrations/2026_11_27_hapus_pembelian_salah.py --po PO-20261126-001 \
        --apply --cadangan /app/backups
"""
import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')

AKTOR = {'id': 'skrip-hapus-pembelian', 'name': 'Skrip hapus pembelian salah input'}
EPS = 0.01
BATAS = 5000


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _rp(v) -> str:
    return f"Rp{_f(v):,.0f}".replace(',', '.')


class Tolak(Exception):
    """Alasan pembelian ini tidak bisa dihapus otomatis."""


def alasan_tolak_tagihan(inv: dict, je_aktif: bool) -> str:
    """'' bila tagihan boleh dihapus (draf/batal, belum dibayar, tanpa nota debit, tanpa jurnal aktif)."""
    no = inv.get('invoice_number') or inv.get('id')
    if str(inv.get('status') or '').lower() not in ('draft', 'cancelled'):
        return f"tagihan {no} berstatus {inv.get('status')} (bukan draf) — batalkan lewat menu Hutang dulu"
    if _f(inv.get('paid_amount')) > EPS or inv.get('payments'):
        return f"tagihan {no} sudah dibayar {_rp(inv.get('paid_amount'))}"
    if _f(inv.get('debit_note_amount')) > EPS:
        return f"tagihan {no} sudah dikurangi nota debit"
    if je_aktif:
        return f"tagihan {no} punya jurnal aktif"
    return ''


def alasan_tolak_penerimaan(gr: dict) -> str:
    """'' bila dokumen penerimaan bisa dikembalikan otomatis."""
    no = gr.get('receipt_number') or gr.get('id')
    if gr.get('rolls_created'):
        return f"{no} sudah menerbitkan roll kain {', '.join(gr['rolls_created'][:5])}"
    for it in gr.get('items') or []:
        if it.get('roll_ids'):
            return f"{no} baris {it.get('material_name') or it.get('sku')} sudah punya roll kain"
        if it.get('quarantine_item_id') or _f(it.get('quarantined_qty')) > 0:
            return f"{no} baris {it.get('material_name') or it.get('sku')} punya barang karantina"
        if it.get('wac_gap_je_number'):
            return f"{no} baris {it.get('material_name') or it.get('sku')} punya jurnal selisih nilai stok lama"
    return ''


def nilai_ulang_progres(p: dict, material_id: str, biaya_salah: float, biaya_benar: float) -> dict:
    """Nilai ulang satu laporan progres cutting yang memakai HPP kain `biaya_salah` → `biaya_benar`.

    Hanya order satu kain (semua nilai potongan berasal dari kain ini, jadi semuanya diskalakan dengan rasio yang
    sama). Hasil: {'set': {...field progres...}, 'panel': [{material_id, qty_in, cost_in_lama, cost_in_baru,
    after_lama, after_baru}], 'value_lama', 'value_baru'}. Raise `Tolak` bila tidak bisa dinilai ulang otomatis."""
    from core.accessory_valuation import moving_average
    ins = p.get('inputs') or []
    if len(ins) != 1 or ins[0].get('input_material_id') != material_id:
        raise Tolak(f"progres {p.get('cutting_number')} memakai lebih dari satu kain — koreksi manual")
    if abs(_f(ins[0].get('fabric_unit_cost', p.get('fabric_unit_cost'))) - biaya_salah) > EPS:
        raise Tolak(f"progres {p.get('cutting_number')} tidak memakai HPP kain {biaya_salah:,.4f}")
    if biaya_salah <= 0:
        raise Tolak('HPP kain salah = 0')
    r = biaya_benar / biaya_salah
    v_lama = _f(ins[0].get('value_out', p.get('value_out')))
    v_baru = round(v_lama * r, 4)
    outs_baru, panel = [], []
    for o in p.get('outputs') or []:
        cpp_lama = _f(o.get('cost_per_pcs_in'))
        cpp_baru = round(cpp_lama * r, 6)
        after_baru = moving_average(o.get('panel_qty_before'), o.get('panel_unit_cost_before'),
                                    o.get('output_qty'), cpp_baru)
        panel.append({'material_id': o.get('output_material_id'), 'code': o.get('output_material_code'),
                      'qty_in': _f(o.get('output_qty')), 'cost_in_lama': cpp_lama, 'cost_in_baru': cpp_baru,
                      'after_lama': _f(o.get('panel_unit_cost_after')), 'after_baru': after_baru})
        outs_baru.append({**o, 'cost_per_pcs_in': cpp_baru, 'panel_unit_cost_after': after_baru})
    if len({x['material_id'] for x in panel}) != len(panel):
        raise Tolak(f"progres {p.get('cutting_number')} punya dua baris hasil untuk potongan yang sama")
    qty_out = sum(x['qty_in'] for x in panel)
    s = {
        'fabric_unit_cost': round(biaya_benar, 4),
        'value_out': v_baru,
        'inputs': [{**ins[0], 'fabric_unit_cost': round(biaya_benar, 4), 'value_out': v_baru}],
        'outputs': outs_baru,
        'value_note': (f"Nilai kain keluar {v_baru:,.2f} dibagi {qty_out:g} pcs = "
                       f"{(v_baru / qty_out if qty_out else 0):,.2f}/pcs, dirata-rata dengan stok potongan lama. "
                       f"Dinilai ulang 27 Nov 2026: penerimaan salah input dihapus, HPP kain {biaya_salah:,.2f} → "
                       f"{biaya_benar:,.2f}."),
    }
    if outs_baru:
        s['cost_per_pcs_in'] = outs_baru[0]['cost_per_pcs_in']
        s['panel_unit_cost_after'] = outs_baru[0]['panel_unit_cost_after']
    return {'set': s, 'panel': panel, 'value_lama': v_lama, 'value_baru': v_baru}


async def _rencana(db, po_number: str) -> dict:
    """Kumpulkan semua yang akan disentuh + periksa syarat. Tidak menulis apa pun."""
    from routes.rahaza_posting import _find_existing_je
    po = await db.rahaza_purchase_orders.find_one({'po_number': po_number}, {'_id': 0})
    if not po:
        raise Tolak(f"PO {po_number} tidak ditemukan")
    grs = await db.warehouse_receiving.find(
        {'$or': [{'po_id': po['id']}, {'source_ref': po_number}]}, {'_id': 0}).to_list(BATAS)
    gr_ids = [g['id'] for g in grs]
    invs = await db.rahaza_ap_invoices.find(
        {'$or': [{'po_ids': po['id']}, {'gr_ids': {'$in': gr_ids}}]}, {'_id': 0}).to_list(BATAS)
    for inv in invs:
        why = alasan_tolak_tagihan(inv, bool(await _find_existing_je(db, 'ap_invoice', f"ap:{inv['id']}")))
        if why:
            raise Tolak(why)
    for g in grs:
        why = alasan_tolak_penerimaan(g)
        if why:
            raise Tolak(why)
    if gr_ids and await db.rahaza_purchase_returns.count_documents(
            {'$or': [{'gr_id': {'$in': gr_ids}}, {'gr_ids': {'$in': gr_ids}}]}):
        raise Tolak('sudah ada retur pembelian dari penerimaan ini')
    if gr_ids and await db.wh_fabric_rolls.count_documents(
            {'$or': [{'source_receipt_id': {'$in': gr_ids}}, {'receipt_id': {'$in': gr_ids}}]}):
        raise Tolak('sudah ada roll kain dari penerimaan ini')
    if gr_ids and await db.da_assets.count_documents(
            {'$or': [{'grn_id': {'$in': gr_ids}}, {'receipt_id': {'$in': gr_ids}}, {'source_id': {'$in': gr_ids}}]}):
        raise Tolak('sudah ada aset tetap dari penerimaan ini')

    mvs = await db.rahaza_material_movements.find(
        {'reference_type': 'goods_receipt', 'reference_id': {'$in': gr_ids}}, {'_id': 0}).to_list(BATAS)
    jes = []
    for mv in mvs:
        je = await _find_existing_je(db, 'inventory_receive', f"mvrcv:{mv['id']}")
        if je:
            jes.append(je)
    ledger_add = await db.rahaza_stock_ledger.find(
        {'ref.ref_type': 'goods_receipt', 'ref.ref_id': {'$in': gr_ids}}, {'_id': 0}).to_list(BATAS)

    stok, hpp, progres, potongan, orders = [], [], [], [], {}
    for g in grs:
        for it in g.get('items') or []:
            mid = it.get('material_id')
            qty = _f(it.get('accepted_qty') if it.get('accepted_qty') is not None
                     else _f(it.get('received_qty')) - _f(it.get('rejected_qty')))
            if not mid or qty <= 0:
                continue
            led = next((x for x in ledger_add if x.get('material_id') == mid
                        and x.get('location_id') == g.get('location_id')), None)
            if not led:
                raise Tolak(f"buku stok penerimaan {g.get('receipt_number')} untuk {it.get('material_name')} "
                            "tidak ditemukan")
            row = await db.rahaza_material_stock.find_one(
                {'material_id': mid, 'location_id': g.get('location_id')}, {'_id': 0})
            if not row or _f(row.get('qty')) + EPS < qty:
                raise Tolak(f"stok {it.get('material_name')} di {g.get('location_name')} tinggal "
                            f"{_f((row or {}).get('qty')):g}, kurang dari {qty:g} yang mau dikeluarkan")
            baris_baru = abs(_f(led.get('qty_after')) - _f(led.get('delta'))) < EPS
            sesudah = await db.rahaza_stock_ledger.find(
                {'material_id': mid, 'created_at': {'$gt': led['created_at']}}, {'_id': 0}).to_list(BATAS)
            stok.append({'material_id': mid, 'nama': it.get('material_name'), 'location_id': g.get('location_id'),
                         'lokasi': g.get('location_name'), 'qty': qty, 'row': row, 'ledger': led,
                         'hapus_baris': baris_baru and abs(_f(row.get('qty')) - qty) < EPS
                         and not any(x.get('location_id') == g.get('location_id') for x in sesudah)})

            # HPP rata-rata bahan
            h = await db.rahaza_material_cost_history.find_one(
                {'material_id': mid, 'source': 'receive', 'notes': {'$regex': f"^GR {re.escape(str(g.get('receipt_number') or ''))}( |$)"}},
                {'_id': 0})
            mat = await db.rahaza_materials.find_one({'id': mid}, {'_id': 0}) or {}
            if h:
                lebih_baru = await db.rahaza_material_cost_history.count_documents(
                    {'material_id': mid, 'created_at': {'$gt': h['created_at']}})
                if lebih_baru:
                    raise Tolak(f"HPP {it.get('material_name')} sudah berubah lagi sesudah penerimaan — koreksi manual")
                if abs(_f(mat.get('unit_cost')) - _f(h.get('new_unit_cost'))) > 0.001:
                    raise Tolak(f"HPP master {it.get('material_name')} {_f(mat.get('unit_cost')):,.4f} tidak sama dengan "
                                f"hasil penerimaan {_f(h.get('new_unit_cost')):,.4f}")
                sebelum = await db.rahaza_material_cost_history.find(
                    {'material_id': mid, 'created_at': {'$lt': h['created_at']}}, {'_id': 0}
                ).sort('created_at', -1).to_list(1)
                hpp.append({'material_id': mid, 'nama': it.get('material_name'), 'hist': h, 'mat': mat,
                            'sebelum': sebelum[0] if sebelum else None})

            # Pemakaian sesudah penerimaan: hanya laporan progres cutting yang bisa dinilai ulang otomatis
            for x in sesudah:
                if x.get('location_id') == g.get('location_id') and x.get('op') == 'add':
                    raise Tolak(f"stok {it.get('material_name')} di {g.get('location_name')} bertambah lagi sesudah "
                                "penerimaan — koreksi manual")
                ref = x.get('ref') or {}
                if x.get('op') != 'issue' or ref.get('type') != 'cutting':
                    raise Tolak(f"{it.get('material_name')} sudah bergerak sesudah penerimaan ({x.get('op')} "
                                f"{ref.get('type') or ref.get('ref_type') or ''} {ref.get('no') or ''}) — koreksi manual")
                if x.get('location_id') == g.get('location_id'):
                    raise Tolak(f"kain dari penerimaan ini sudah dipakai cutting {ref.get('no')} — tidak bisa dihapus")
                if not h:
                    continue
                pgs = await db.cutting_progress.find(
                    {'cutting_order_id': ref.get('id'), 'inputs.input_material_id': mid}, {'_id': 0}).to_list(50)
                pg = [p for p in pgs if abs((p['created_at'] - x['created_at']).total_seconds()) < 5]
                if len(pg) != 1:
                    raise Tolak(f"laporan progres cutting {ref.get('no')} tidak ditemukan pasti — koreksi manual")
                hasil = nilai_ulang_progres(pg[0], mid, _f(h.get('new_unit_cost')), _f(h.get('old_unit_cost')))
                progres.append({'p': pg[0], 'hasil': hasil})
                orders.setdefault(ref.get('id'), None)

    # Potongan hasil cutting yang dinilai ulang: belum bergerak sesudah cutting & HPP-nya belum berubah lagi
    for item in progres:
        p = item['p']
        for pn in item['hasil']['panel']:
            if any(pn['material_id'] == q['material_id'] for q in potongan):
                raise Tolak(f"potongan {pn['code']} dinilai oleh lebih dari satu progres — koreksi manual")
            mat = await db.rahaza_materials.find_one({'id': pn['material_id']}, {'_id': 0}) or {}
            if abs(_f(mat.get('unit_cost')) - pn['after_lama']) > 0.001:
                raise Tolak(f"HPP potongan {pn['code']} sudah berubah lagi — koreksi manual")
            h = await db.rahaza_material_cost_history.find(
                {'material_id': pn['material_id'], 'created_at': {'$gte': p['created_at'].replace(microsecond=0)}},
                {'_id': 0}).sort('created_at', 1).to_list(5)
            if len(h) != 1 or abs(_f(h[0].get('new_unit_cost')) - pn['after_lama']) > 0.001:
                raise Tolak(f"riwayat HPP potongan {pn['code']} tidak cocok — koreksi manual")
            gerak = await db.rahaza_stock_ledger.find(
                {'material_id': pn['material_id'], 'created_at': {'$gte': p['created_at'].replace(microsecond=0)}},
                {'_id': 0}).to_list(50)
            if any((x.get('ref') or {}).get('id') != p['cutting_order_id'] or x.get('op') != 'add' for x in gerak):
                raise Tolak(f"potongan {pn['code']} sudah bergerak sesudah cutting (mis. kirim ke CMT) — koreksi manual")
            potongan.append({**pn, 'mat': mat, 'hist': h[0], 'cutting': p.get('cutting_number')})
    for oid in list(orders):
        o = await db.cutting_orders.find_one({'id': oid}, {'_id': 0})
        if o and o.get('status') == 'completed':
            if o.get('value_source') != 'progress_trace' or len(o.get('outputs') or []) > 1:
                raise Tolak(f"order cutting {o.get('number')} Selesai dengan nilai cadangan / banyak hasil — "
                            "koreksi manual")
        orders[oid] = o

    notif = await db.notifications.find(
        {'source_id': {'$in': [po['id'], *gr_ids, *[i['id'] for i in invs]]}}, {'_id': 0}).to_list(BATAS)
    je_lines = await db.rahaza_journal_lines.find({'je_id': {'$in': [j['id'] for j in jes]}},
                                                  {'_id': 0}).to_list(BATAS)
    return {'po': po, 'grs': grs, 'invs': invs, 'mvs': mvs, 'jes': jes, 'je_lines': je_lines,
            'ledger_add': ledger_add, 'stok': stok, 'hpp': hpp, 'progres': progres, 'potongan': potongan,
            'orders': orders, 'notif': notif}


def _cetak(r: dict) -> None:
    po = r['po']
    print(f"  PO {po['po_number']} · {po.get('vendor_name')} · {_rp(po.get('total_value'))} · status {po.get('status')}")
    for g in r['grs']:
        print(f"  penerimaan {g.get('receipt_number')} · {g.get('location_name')} · status {g.get('status')}")
    for i in r['invs']:
        print(f"  tagihan {i.get('invoice_number')} · {_rp(i.get('total'))} · status {i.get('status')}")
    for j in r['jes']:
        print(f"  jurnal {j.get('je_number')} ({j.get('date')}) {_rp(j.get('total_debit'))} → dibatalkan")
    for s in r['stok']:
        cara = 'baris stok dihapus' if s['hapus_baris'] else 'stok dikurangi'
        print(f"  stok {s['nama']} di {s['lokasi']}: −{s['qty']:g} ({cara})")
    for h in r['hpp']:
        print(f"  HPP {h['nama']}: {_f(h['mat'].get('unit_cost')):,.4f} → {_f(h['hist'].get('old_unit_cost')):,.4f}")
    for it in r['progres']:
        p, hs = it['p'], it['hasil']
        print(f"  cutting {p.get('cutting_number')}: nilai kain keluar {hs['value_lama']:,.2f} → {hs['value_baru']:,.2f}")
    for pn in r['potongan']:
        print(f"    potongan {pn['code']}: HPP/pcs masuk {pn['cost_in_lama']:,.2f} → {pn['cost_in_baru']:,.2f}; "
              f"HPP rata-rata {pn['after_lama']:,.4f} → {pn['after_baru']:,.4f}")
    for o in r['orders'].values():
        if o and o.get('status') == 'completed':
            print(f"    order {o.get('number')} Selesai: rekap nilai dihitung ulang dari progres")
    print(f"  notifikasi dihapus: {len(r['notif'])}")


async def run(db, po_number: str, apply: bool = False, cadangan: str = '.') -> dict:
    mode = 'TULIS' if apply else 'PRATINJAU (tanpa perubahan — tambahkan --apply untuk menulis)'
    print(f"[hapus-pembelian-salah] {po_number} · {mode}")
    try:
        r = await _rencana(db, po_number)
    except Tolak as e:
        print(f"  DITOLAK: {e}")
        return {'ok': False, 'alasan': str(e)}
    _cetak(r)
    if not apply:
        return {'ok': True, 'applied': False}

    os.makedirs(cadangan, exist_ok=True)
    path = os.path.join(cadangan, f"cadangan_hapus_{po_number}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'po': r['po'], 'grs': r['grs'], 'invs': r['invs'], 'mvs': r['mvs'], 'jes': r['jes'],
                   'je_lines': r['je_lines'], 'ledger_add': r['ledger_add'],
                   'stok_rows': [s['row'] for s in r['stok']],
                   'hpp': [{'mat': h['mat'], 'hist': h['hist']} for h in r['hpp']],
                   'progres': [it['p'] for it in r['progres']],
                   'potongan': [{'mat': pn['mat'], 'hist': pn['hist']} for pn in r['potongan']],
                   'orders': list(r['orders'].values()), 'notif': r['notif']},
                  f, default=str, ensure_ascii=False, indent=1)
    print(f"  cadangan ditulis: {path}")

    from routes.rahaza_posting import _void_je_by_source
    from core import cutting_lines
    alasan = f"Hapus pembelian salah input {po_number} (keputusan owner 27 Nov 2026)"
    now = datetime.now(timezone.utc)
    # 1) jurnal penerimaan — gagal ⇒ berhenti sebelum data lain disentuh
    for mv in r['mvs']:
        res = await _void_je_by_source(db, 'inventory_receive', f"mvrcv:{mv['id']}", AKTOR, alasan)
        if not res.get('ok'):
            print(f"  GAGAL membatalkan jurnal: {res.get('error')} — tidak ada perubahan lain")
            return {'ok': False, 'alasan': res.get('error'), 'backup': path}
        print(f"  jurnal {res.get('je_number') or '-'}: {'dibalik ' + str(res.get('reversal_je_number')) if res.get('reversed') else 'dibatalkan'}")
    # 2) nilai ulang progres cutting, potongan, order
    for it in r['progres']:
        await db.cutting_progress.update_one({'id': it['p']['id']}, {'$set': it['hasil']['set']})
    for pn in r['potongan']:
        await db.rahaza_materials.update_one({'id': pn['material_id']}, {'$set': {
            'unit_cost': pn['after_baru'], 'cost_updated_at': now, 'updated_at': now}})
        await db.rahaza_material_cost_history.update_one({'id': pn['hist']['id']}, {'$set': {
            'unit_cost_in': round(pn['cost_in_baru'], 4), 'new_unit_cost': round(pn['after_baru'], 4),
            'notes': (pn['hist'].get('notes') or '') + f" · dinilai ulang 27 Nov 2026 ({alasan})"}})
    for oid, o in r['orders'].items():
        if not o or o.get('status') != 'completed':
            continue
        total = 0.0
        async for p in db.cutting_progress.find({'cutting_order_id': oid}, {'_id': 0, 'value_out': 1}):
            total += _f(p.get('value_out'))
        outs = o.get('outputs') or []
        produced = sum(_f(x.get('produced_qty')) for x in outs) if outs else _f(o.get('produced_qty'))
        per = cutting_lines.cost_per_pcs(total, produced)
        upd = {'total_input_cost': round(total, 2), 'output_unit_cost': per, 'updated_at': now}
        if outs:
            upd['outputs'] = [{**x, 'output_unit_cost': per} for x in outs]
        await db.cutting_orders.update_one({'id': oid}, {'$set': upd})
    # 3) HPP rata-rata bahan kembali
    for h in r['hpp']:
        prev = h['sebelum']
        st = {'unit_cost': _f(h['hist'].get('old_unit_cost')), 'updated_at': now}
        uns = {}
        if prev:
            st['cost_updated_at'] = prev.get('created_at')
            if prev.get('source') == 'receive':
                st['last_receipt_unit_cost'] = _f(prev.get('unit_cost_in'))
        else:
            uns = {'cost_updated_at': '', 'last_receipt_unit_cost': ''}
        await db.rahaza_materials.update_one({'id': h['material_id']}, {'$set': st, **({'$unset': uns} if uns else {})})
        await db.rahaza_material_cost_history.delete_one({'id': h['hist']['id']})
    # 4) stok
    from core import stock_service
    for s in r['stok']:
        if s['hapus_baris']:
            await db.rahaza_material_stock.delete_one({'id': s['row']['id']})
            await db.rahaza_stock_ledger.delete_one({'id': s['ledger']['id']})
        else:
            await stock_service.issue(s['material_id'], s['location_id'], s['qty'], actor=AKTOR, db=db,
                                      ref={'type': 'hapus_pembelian', 'no': po_number})
    # 5) dokumen
    await db.rahaza_material_movements.delete_many({'id': {'$in': [m['id'] for m in r['mvs']]}})
    await db.rahaza_ap_invoices.delete_many({'id': {'$in': [i['id'] for i in r['invs']]}})
    await db.warehouse_receiving.delete_many({'id': {'$in': [g['id'] for g in r['grs']]}})
    await db.rahaza_purchase_orders.delete_one({'id': r['po']['id']})
    await db.notifications.delete_many({'id': {'$in': [n['id'] for n in r['notif'] if n.get('id')]}})
    await db.activity_logs.insert_one({
        'id': f"hapus-{r['po']['id']}", 'user_id': AKTOR['id'], 'user_name': AKTOR['name'],
        'action': 'delete', 'module': 'pengadaan.purchase_order',
        'details': (f"{alasan}: {po_number} {r['po'].get('vendor_name')} {_rp(r['po'].get('total_value'))}, "
                    f"penerimaan {', '.join(g.get('receipt_number') or '' for g in r['grs'])}, tagihan "
                    f"{', '.join(i.get('invoice_number') or '' for i in r['invs']) or '-'}. Cadangan: {os.path.basename(path)}"),
        'timestamp': now})
    print('  selesai.')
    return {'ok': True, 'applied': True, 'backup': path}


async def main(po_number: str, apply: bool, cadangan: str) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    out = await run(db, po_number, apply, cadangan)
    return 0 if out.get('ok') else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--po', required=True, help='nomor PO, mis. PO-20261126-001')
    ap.add_argument('--apply', action='store_true', help='tulis perubahan (bawaan: pratinjau)')
    ap.add_argument('--cadangan', default='.', help='folder cadangan JSON sebelum menulis')
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.po, a.apply, a.cadangan)))
