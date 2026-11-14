from database import get_db


async def _shipment_ids_po(db, po_id: str, po_item_ids: list) -> list:
    """Surat jalan Kirim ke CMT milik PO (langsung `po_id`, atau lewat barisnya) — sama dengan cakupan hapus di bawah."""
    ids = {s['id'] for s in await db.vendor_shipments.find({'po_id': po_id}, {'_id': 0, 'id': 1}).to_list(None)}
    q = [{'po_id': po_id}] + ([{'po_item_id': {'$in': po_item_ids}}] if po_item_ids else [])
    for it in await db.vendor_shipment_items.find({'$or': q}, {'_id': 0, 'shipment_id': 1}).to_list(None):
        if it.get('shipment_id'):
            ids.add(it['shipment_id'])
    return sorted(ids)


async def alasan_tolak_hapus_po(db, po_id: str) -> list:
    """Alasan PO TIDAK boleh dihapus (kosong = boleh). 14 Nov 2026 (temuan owner): dulu Hapus PO internal tanpa batas
    status ikut menghapus kiriman CMT, job, progres, dll. TANPA mengembalikan stok — bahan yang sudah keluar gudang
    hilang jejaknya. PO yang sudah berjalan ditutup lewat Tutup PO, bukan dihapus.

    Ditolak bila PO sudah punya: job produksi, progres, penerimaan dari CMT (Terima & QC, selain yang dibatalkan),
    kiriman hasil ke buyer, atau surat jalan Kirim ke CMT yang bahannya sudah keluar gudang (Material Issue keluar dan
    belum diretur penuh — `routes.vendor_shipment.shipment_issued_mis`). PO Draf yang hanya punya surat jalan TANPA
    bahan keluar dan tanpa job tetap boleh dihapus."""
    from core.cmt_receipt_status import ST_CANCELLED, canon_status
    from routes.vendor_shipment import shipment_issued_mis
    alasan = []
    po_item_ids = [i['id'] for i in await db.po_items.find({'po_id': po_id}, {'_id': 0, 'id': 1}).to_list(None)]
    ship_ids = await _shipment_ids_po(db, po_id, po_item_ids)
    jobs = await db.production_jobs.find(
        {'$or': [{'po_id': po_id}] + ([{'vendor_shipment_id': {'$in': ship_ids}}] if ship_ids else [])},
        {'_id': 0, 'id': 1}).to_list(None)
    if jobs:
        alasan.append(f'{len(jobs)} job produksi')
    job_ids = [j['id'] for j in jobs]
    wo_ids = [w['id'] for w in await db.work_orders.find({'po_id': po_id}, {'_id': 0, 'id': 1}).to_list(None)]
    q_prog = ([{'job_id': {'$in': job_ids}}] if job_ids else []) + ([{'work_order_id': {'$in': wo_ids}}] if wo_ids else [])
    if q_prog and await db.production_progress.count_documents({'$or': q_prog}):
        alasan.append('progres produksi')
    terima = [r for r in await db.cmt_receipts.find({'po_id': po_id}, {'_id': 0, 'status': 1}).to_list(None)
              if canon_status(r.get('status')) != ST_CANCELLED]
    if terima:
        alasan.append(f'{len(terima)} penerimaan dari CMT (Terima & QC)')
    kirim_hasil = await db.buyer_shipments.count_documents({'po_id': po_id})
    if kirim_hasil:
        alasan.append(f'{kirim_hasil} kiriman hasil')
    mi = []
    for sid in ship_ids:
        mi += [m.get('mi_number') or m.get('id') for m in await shipment_issued_mis(db, sid)]
    if mi:
        mi = sorted(set(mi))
        alasan.append(f"bahan sudah keluar gudang untuk Kirim ke CMT (Material Issue {', '.join(mi[:5])}"
                      f"{' …' if len(mi) > 5 else ''})")
    return alasan


async def cascade_delete_po(po_id: str):
    db = get_db()
    # 1. Get PO items
    po_items = await db.po_items.find({'po_id': po_id}).to_list(None)
    po_item_ids = [i['id'] for i in po_items]
    
    # 2. Delete vendor shipments & items
    vs_items = []
    if po_item_ids:
        vs_items = await db.vendor_shipment_items.find({'po_item_id': {'$in': po_item_ids}}).to_list(None)
    vs_by_po = await db.vendor_shipment_items.find({'po_id': po_id}).to_list(None)
    all_vs_items = vs_items + vs_by_po
    shipment_ids = list(set(i.get('shipment_id') for i in all_vs_items if i.get('shipment_id')))
    
    for ship_id in shipment_ids:
        # Delete inspections
        inspections = await db.vendor_material_inspections.find({'shipment_id': ship_id}).to_list(None)
        for insp in inspections:
            await db.vendor_material_inspection_items.delete_many({'inspection_id': insp['id']})
        await db.vendor_material_inspections.delete_many({'shipment_id': ship_id})
        
        # Delete production jobs
        jobs = await db.production_jobs.find({'vendor_shipment_id': ship_id}).to_list(None)
        for job in jobs:
            child_jobs = await db.production_jobs.find({'parent_job_id': job['id']}).to_list(None)
            for cj in child_jobs:
                await db.production_job_items.delete_many({'job_id': cj['id']})
                await db.production_progress.delete_many({'job_id': cj['id']})
                await db.production_jobs.delete_one({'id': cj['id']})
            await db.production_job_items.delete_many({'job_id': job['id']})
            await db.production_progress.delete_many({'job_id': job['id']})
            await db.production_jobs.delete_one({'id': job['id']})
        
        await db.material_requests.delete_many({'original_shipment_id': ship_id})
        await db.vendor_shipment_items.delete_many({'shipment_id': ship_id})
        
        # Delete child shipments
        child_ships = await db.vendor_shipments.find({'parent_shipment_id': ship_id}).to_list(None)
        for cs in child_ships:
            await db.vendor_shipment_items.delete_many({'shipment_id': cs['id']})
            await db.vendor_shipments.delete_one({'id': cs['id']})
        
        await db.vendor_shipments.delete_one({'id': ship_id})
    
    # 3. Delete buyer shipments
    buyer_ships = await db.buyer_shipments.find({'po_id': po_id}).to_list(None)
    for bs in buyer_ships:
        await db.buyer_shipment_items.delete_many({'shipment_id': bs['id']})
        await db.buyer_shipments.delete_one({'id': bs['id']})
    
    # 4. Delete invoices
    invoices = await db.invoices.find({'po_id': po_id}).to_list(None)
    for inv in invoices:
        await db.invoice_adjustments.delete_many({'invoice_id': inv['id']})
        await db.payments.delete_many({'invoice_id': inv['id']})
        await db.invoices.delete_one({'id': inv['id']})
    
    # 5. Delete work orders
    work_orders = await db.work_orders.find({'po_id': po_id}).to_list(None)
    for wo in work_orders:
        await db.production_progress.delete_many({'work_order_id': wo['id']})
    await db.work_orders.delete_many({'po_id': po_id})
    
    # 6. Delete defect reports
    if po_item_ids:
        await db.material_defect_reports.delete_many({'po_item_id': {'$in': po_item_ids}})
    await db.material_defect_reports.delete_many({'po_id': po_id})
    
    # 7. Delete production returns
    returns = await db.production_returns.find({'reference_po_id': po_id}).to_list(None)
    for ret in returns:
        await db.production_return_items.delete_many({'return_id': ret['id']})
    await db.production_returns.delete_many({'reference_po_id': po_id})
    
    # 7b. Delete production variances (referensi job/PO yang dihapus)
    await db.production_variances.delete_many({'po_id': po_id})

    # 8. Delete attachments
    await db.attachments.delete_many({'reference_id': po_id})

    # 8b. (DA Fase 2 Maklon) Bersihkan mirror finance + Draft AR yang belum diposting.
    # AR yang sudah diposting ke GL TIDAK dihapus (jejak audit finance).
    mirror = await db.dewi_maklon_pos.find_one({'id': po_id, 'mirror_of': 'production_pos'})
    if mirror:
        await db.rahaza_ar_invoices.delete_many({
            'linked_maklon_po_id': po_id, 'source_module': 'maklon_po', 'status': 'draft'})
        await db.dewi_maklon_pos.delete_one({'id': po_id})

    # 9. Delete PO items, accessories, then PO
    await db.po_accessories.delete_many({'po_id': po_id})
    await db.po_items.delete_many({'po_id': po_id})
    await db.production_pos.delete_one({'id': po_id})
