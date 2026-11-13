/**
 * CuttingProgressForm — popup "Catat progres potong" untuk order cutting banyak kain × banyak hasil
 * (keputusan owner 10 Nov 2026).
 *
 *   · Per KAIN: kain diambil (satuan operator boleh beda — server menerjemahkan), sisa kain yang kembali ke stok,
 *     limbah, dan gulungan yang dipotong (FASE H-6: wajib untuk kain yang dilacak per gulungan; dibagi FIFO).
 *   · Per HASIL: pcs jadi + "Gulungan dipakai" (ketelusuran gulungan → hasil, bukan dasar HPP).
 *   · Tabel "Gulungan → hasil potongan" progres ini + perkiraan HPP/pcs = biaya kain ÷ total pcs (sama semua baris).
 * Kain yang tidak dipakai pada progres ini cukup dikosongkan.
 *
 * 14 Nov 2026 (owner: "di cutting yang sedang berjalan, tolong bisa dilakukan EDIT"; order Selesai juga): `correcting`
 * = catatan progres yang dikoreksi. Isian terisi angka lama, gulungan menampilkan sisa + pemakaian catatan itu, alasan
 * wajib, dan server membalik catatan lama (stok, gulungan, HPP, dokumen keluar) sebelum angka baru dicatat.
 */
import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Eraser, History, Scissors } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { EmptyState, Notice } from '../moduleAtoms';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { cuttingApi, fmtDateTime, fmtNum, fmtRp } from './cuttingApi';
import useUomOptions from '../../../hooks/useUomOptions';
import { UomSelect, UomConversionHint, toBaseQty } from '../uom/UomPicker';
// FASE H-6 — gulungan WAJIB ditunjuk saat memotong kain yang punya gulungan.
import { previewAllocation, fmtQty } from '../warehouse/rollLines';
import { rollRemaining } from './cuttingLines';

const EMPTY_LINE = { input_consumed: '', input_uom: '', leftover_qty: '', waste_qty: '', waste_uom: '', roll_ids: [] };
const EMPTY_ROLLS = { items: [], roll_required: false, total_remaining: 0, uom: '', other_location_count: 0 };
const numText = (v) => (Number(v) > 0 ? String(Math.round(Number(v) * 10000) / 10000) : '');

/** Angka satu catatan progres per baris kain (satuan order) — catatan lama satu-kain memakai field tingkat atas. */
function oldInputOf(prog, line, single) {
  const rows = prog?.inputs || [];
  const x = rows.length
    ? rows.find((p) => p.line_id === line.line_id || p.input_material_id === line.input_material_id)
    : (single ? prog : null);
  if (!x) return null;
  const taken = x.input_taken ?? (Number(x.input_consumed || 0) + Number(x.leftover_qty || 0));
  return { taken, leftover: x.leftover_qty, waste: x.waste_qty, consumed: x.input_consumed,
    rolls: [...new Set((x.roll_consumption || []).map((r) => r.roll_id).filter(Boolean))] };
}

/** pcs satu catatan progres per baris hasil. */
function oldOutputOf(prog, line, single) {
  const rows = prog?.outputs || [];
  const x = rows.length ? rows.find((p) => p.line_id === line.line_id || p.output_material_id === line.output_material_id)
    : (single ? { output_qty: prog?.output_qty } : null);
  return x ? { qty: x.output_qty, rolls: x.roll_ids || null } : null;
}

export default function CuttingProgressForm({ open, onClose, order, token, onSaved, onNavigate, correcting = null }) {
  const ins = useMemo(() => order?.inputs || [], [order]);
  const outs = useMemo(() => order?.outputs || [], [order]);
  const [lines, setLines] = useState({});
  const [outState, setOutState] = useState({});
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [rollsBy, setRollsBy] = useState({});
  const [saving, setSaving] = useState(false);
  // ROADMAP P1 (2026-08-05) — operator lantai boleh mencatat pemakaian kain dalam satuan lain (rol/gram/yard).
  const { options: uomOpts } = useUomOptions(ins.map((i) => i.input_material_id));

  useEffect(() => {
    if (!open || !order) return undefined;
    let alive = true;
    setLines(Object.fromEntries(ins.map((i) => {
      const old = correcting ? oldInputOf(correcting, i, ins.length === 1) : null;
      return [i.line_id, old ? { ...EMPTY_LINE, input_consumed: numText(old.taken), leftover_qty: numText(old.leftover),
        waste_qty: numText(old.waste), roll_ids: old.rolls } : { ...EMPTY_LINE, roll_ids: [] }];
    })));
    setOutState(Object.fromEntries(outs.map((x) => {
      const old = correcting ? oldOutputOf(correcting, x, outs.length === 1) : null;
      return [x.line_id, { output_qty: old ? numText(old.qty) : '', roll_ids: old && outs.length > 1 ? old.rolls : null }];
    })));
    setNote(correcting?.note || '');
    setReason('');
    // Koreksi: sisa gulungan + pemakaian catatan ini (yang dikembalikan dulu oleh server)
    const locQs = (order.location_id ? `&location_id=${encodeURIComponent(order.location_id)}` : '')
      + (correcting ? `&progress_id=${encodeURIComponent(correcting.id)}` : '');
    ins.forEach(async (i) => {
      try {
        const res = await cuttingApi('GET', `/rolls?material_id=${i.input_material_id}${locQs}`, token);
        const items = Array.isArray(res) ? res : (res?.items || []);
        if (alive) {
          setRollsBy((m) => ({ ...m, [i.line_id]: {
            items, roll_required: !!res?.roll_required, total_remaining: Number(res?.total_remaining || 0),
            uom: res?.uom || items[0]?.uom || '', other_location_count: Number(res?.other_location_count || 0) } }));
        }
      } catch {
        if (alive) setRollsBy((m) => ({ ...m, [i.line_id]: EMPTY_ROLLS }));
      }
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, order?.id, correcting?.id]);

  const setLine = (lid, patch) => setLines((m) => ({ ...m, [lid]: { ...(m[lid] || EMPTY_LINE), ...patch } }));

  // 2026-11-06 (Tahap 2): pratinjau gulungan memakai angka yang SUDAH dikonversi ke satuan order dan dikurangi
  // sisa kain yang kembali ke stok (yang benar-benar dipotong dari gulungan = diambil − sisa).
  const calc = useMemo(() => {
    const out = {};
    ins.forEach((i) => {
      const st = lines[i.line_id] || EMPTY_LINE;
      const opt = uomOpts[i.input_material_id] || null;
      const unit = String(i.input_unit || '').toLowerCase();
      const eff = st.input_uom || unit;
      const conv = (q, u) => {
        const n = Number(q || 0);
        if (!n) return 0;
        if (!opt || !u || u === unit) return n;
        const a = toBaseQty(opt, n, u);
        const b = toBaseQty(opt, 1, unit);
        return a != null && b ? Math.round((a / b) * 10000) / 10000 : n;
      };
      const used = Math.max(0, Math.round((conv(st.input_consumed, eff) - conv(st.leftover_qty, eff)) * 10000) / 10000);
      const rm = rollsBy[i.line_id] || EMPTY_ROLLS;
      const picked = rm.items.filter((r) => (st.roll_ids || []).includes(r.id));
      const active = Number(st.input_consumed) > 0;
      out[i.line_id] = {
        opt, unit, eff, used, picked, active, rm,
        alloc: previewAllocation(picked, used),
        blocking: active && rm.roll_required && !(st.roll_ids || []).length,
        value: used * Number(i.input_unit_cost || 0),
      };
    });
    return out;
  }, [ins, lines, uomOpts, rollsBy]);

  // Gulungan yang dipotong di progres ini (semua kain) — pilihan "Gulungan dipakai" tiap hasil.
  const pickedAll = useMemo(() => ins.flatMap((i) => (calc[i.line_id]?.picked || [])
    .map((r) => ({ ...r, material_code: i.input_material_code || '', plan: (calc[i.line_id].alloc.plan || [])
      .find((p) => p.roll_id === r.id) }))), [ins, calc]);

  /** Gulungan untuk satu hasil: pilihan operator; bawaan = tautan order yang ikut dipotong, selain itu semua. */
  const effOutRolls = (x) => {
    const ids = pickedAll.map((r) => r.id);
    const st = outState[x.line_id] || {};
    if (Array.isArray(st.roll_ids)) return st.roll_ids.filter((r) => ids.includes(r));
    const linked = ids.filter((r) => (x.roll_ids || []).includes(r));
    return linked.length ? linked : ids;
  };
  const toggleOutRoll = (x, rid) => {
    const cur = effOutRolls(x);
    setOutState((m) => ({ ...m, [x.line_id]: { ...(m[x.line_id] || {}),
      roll_ids: cur.includes(rid) ? cur.filter((r) => r !== rid) : [...cur, rid] } }));
  };

  const totalPcs = outs.reduce((s, x) => s + Number(outState[x.line_id]?.output_qty || 0), 0);
  const totalValue = ins.reduce((s, i) => s + (calc[i.line_id]?.value || 0), 0);
  const anyBlocking = ins.some((i) => calc[i.line_id]?.blocking);
  const anyShortage = ins.some((i) => calc[i.line_id]?.active && calc[i.line_id]?.alloc.shortage > 0);

  const reasonOk = !correcting || reason.trim().length >= 5;

  /** Koreksi: kosongkan catatan ini (mis. tercatat dua kali) — server mengembalikan semua efeknya. */
  const voidRecord = async () => {
    if (!reasonOk) { toast.error('Isi alasan koreksi dulu (minimal 5 huruf).'); return; }
    if (!(await confirmDialog({
      title: 'Kosongkan catatan progres ini?',
      body: 'Kain dan gulungan kembali ke stok, potongan dari catatan ini ditarik dari stok, dan dokumen keluarnya dibatalkan. Potongan yang sudah dikirim ke CMT tidak bisa ditarik.',
      confirmLabel: 'Kosongkan', danger: true }))) return;
    setSaving(true);
    try {
      const res = await cuttingApi('PUT', `/orders/${order.id}/progress/${correcting.id}`, token,
        { void: true, reason: reason.trim() });
      toast.success('Catatan progres dikosongkan — stok gudang sudah dikembalikan.');
      if (res?.notice) toast.info(res.notice, { duration: 9000 });
      if (res?.mi_warning) toast.error(res.mi_warning, { duration: 12000 });
      onSaved?.(res);
    } catch (e) {
      toast.error(e.message, { duration: 12000 });
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    if (!reasonOk) { toast.error('Isi alasan koreksi dulu (minimal 5 huruf) — koreksi menggerakkan stok dan HPP.'); return; }
    const act = ins.filter((i) => calc[i.line_id]?.active);
    if (!act.length) { toast.error('Isi kain terpakai minimal untuk satu kain.'); return; }
    if (act.some((i) => !(calc[i.line_id].used > 0))) {
      toast.error('Sisa kain tidak boleh sama dengan atau melebihi kain yang diambil.');
      return;
    }
    if (!(totalPcs > 0)) { toast.error('Jumlah potongan jadi harus > 0.'); return; }
    if (anyBlocking) {
      toast.error('Pilih gulungan yang dipotong dulu — tanpa itu sisa gulungan di sistem akan menyimpang '
        + 'dari kenyataan dan lot kain tidak bisa dipertanggungjawabkan ke buyer.', { duration: 8000 });
      return;
    }
    setSaving(true);
    try {
      const res = await cuttingApi(correcting ? 'PUT' : 'POST',
        correcting ? `/orders/${order.id}/progress/${correcting.id}` : `/orders/${order.id}/progress`, token, {
        ...(correcting ? { reason: reason.trim() } : {}),
        inputs: act.map((i) => {
          const st = lines[i.line_id];
          const c = calc[i.line_id];
          return {
            line_id: i.line_id,
            input_consumed: Number(st.input_consumed),
            input_uom: (c.eff && c.eff !== c.unit) ? c.eff : undefined,
            leftover_qty: Number(st.leftover_qty || 0),
            waste_qty: Number(st.waste_qty || 0),
            waste_uom: st.waste_uom || undefined,
            roll_ids: st.roll_ids || [],
          };
        }),
        outputs: outs.filter((x) => Number(outState[x.line_id]?.output_qty || 0) > 0).map((x) => ({
          line_id: x.line_id,
          output_qty: Number(outState[x.line_id].output_qty),
          ...(outs.length > 1 ? { roll_ids: effOutRolls(x) } : {}),
        })),
        note,
      });
      if (correcting) {
        toast.success('Catatan progres dikoreksi — stok gudang & HPP potongan sudah disesuaikan.');
        if (res?.notice) toast.info(res.notice, { duration: 9000 });
        if (res?.mi_warning) toast.error(res.mi_warning, { duration: 12000 });
        if (res?.value_warning) toast.warning(res.value_warning, { duration: 12000 });
        onSaved?.(res);
        return;
      }
      toast.success('Progres tercatat — stok gudang sudah diperbarui.');
      // FASE H-6b — nomor dokumen arus keluarnya (atau peringatan kalau dokumen gagal terbit).
      const lp = res?.last_progress || {};
      if (lp.material_issue_number) {
        toast.info(`Dokumen Pengeluaran Material ${lp.material_issue_number} diterbitkan — arus keluar kain tampil di layar Gudang.`,
          { duration: 8000 });
      } else if (res?.mi_warning) {
        toast.error(res.mi_warning, { duration: 12000 });
      }
      if ((lp.roll_consumption || []).length) {
        toast.info('Gulungan dipakai: ' + lp.roll_consumption
          .map((u) => `${u.roll_no} −${fmtQty(u.qty)} (sisa ${fmtQty(u.remaining_after)})`).join(' · '), { duration: 9000 });
      }
      // SESI #32 — NILAI yang berpindah dari kain ke potongan (sama per pcs untuk semua baris hasil).
      if (lp.value_status === 'valued' && Number(lp.value_out) > 0) {
        toast.info(`Nilai kain keluar ${fmtRp(lp.value_out)} ÷ ${fmtNum(lp.output_qty)} pcs → ${fmtRp(Math.round(lp.cost_per_pcs_in))}/pcs`
          + ' masuk ke HPP potongan (rata-rata bergerak).', { duration: 9000 });
      }
      if (res?.value_warning) toast.warning(res.value_warning, { duration: 12000 });
      onSaved?.(res);
    } catch (e) {
      toast.error(e.message, { duration: 9000 });
    } finally {
      setSaving(false);
    }
  };

  if (!order) return null;
  const many = ins.length > 1;

  const renderInput = (i, n) => {
    const st = lines[i.line_id] || EMPTY_LINE;
    const c = calc[i.line_id] || { rm: EMPTY_ROLLS, alloc: { plan: [], shortage: 0, available: 0 }, eff: '', unit: '' };
    const rm = c.rm;
    const planned = (i.roll_ids || []).map((r) => r.roll_id);
    return (
      <div key={i.line_id} className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3"
        data-testid={`cutting-progress-input-${n}`}>
        <p className="text-sm font-medium text-foreground">
          {i.input_material_code} · {i.input_material_name}
          <span className="font-normal text-muted-foreground">
            {' '}— terpakai {fmtNum(i.consumed_input_qty, 2)} / {fmtNum(i.planned_input_qty, 2)} {i.input_unit}
            {many ? ' · kosongkan bila kain ini tidak dipakai pada progres ini' : ''}
          </span>
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Isian label={`Kain diambil (${c.eff || i.input_unit})`} wajib={!many}>
            <div className="flex gap-2">
              <Input type="number" step="0.0001" min="0" value={st.input_consumed}
                onChange={(e) => setLine(i.line_id, { input_consumed: e.target.value })}
                data-testid={`cutting-progress-taken-${n}`} />
              <UomSelect opt={c.opt} value={c.eff} fallbackUnit={i.input_unit}
                onChange={(e) => setLine(i.line_id, { input_uom: e.target.value })}
                testId={`cutting-progress-uom-${n}`} className="w-24 shrink-0" />
            </div>
            <UomConversionHint opt={c.opt} qty={st.input_consumed} unit={c.eff} fallbackUnit={i.input_unit} className="mt-1" />
          </Isian>
          <Isian label={`Sisa kembali ke stok (${c.eff || i.input_unit})`}
            petunjuk="Kain yang masih bisa dipakai — kembali ke stok pada harga kain.">
            <Input type="number" step="0.0001" min="0" value={st.leftover_qty}
              onChange={(e) => setLine(i.line_id, { leftover_qty: e.target.value })}
              data-testid={`cutting-progress-leftover-${n}`} />
          </Isian>
          <Isian label="Limbah" petunjuk="Bagian dari kain terpakai — nilainya ikut biaya potongan.">
            <div className="flex gap-2">
              <Input type="number" step="0.0001" min="0" value={st.waste_qty}
                onChange={(e) => setLine(i.line_id, { waste_qty: e.target.value })}
                data-testid={`cutting-progress-waste-${n}`} />
              <UomSelect opt={c.opt} value={st.waste_uom || c.eff} fallbackUnit={i.input_unit}
                onChange={(e) => setLine(i.line_id, { waste_uom: e.target.value })}
                testId={`cutting-progress-waste-uom-${n}`} className="w-24 shrink-0" />
            </div>
          </Isian>
        </div>
        {(rm.roll_required || planned.length > 0) && (
          rm.items.length === 0 ? (
            <Notice tone="danger" icon={AlertCircle} testId={`cutting-progress-no-rolls-${n}`}
              action={onNavigate && (
                <Button type="button" size="sm" variant="outline" onClick={() => onNavigate('wms-fabric-rolls')}>
                  Buka sekarang
                </Button>
              )}>
              Kain ini tidak punya gulungan bersisa di gudang order. Terbitkan gulungan di
              <b> Gudang › Roll Kain › “Penerimaan tanpa roll”</b>.
            </Notice>
          ) : (
            <Isian label={rm.roll_required ? 'Gulungan yang dipotong (wajib)' : 'Gulungan yang dipotong'}
              wajib={rm.roll_required && c.active}
              petunjuk="Centang gulungan yang benar-benar dipotong. Pemakaian dibagi otomatis FIFO (gulungan tertua dulu).">
              <div className="max-h-44 divide-y divide-[var(--glass-border)] overflow-y-auto rounded-lg border border-[var(--glass-border)]"
                data-testid={`cutting-progress-roll-picker-${n}`}>
                {rm.items.map((r) => {
                  const checked = (st.roll_ids || []).includes(r.id);
                  const inPlan = (c.alloc.plan || []).find((p) => p.roll_id === r.id);
                  return (
                    <label key={r.id} data-testid={`cutting-progress-roll-${r.roll_no}`}
                      className={`flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-foreground/5 ${checked ? 'bg-primary/5' : ''}`}>
                      <Checkbox checked={checked} data-testid={`cutting-progress-roll-cb-${r.roll_no}`}
                        onCheckedChange={() => setLine(i.line_id, { roll_ids: checked
                          ? st.roll_ids.filter((x) => x !== r.id) : [...(st.roll_ids || []), r.id] })} />
                      <span className="tabular-nums text-foreground">{r.roll_no}</span>
                      <span className="text-xs text-muted-foreground">
                        sisa {fmtQty(rollRemaining(r))} {r.uom}
                        {(r.color_lot || r.color) ? ` · lot ${r.color_lot || r.color}` : ''}
                        {planned.includes(r.id) ? ' · rencana order' : ''}
                      </span>
                      {inPlan && (
                        <span className="ml-auto text-xs font-semibold text-primary">
                          pakai {fmtQty(inPlan.qty)} → sisa {fmtQty(inPlan.remaining_after)}
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
              {c.active && (st.roll_ids || []).length > 0 && (
                <p className={`mt-1.5 text-xs ${c.alloc.shortage > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--success-text))]'}`}
                  data-testid={`cutting-alloc-preview-${n}`}>
                  {c.alloc.shortage > 0
                    ? `Sisa gulungan terpilih kurang ${fmtQty(c.alloc.shortage, 3)} ${rm.uom} — tersedia ${fmtQty(c.alloc.available)}. Pilih gulungan tambahan atau kurangi pemakaian.`
                    : `Rencana: ${c.alloc.plan.map((p) => `${p.roll_no} −${fmtQty(p.qty)}`).join(' · ')}`}
                </p>
              )}
              {c.blocking && (
                <p className="mt-1.5 text-xs text-[hsl(var(--warning-text))]" data-testid={`cutting-roll-required-hint-${n}`}>
                  Pilih minimal satu gulungan — progres tidak bisa dicatat tanpa itu.
                </p>
              )}
              {rm.other_location_count > 0 && (
                <p className="mt-1 text-xs text-[hsl(var(--warning-text))]">
                  {rm.other_location_count} gulungan kain ini ada di gudang lain — tidak bisa dipakai untuk order di gudang ini.
                </p>
              )}
            </Isian>
          )
        )}
      </div>
    );
  };

  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" testId="cutting-progress-form"
      judul={correcting ? `Koreksi catatan progres · ${order.number}` : `Catat progres potong · ${order.number}`}
      keterangan={correcting
        ? 'Angka lama dibalik dulu (stok kain, sisa gulungan, stok potongan, HPP, dokumen keluar), lalu angka di bawah ini dicatat. Potongan yang sudah dikirim ke CMT tidak bisa ditarik.'
        : 'Setiap catatan langsung memotong stok tiap kain, menambah stok potongan tiap baris hasil, dan mengurangi sisa gulungan yang ditunjuk.'}
      onSimpan={submit} menyimpan={saving} labelSimpan={correcting ? 'Simpan koreksi' : 'Catat'}
      bisaSimpan={!anyBlocking && !anyShortage && reasonOk}
      aksiKiri={correcting && (
        <Button type="button" variant="outline" onClick={voidRecord} disabled={saving}
          data-testid="cutting-progress-void"><Eraser />Kosongkan catatan</Button>
      )}>
      {correcting && (
        <Notice tone="info" icon={History} testId="cutting-progress-old">
          Catatan lama ({fmtDateTime(correcting.created_at)} oleh {correcting.created_by_name || '—'}):{' '}
          kain {(correcting.inputs || []).length
            ? correcting.inputs.map((x) => `${x.input_material_code} ${fmtNum(x.input_consumed, 2)} ${x.input_unit}`).join(', ')
            : `${fmtNum(correcting.input_consumed, 2)} ${order.input_unit || ''}`}
          {' '}→ {fmtNum(correcting.output_qty)} pcs.
          {Number(correcting.correction_count) > 0 && ` Sudah dikoreksi ${correcting.correction_count}×.`}
        </Notice>
      )}
      {ins.map((i, n) => renderInput(i, n))}

      <div className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Hasil potongan</p>
        <div className="overflow-x-auto">
          <Table data-testid="cutting-progress-outputs">
            <TableHeader><TableRow>
              <TableHead>Hasil</TableHead>
              <TableHead className="text-right">Jadi / target</TableHead>
              <TableHead className="min-w-[7rem] text-right">Potongan jadi (pcs)</TableHead>
              {outs.length > 1 && <TableHead className="min-w-[9rem]">Gulungan dipakai</TableHead>}
            </TableRow></TableHeader>
            <TableBody>
              {outs.map((x, n) => (
                <TableRow key={x.line_id}>
                  <TableCell>
                    <p className="text-foreground">{x.label}</p>
                    <p className="text-xs tabular-nums text-muted-foreground">{x.output_material_code}</p>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(x.produced_qty)} / {fmtNum(x.planned_output_qty)}</TableCell>
                  <TableCell>
                    <Input type="number" step="1" min="0" value={outState[x.line_id]?.output_qty ?? ''} className="text-right tabular-nums"
                      onChange={(e) => setOutState((m) => ({ ...m, [x.line_id]: { ...(m[x.line_id] || {}), output_qty: e.target.value } }))}
                      data-testid={`cutting-progress-output-${n}`} />
                  </TableCell>
                  {outs.length > 1 && (
                    <TableCell data-testid={`cutting-progress-output-rolls-${n}`}>
                      {pickedAll.length === 0 ? <span className="text-xs text-muted-foreground">—</span> : (
                        <div className="flex flex-col gap-1">
                          {pickedAll.map((r) => (
                            <label key={r.id} className="inline-flex cursor-pointer items-center gap-1.5 text-xs">
                              <Checkbox checked={effOutRolls(x).includes(r.id)} onCheckedChange={() => toggleOutRoll(x, r.id)} />
                              <span className="tabular-nums text-foreground">{r.roll_no}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Gulungan → hasil potongan untuk progres ini (no. roll, kain, lot warna → model/varian, pcs) */}
      <div className="space-y-2">
        <p className="text-sm font-semibold text-foreground">Gulungan dipakai untuk hasil potongan</p>
        <div className="overflow-x-auto">
          <Table data-testid="cutting-progress-roll-matrix">
            <TableHeader><TableRow>
              <TableHead>No. roll</TableHead><TableHead>Kain</TableHead><TableHead>Lot warna</TableHead>
              <TableHead className="text-right">Rencana pakai</TableHead><TableHead>Dipakai untuk</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {pickedAll.length === 0 ? (
                <TableRow><TableCell colSpan={5}>
                  <EmptyState icon={Scissors} title="Belum ada gulungan dipilih"
                    description="Centang gulungan yang dipotong di bagian kain di atas." />
                </TableCell></TableRow>
              ) : pickedAll.map((r) => {
                const used = outs.filter((x) => effOutRolls(x).includes(r.id) || outs.length === 1);
                return (
                  <TableRow key={r.id}>
                    <TableCell className="tabular-nums">{r.roll_no}</TableCell>
                    <TableCell className="tabular-nums">{r.material_code}</TableCell>
                    <TableCell>{r.color_lot || r.color || '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.plan ? `${fmtQty(r.plan.qty)} ${r.uom}` : '—'}</TableCell>
                    <TableCell className="text-xs">
                      {used.length ? used.map((x) => `${x.label}${Number(outState[x.line_id]?.output_qty) > 0
                        ? ` (${fmtNum(outState[x.line_id].output_qty)} pcs)` : ''}`).join(', ') : '—'}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>

      <p className="text-sm text-muted-foreground" data-testid="cutting-progress-hpp">
        Total <b className="tabular-nums text-foreground">{fmtNum(totalPcs)} pcs</b>
        {totalPcs > 0 && totalValue > 0 && (
          <> · perkiraan biaya kain {fmtRp(Math.round(totalValue))} ÷ {fmtNum(totalPcs)} pcs ≈{' '}
            <b className="tabular-nums text-foreground">{fmtRp(Math.round(totalValue / totalPcs))}/pcs</b> untuk semua baris
            (angka pasti memakai harga kain saat dicatat)</>
        )}
      </p>

      <Isian label="Catatan">
        <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="mis. shift pagi" data-testid="cutting-progress-note" />
      </Isian>
      {correcting && (
        <Isian label="Alasan koreksi" wajib petunjuk="Tersimpan di riwayat catatan ini bersama nama Anda dan waktunya.">
          <Input value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="mis. salah ketik jumlah potongan, seharusnya 50 pcs" data-testid="cutting-progress-reason" />
        </Isian>
      )}
    </FormPopup>
  );
}
