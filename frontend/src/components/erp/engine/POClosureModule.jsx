/**
 * POClosureModule — "Tutup PO": pantau pemenuhan PO per UKURAN + penutupan manual.
 *
 * 2026-11-06 (Tahap 2, keputusan owner):
 *   • Kekurangan dihitung PER BARIS/UKURAN (kelebihan ukuran L tidak menutupi kekurangan ukuran S).
 *   • PO tertutup otomatis ("Selesai") hanya bila SETIAP ukuran terpenuhi dan semua qty diterima dicatat.
 *   • Dua tombol tutup ("Tutup PO" & "Tutup kurang") memakai pemeriksaan yang SAMA di server: ada
 *     kekurangan ⇒ alasan wajib, PO menjadi "Ditutup kurang", jadwal piutang klien menyusut ke qty
 *     yang sudah dikirim (tanpa nota kredit ganda).
 *   • PO yang sudah ditutup TERKUNCI: kiriman material, penerimaan, kiriman ke klien, permak, permintaan
 *     komponen, dan perubahan PO ditolak.
 *
 * SSOT: /api/production-pos, /api/production-pos/{id}/fulfillment (baris per ukuran),
 *       /api/production-pos/{id}/close, /api/production-pos/{id}/close-short.
 * PANDUAN_UI: PageLayout · rincian ukuran di bawah barisnya (RowDetail) · popup hanya formulir alasan.
 * 10 Nov 2026 (owner): popup tutup punya isian DENDA dua arah (`DendaTutupPO`): denda dari klien (PO maklon) dan
 *   denda ke CMT — qty × nominal per pcs masing-masing; rincian baris menampilkan nota dendanya.
 * Tahap 9 (7 Nov 2026): popup alasan memakai `FormDialog` (ui/dialog) — bukan lagi `engine/Modal` —
 * dan status PO tampil dengan label Indonesia (`lib/poStatus`). Daftar sudah disaring per portal.
 */
import { Fragment, useEffect, useMemo, useState, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { RefreshCw, Search, AlertTriangle, Package, Info, Loader2, Scissors, Lock } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { PageLayoutSatuBaris } from './DataTable';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { Field } from './FormDialog';
import FormPopup from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Input } from '@/components/ui/input';
import { apiGet, apiPost } from '../../../lib/api';
import { portalBusinessType, portalQuery } from '@/lib/portalScope';
import { poStatusLabel, poStatusTone } from '@/lib/poStatus';
import DendaTutupPO, { DendaDaftarPO, dendaAwal, dendaGalat, dendaPayload } from './DendaTutupPO';

const REASON_LABELS = {
  deadline_expired: 'Batas waktu terlewati',
  buyer_material_shortage: 'Bahan dari klien kurang',
  cmt_quality_reject_final: 'Reject kualitas CMT (final)',
  mutual_agreement: 'Kesepakatan bersama',
};
const TERMINAL = ['Completed', 'Closed', 'Closed Short'];
const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');
const shortText = (lines) => (lines || []).filter((l) => l.short > 0)
  .map((l) => `${l.size || l.sku || 'item'} kurang ${fmtNum(l.short)}`).join(', ');

export default function POClosureModule({ portalId }) {
  const businessType = portalBusinessType(portalId);
  const [rows, setRows] = useState([]);        // [{po, fulfillment}]
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('open');       // open | closed | all
  const [search, setSearch] = useState('');
  const [openRow, setOpenRow] = useState(null);
  const [closing, setClosing] = useState(null); // {po, fulfillment}
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [denda, setDenda] = useState(() => dendaAwal(0));
  const [submitting, setSubmitting] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/production-pos${portalQuery(businessType)}`);
      const pos = Array.isArray(data) ? data : (data?.data || []);
      const settled = await Promise.allSettled(pos.map((p) => apiGet(`/production-pos/${p.id}/fulfillment`)));
      setRows(pos.map((p, i) => ({ po: p, fulfillment: settled[i].status === 'fulfilled' ? settled[i].value : null })));
    } catch (e) {
      toast.error(`Gagal memuat PO: ${e.message || e}`);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [businessType]);
  useEffect(() => { fetchAll(); }, [fetchAll]);

  const filtered = useMemo(() => {
    let r = rows;
    if (tab === 'open') r = r.filter((x) => !TERMINAL.includes(x.po.status));
    else if (tab === 'closed') r = r.filter((x) => TERMINAL.includes(x.po.status));
    const s = search.trim().toLowerCase();
    if (s) r = r.filter((x) => (x.po.po_number || '').toLowerCase().includes(s)
      || (x.po.customer_name || '').toLowerCase().includes(s));
    return r;
  }, [rows, tab, search]);
  const counts = useMemo(() => ({
    open: rows.filter((x) => !TERMINAL.includes(x.po.status)).length,
    closed: rows.filter((x) => TERMINAL.includes(x.po.status)).length,
    all: rows.length,
  }), [rows]);

  const openClose = (row) => { setClosing(row); setReason(''); setNotes(''); setDenda(dendaAwal(row.fulfillment?.total_ordered || 0)); };
  const dendaErr = dendaGalat(denda);
  const dendaAktif = denda.klien.aktif || denda.cmt.aktif;
  const short = closing?.fulfillment?.qty_short || 0;

  const submitClose = async () => {
    if (short > 0 && !reason) { toast.error('Pilih alasan tutup kurang.'); return; }
    if (dendaErr) { toast.error(dendaErr); return; }
    setSubmitting(true);
    try {
      const path = short > 0 ? 'close-short' : 'close';
      const res = await apiPost(`/production-pos/${closing.po.id}/${path}`, { closed_reason: reason, notes, close_notes: notes,
        denda: dendaPayload(denda) });
      const fin = res.finance || {};
      if (fin.credit_note_created) toast.success(`PO ditutup kurang. Nota kredit ${fin.credit_note_number} dibuat.`);
      else if (res.status === 'Closed Short') toast.success(`PO ditutup kurang (${fmtNum(res.qty_short)} pcs). Jadwal piutang disesuaikan.`);
      else toast.success('PO ditutup.');
      (res.denda || []).forEach((d) => toast.success(`${d.nomor}: denda Rp ${fmtNum(d.jumlah)} dicatat`
        + (d.jumlah_dipotong > 0 ? `, Rp ${fmtNum(d.jumlah_dipotong)} memotong ${d.pihak === 'klien' ? 'piutang klien' : 'tagihan CMT'}` : '')
        + (d.sisa > 0 ? `, sisa Rp ${fmtNum(d.sisa)} memotong tagihan berikutnya` : '')
        + (d.kredit_klien > 0 ? `, Rp ${fmtNum(d.kredit_klien)} jadi saldo kredit klien` : '') + '.'));
      setClosing(null);
      await fetchAll();
    } catch (e) {
      toast.error(`Gagal menutup PO: ${e.message || e}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <PageLayoutSatuBaris
      testId="po-closure-module"
      title="Tutup PO"
      subtitle="Pemenuhan PO per ukuran. PO yang ditutup terkunci dari kiriman, penerimaan, dan perubahan."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari no. PO atau klien"
            data-testid="po-closure-search" className="pl-8" />
        </div>
        <div data-testid="po-closure-tabs">
          <FilterChips value={tab} onChange={setTab} testId="po-closure-tab" ariaLabel="Penyaring status PO" hideWhenEmpty={false}
            options={[{ key: 'open', label: 'Perlu ditutup', count: counts.open },
              { key: 'closed', label: 'Sudah ditutup', count: counts.closed },
              { key: 'all', label: 'Semua', count: counts.all }]} />
        </div>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="tutup-po" namaLembar="Tutup PO" baris={filtered} testId="po-closure-unduh" kolom={[
          { label: 'No. PO', nilai: (x) => x.po.po_number }, { label: 'Klien', nilai: (x) => x.po.customer_name || '' },
          { label: 'Dipesan', nilai: (x) => (x.fulfillment ? Number(x.fulfillment.total_ordered) || 0 : '') },
          { label: 'Lolos QC', nilai: (x) => (x.fulfillment?.qc ? Number(x.fulfillment.qc.accepted) || 0 : '') },
          { label: 'Ditolak', nilai: (x) => (x.fulfillment?.qc ? Number(x.fulfillment.qc.reject) || 0 : '') },
          { label: 'Dikirim', nilai: (x) => (x.fulfillment ? Number(x.fulfillment.total_received) || 0 : '') },
          { label: 'Kurang', nilai: (x) => Number(x.fulfillment?.qty_short) || 0 },
          { label: 'Status', nilai: (x) => poStatusLabel(x.po.status) },
          { label: 'Alasan tutup', nilai: (x) => REASON_LABELS[x.po.closed_reason] || '' },
        ]} />
        <Button type="button" variant="outline" size="icon" onClick={fetchAll} title="Muat ulang" aria-label="Muat ulang" data-testid="po-closure-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<p className="text-sm text-muted-foreground">
        Kekurangan dihitung per ukuran. PO selesai otomatis bila setiap ukuran terpenuhi dan qty diterima klien sudah
        dicatat. Ada ukuran yang kurang ⇒ tutup kurang dengan alasan; jadwal piutang klien menyusut ke qty yang dikirim.
      </p>}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Memuat…</div>
        ) : (
          <Table>
            <TableHeader><TableRow>
              <TableHead className="w-10" />
              <TableHead>No. PO</TableHead><TableHead>Klien</TableHead>
              <TableHead className="text-right">Dipesan</TableHead><TableHead className="text-right">Lolos QC</TableHead>
              <TableHead className="text-right">Ditolak</TableHead><TableHead className="text-right">Dikirim</TableHead>
              <TableHead className="text-right">Kurang</TableHead><TableHead>Status</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {filtered.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={10} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Package} title="Tidak ada PO pada penyaring ini" description="Pilih penyaring lain atau ubah kata pencarian." />
                  </TableCell>
                </TableRow>
              )}
              {filtered.map(({ po, fulfillment: f }) => {
                const isTerminal = TERMINAL.includes(po.status);
                const open = openRow === po.id;
                const s = f?.qty_short ?? 0;
                return (
                  <Fragment key={po.id}>
                    <TableRow data-testid={`po-closure-row-${po.id}`}>
                      <TableCell><RowToggle open={open} onClick={() => setOpenRow(open ? null : po.id)} label="Lihat per ukuran" /></TableCell>
                      <TableCell className="font-medium whitespace-nowrap">{po.po_number}</TableCell>
                      <TableCell>{po.customer_name || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{f ? fmtNum(f.total_ordered) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{f?.qc ? fmtNum(f.qc.accepted) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {f?.qc && Number(f.qc.reject || 0) > 0
                          ? <span className="text-[hsl(var(--danger-text))]">{fmtNum(f.qc.reject)} ({String(f.qc.reject_rate_pct).replace('.', ',')}%)</span>
                          : fmtNum(0)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{f ? fmtNum(f.total_received) : '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s > 0 ? <span className="text-[hsl(var(--warning-text))] font-medium">{fmtNum(s)}</span> : fmtNum(0)}
                        {s > 0 && <div className="text-xs text-muted-foreground">{shortText(f.lines)}</div>}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={po.status} label={poStatusLabel(po.status)} tone={poStatusTone(po.status)} />
                        {po.closed_reason && REASON_LABELS[po.closed_reason] && (
                          <div className="text-xs text-muted-foreground">{REASON_LABELS[po.closed_reason]}</div>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {isTerminal ? (
                          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground"><Lock className="w-3.5 h-3.5" />Terkunci</span>
                        ) : f?.can_close_short ? (
                          <Button type="button" variant="outline" size="sm" onClick={() => openClose({ po, fulfillment: f })} data-testid={`po-close-short-btn-${po.id}`}>
                            <Scissors className="w-3.5 h-3.5" />Tutup kurang
                          </Button>
                        ) : f?.can_close && s === 0 ? (
                          <Button type="button" variant="outline" size="sm" onClick={() => openClose({ po, fulfillment: f })} data-testid={`po-close-btn-${po.id}`}>
                            <Lock className="w-3.5 h-3.5" />Tutup PO
                          </Button>
                        ) : <span className="text-xs text-muted-foreground">—</span>}
                      </TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={10} testId={`po-closure-lines-${po.id}`}>
                        <div className="space-y-3">
                        {(f?.lines || []).length === 0 ? (
                          <p className="text-sm text-muted-foreground">Rincian per ukuran tidak tersedia.</p>
                        ) : (
                          <Table>
                            <TableHeader><TableRow>
                              <TableHead>Ukuran / barang</TableHead><TableHead className="text-right">Dipesan</TableHead>
                              <TableHead className="text-right">Lolos QC</TableHead><TableHead className="text-right">Terpenuhi</TableHead>
                              <TableHead className="text-right">Kurang</TableHead><TableHead className="text-right">Lebih</TableHead>
                            </TableRow></TableHeader>
                            <TableBody>{f.lines.map((ln) => (
                              <TableRow key={ln.po_item_id}>
                                <TableCell>{ln.size || '—'} <span className="text-muted-foreground">{ln.sku}</span></TableCell>
                                <TableCell className="text-right tabular-nums">{fmtNum(ln.ordered)}</TableCell>
                                <TableCell className="text-right tabular-nums">{fmtNum(ln.accepted)}</TableCell>
                                <TableCell className="text-right tabular-nums">{fmtNum(ln.fulfilled)}</TableCell>
                                <TableCell className={`text-right tabular-nums ${ln.short > 0 ? 'text-[hsl(var(--warning-text))] font-medium' : ''}`}>{fmtNum(ln.short)}</TableCell>
                                <TableCell className="text-right tabular-nums">{fmtNum(ln.over)}</TableCell>
                              </TableRow>
                            ))}</TableBody>
                          </Table>
                        )}
                        {isTerminal && <DendaDaftarPO poId={po.id} />}
                        </div>
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {closing && (
        <FormPopup open onClose={() => setClosing(null)} ukuran={dendaAktif ? 'panjang' : 'pendek'}
          testId="po-close-short-modal" judul={short > 0 ? 'Tutup kurang' : 'Tutup PO'} galat={dendaAktif ? dendaErr : ''}
          keterangan={`${closing.po.po_number} · ${closing.po.customer_name || ''} · dipesan ${fmtNum(closing.fulfillment.total_ordered)} · terpenuhi ${fmtNum(closing.fulfillment.total_fulfilled)}`}
          onSimpan={submitClose} menyimpan={submitting} bisaSimpan={!(short > 0 && !reason) && !dendaErr} labelSimpan={short > 0 ? 'Tutup kurang' : 'Tutup PO'}>
          {short > 0 ? (
            <Notice tone="warning" icon={AlertTriangle}>
              Kurang {fmtNum(short)} pcs: {shortText(closing.fulfillment.lines)}. PO menjadi <b>Ditutup kurang</b> dan terkunci;
              jadwal piutang klien menyusut ke qty yang sudah dikirim.
            </Notice>
          ) : (
            <Notice tone="info" icon={Info}>Setiap ukuran sudah terpenuhi. PO menjadi <b>Ditutup</b> dan terkunci.</Notice>
          )}
          {short > 0 && (
            <Field label="Alasan tutup kurang *">
              <SmartNativeSelect value={reason} onChange={(e) => setReason(e.target.value)} data-testid="po-close-short-reason" className="w-full h-9" aria-label="Alasan tutup kurang">
                <option value="">— pilih alasan —</option>
                {(closing.fulfillment.close_short_reasons || Object.keys(REASON_LABELS)).map((r) => (
                  <option key={r} value={r}>{REASON_LABELS[r] || r}</option>
                ))}
              </SmartNativeSelect>
            </Field>
          )}
          <Field label="Catatan">
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} data-testid="po-close-short-notes"
              placeholder="mis. klien membatalkan sisa pesanan karena musim berakhir" />
          </Field>
          <DendaTutupPO po={closing.po} qtyPesanan={closing.fulfillment?.total_ordered} value={denda} onChange={setDenda} />
        </FormPopup>
      )}
    </PageLayoutSatuBaris>
  );
}
