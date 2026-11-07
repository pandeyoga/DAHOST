/**
 * AccessoryValuationTab — FASE 8: Valuasi HPP Aksesoris.
 *
 * MASALAH YANG DIPECAHKAN
 * Harga satuan (HPP) aksesoris sudah bisa diisi & opname sudah berjurnal, tapi mutasi
 * harian (terima / keluar / scrap) tidak pernah dinilai ⇒ nilai persediaan aksesoris
 * tidak pernah cocok dengan buku besar, dan item ber-HPP 0 diam-diam membuat jurnal
 * gagal terbentuk. Tab ini menampilkan nilai persediaan, menyorot item BELUM DINILAI,
 * dan menyediakan dua aksi bernilai: koreksi HPP dan scrap (write-off).
 *
 * Sumber data: /api/acc/valuation (+ /valuation/set-cost, /api/acc/stock/scrap)
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (di dalam tab modul Aksesoris kepala tersembunyi), penyaring
 * satu baris, tabel = TabelData + unduh Excel/CSV, form Set HPP / Scrap / rapor = FormPopup, panel otomasi
 * dipindah ke popup (dulu dua panel besar mendorong tabel ke bawah), rekap per kategori = tabel.
 */

import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { monthOptions } from '../finance/PeriodPicker';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import {
  AlertTriangle, RefreshCw, Search, X, Trash2, Tag, Package, Info, FileSpreadsheet, Settings2,
} from 'lucide-react';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { thisMonthWIB } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import AccessoryValuationLedger from './AccessoryValuationLedger';
// FASE 10: otomasi — ringkasan harian item belum dinilai + rapor bulanan via email
import AccessoryValuationAutomation from './AccessoryValuationAutomation';

// 2026-11-07 (Tahap 5): periode rapor = pilihan bulan aplikasi (dulu isian bulan bawaan browser)
const MONTH_OPTIONS = monthOptions(24);

const API = process.env.REACT_APP_BACKEND_URL || '';

async function api(method, path, token, body) {
  const opts = { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${API}${path}`, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(data.detail || `HTTP ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return data;
}

const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 4 });
const fmtRp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}`;

const METHOD_LABEL = { moving_average: 'Rata-rata bergerak', manual: 'Manual' };
const SCRAP_REASONS = ['Rusak', 'Hilang', 'Kadaluarsa', 'Cacat produksi', 'Lain-lain'];

export default function AccessoryValuationTab({ token, onRefreshDash }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [formErr, setFormErr] = useState('');
  const [msg, setMsg] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [saving, setSaving] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [month, setMonth] = useState(thisMonthWIB);
  const [downloading, setDownloading] = useState('');
  const [raporOpen, setRaporOpen] = useState(false);
  const [raporFormat, setRaporFormat] = useState('xlsx');
  const [otomasiOpen, setOtomasiOpen] = useState(false);
  const [costForm, setCostForm] = useState(null);   // {id, name, unit_cost, stock_qty}
  const [scrapForm, setScrapForm] = useState(null); // {id, name, unit, stock_qty, unit_cost}

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const d = await api('GET', '/api/acc/valuation', token);
      setData(d);
    } catch (e) { setErr(e.message); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const items = data?.items || [];
  const totals = data?.totals || {};
  const cocokCari = (it) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (it.name || '').toLowerCase().includes(q) || (it.code || '').toLowerCase().includes(q);
  };
  const filtered = items.filter((it) => {
    if (filter === 'unvalued' && it.valued) return false;
    if (filter === 'instock' && !(it.stock_qty > 0)) return false;
    return cocokCari(it);
  });
  const pg = useClientPagination(filtered, 25);
  const dicari = items.filter(cocokCari);
  const opsiSaring = [
    { key: '', label: 'Semua item', count: dicari.length },
    { key: 'instock', label: 'Berstok', count: dicari.filter((it) => it.stock_qty > 0).length },
    { key: 'unvalued', label: 'Belum dinilai', count: dicari.filter((it) => !it.valued).length },
  ];

  // Rapor valuasi untuk lampiran laporan keuangan (Excel utk diolah, PDF utk ditandatangani).
  const downloadReport = async (fmt) => {
    setDownloading(fmt); setFormErr(''); setMsg('');
    try {
      const qs = new URLSearchParams({ format: fmt });
      if (month) qs.set('month', month);
      const r = await fetch(`${API}/api/acc/valuation/export?${qs}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${r.status}`);
      }
      const blob = await r.blob();
      const cd = r.headers.get('Content-Disposition') || '';
      const guess = (cd.match(/filename="?([^";]+)"?/) || [])[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = guess || `valuasi-aksesoris-${month || 'semua'}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setMsg(`Rapor ${fmt === 'pdf' ? 'PDF' : 'Excel'} periode ${month || 'semua'} berhasil diunduh.`);
      setRaporOpen(false);
    } catch (e) { setFormErr(e.message); }
    finally { setDownloading(''); }
  };

  const saveCost = async () => {
    const val = parseFloat(costForm.unit_cost);
    if (!(val >= 0)) { setFormErr('Harga satuan harus angka ≥ 0'); return; }
    // 2026-11-02 (K12): Set HPP = revaluasi bernilai audit → alasan wajib
    if (!String(costForm.notes || '').trim()) { setFormErr('Alasan koreksi HPP wajib diisi (jejak audit revaluasi).'); return; }
    setSaving(true); setFormErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/acc/valuation/set-cost', token, {
        acc_id: costForm.id, unit_cost: val, notes: costForm.notes || '',
      });
      const rv = res.revaluation || {};
      setMsg(`HPP ${costForm.name} disimpan: ${fmtRp(res.old_unit_cost)} → ${fmtRp(res.new_unit_cost)} · nilai stok ${fmtRp(res.stock_value)}`
        + (rv.reval_number ? ` · revaluasi ${rv.reval_number} ${rv.delta_value >= 0 ? '+' : '−'}${fmtRp(Math.abs(rv.delta_value || 0))}`
          + (rv.je_number ? ` (jurnal ${rv.je_number})` : ' (tanpa jurnal: selisih 0)') : ''));
      setCostForm(null);
      setRefreshKey((k) => k + 1);
      await load();
      onRefreshDash?.();
    } catch (e) { setFormErr(e.message); }
    finally { setSaving(false); }
  };

  const doScrap = async () => {
    const qty = parseFloat(scrapForm.qty);
    if (!qty || qty <= 0) { setFormErr('Qty scrap harus lebih dari 0'); return; }
    if (!(scrapForm.reason || '').trim()) { setFormErr('Alasan scrap wajib diisi (untuk jejak audit & jurnal)'); return; }
    setSaving(true); setFormErr(''); setMsg('');
    try {
      const res = await api('POST', '/api/acc/stock/scrap', token, {
        acc_id: scrapForm.id, qty, reason: scrapForm.reason, notes: scrapForm.notes || '',
      });
      setMsg(
        `Scrap ${fmtNum(res.qty_scrapped)} ${scrapForm.unit} · nilai ${fmtRp(res.value)} · `
        + (res.je?.posted ? `jurnal ${res.je.je_number} di-posting` : `tanpa jurnal (${res.je?.error || 'HPP 0'})`),
      );
      setScrapForm(null);
      setRefreshKey((k) => k + 1);
      await load();
      onRefreshDash?.();
    } catch (e) { setFormErr(e.message); }
    finally { setSaving(false); }
  };

  const bukaSetHpp = (it) => {
    setFormErr('');
    setCostForm({ id: it.id, name: it.name, unit_cost: it.unit_cost || '', notes: '', old_cost: Number(it.unit_cost || 0), stock_qty: Number(it.stock_qty || 0), unit: it.unit });
  };
  const bukaScrap = (it) => {
    setFormErr('');
    setScrapForm({ id: it.id, name: it.name, unit: it.unit, stock_qty: it.stock_qty, unit_cost: it.unit_cost, qty: '', reason: '', notes: '' });
  };

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (it) => <span className="whitespace-nowrap tabular-nums">{it.code}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (it) => <span className="font-medium">{it.name}</span> },
    { kunci: 'kategori', label: 'Kategori', isi: (it) => <span className="text-muted-foreground">{it.category || '—'}</span> },
    { kunci: 'stok', label: 'Stok', rata: 'kanan', isi: (it) => (
      <span className="tabular-nums">{fmtNum(it.stock_qty)} <span className="text-xs text-muted-foreground">{it.unit}</span></span>) },
    // Metode penilaian ditulis kecil di bawah HPP (dulu kolom sendiri → tombol Scrap terpotong di kanan).
    { kunci: 'hpp', label: 'HPP', rata: 'kanan', isi: (it) => (
      <div>
        {it.valued
          ? <span className="tabular-nums">{fmtRp(it.unit_cost)}</span>
          : <span className="text-[hsl(var(--warning-text))]" title="Belum dinilai — jurnal persediaan tidak akan terbentuk">belum diisi</span>}
        {METHOD_LABEL[it.cost_method] && <p className="text-xs text-muted-foreground">{METHOD_LABEL[it.cost_method]}</p>}
      </div>) },
    { kunci: 'nilai', label: 'Nilai stok', rata: 'kanan', isi: (it) => (
      <span className="font-medium tabular-nums">{it.stock_value > 0 ? fmtRp(it.stock_value) : '—'}</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => bukaSetHpp(it)} title="Set / koreksi harga satuan"
          data-testid={`acc-set-cost-${it.id}`}>
          <Tag /> Set HPP
        </Button>
        <Button size="sm" variant="outline" onClick={() => bukaScrap(it)} disabled={!(it.stock_qty > 0)}
          title={it.stock_qty > 0 ? 'Scrap / hapus buku stok' : 'Stok kosong'} data-testid={`acc-scrap-${it.id}`}>
          <Trash2 className="text-[hsl(var(--danger-text))]" /> Scrap
        </Button>
      </div>) },
  ];

  // Skeleton HANYA pada muat pertama (saat `data` masih kosong). Kalau tidak,
  // setiap refresh setelah aksi akan meng-UNMOUNT seluruh isi tab — termasuk
  // panel otomasi anak — sehingga pesan hasil aksi (mis. "SMTP belum diisi")
  // ikut hilang sebelum sempat terbaca user. Ini bug nyata yang ketemu saat uji UI.
  if (loading && !data) {
    return <p className="py-6 text-center text-sm text-muted-foreground" data-testid="acc-valuation-loading">Memuat valuasi…</p>;
  }

  const adaStok = Number(totals.total_qty || 0) > 0;

  return (
    <PageLayout testId="acc-valuation-tab" title="Valuasi HPP"
      subtitle="Nilai persediaan aksesoris, item belum dinilai, koreksi HPP, dan scrap."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); pg.setPage(1); }}
            placeholder="Cari kode atau nama" className="pl-8 pr-8" data-testid="acc-val-search" />
          {search && (
            <Button type="button" variant="ghost" size="icon-sm" onClick={() => setSearch('')}
              className="absolute right-0.5 top-1/2 -translate-y-1/2" title="Hapus pencarian" aria-label="Hapus pencarian">
              <X />
            </Button>
          )}
        </div>
        <FilterChips options={opsiSaring} value={filter} onChange={(v) => { setFilter(v); pg.setPage(1); }}
          hideWhenEmpty={false} testId="acc-val-filter" />
      </>}
      tools={<>
        <Button variant="outline" onClick={() => { setFormErr(''); setRaporOpen(true); }} data-testid="acc-val-rapor-btn">
          <FileSpreadsheet /> Rapor
        </Button>
        <Button variant="outline" onClick={() => setOtomasiOpen(true)} data-testid="acc-val-otomasi-btn">
          <Settings2 /> Otomasi
        </Button>
        <TombolUnduh namaBerkas="valuasi-aksesoris" namaLembar="Valuasi" baris={filtered} testId="acc-val-unduh"
          kolom={[
            { label: 'Kode', nilai: (it) => it.code },
            { label: 'Nama', nilai: (it) => it.name },
            { label: 'Kategori', nilai: (it) => it.category || '' },
            { label: 'Stok', nilai: (it) => Number(it.stock_qty || 0) },
            { label: 'Satuan', nilai: (it) => it.unit },
            { label: 'HPP (Rp)', nilai: (it) => (it.valued ? Number(it.unit_cost || 0) : '') },
            { label: 'Nilai stok (Rp)', nilai: (it) => Number(it.stock_value || 0) },
            { label: 'Metode', nilai: (it) => METHOD_LABEL[it.cost_method] || '' },
            { label: 'Status', nilai: (it) => (it.valued ? 'Bernilai' : 'Belum dinilai') },
          ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="acc-val-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={<>
        {/* Nilai persediaan total sudah tampil di kartu atas modul Aksesoris — di sini rinciannya. */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Item bernilai" value={fmtNum(totals.valued_items)}
            sub={`dari ${fmtNum(totals.total_items)} item · punya HPP`} />
          <StatTile label="Belum dinilai" value={fmtNum(totals.unvalued_items)}
            accent={totals.unvalued_items ? 'warning' : 'default'}
            sub={totals.unvalued_items ? `${fmtNum(totals.unvalued_qty)} unit stok tanpa nilai` : 'Semua item sudah dinilai'} />
          <StatTile label="Jumlah stok" value={fmtNum(totals.total_qty)}
            sub={`Bernilai ${fmtRp(totals.total_value)}`} />
          <StatTile label="HPP rata-rata" value={adaStok ? fmtRp(totals.avg_unit_cost) : '—'}
            sub={adaStok ? (METHOD_LABEL[data?.cost_method] || data?.cost_method) : 'Belum ada stok untuk dirata-rata'}
            hint="Nilai persediaan ÷ jumlah stok." />
        </div>
        {/* Peringatan item belum dinilai */}
        {totals.unvalued_items > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="acc-val-unvalued-banner"
            title={`${totals.unvalued_items} item belum punya harga satuan`}
            action={filter !== 'unvalued' && (
              <Button size="sm" variant="outline" onClick={() => { setFilter('unvalued'); pg.setPage(1); }}
                data-testid="acc-val-filter-unvalued">
                Tampilkan item belum dinilai
              </Button>
            )}>
            Selama HPP masih 0, penerimaan, pengeluaran, dan selisih opname item itu tidak menghasilkan jurnal keuangan.
            Isi lewat tombol Set HPP di tabel.
          </Notice>
        )}
      </>}
      footer={<PaginationLite page={pg.page} totalPages={pg.totalPages} total={pg.total}
        pageSize={pg.pageSize} onPageChange={pg.setPage} />}>
      {err && <Notice tone="danger" testId="acc-val-error">{err}</Notice>}
      {msg && <Notice tone="success" testId="acc-val-msg">{msg}</Notice>}

      <TabelData kolom={kolom} baris={pg.paged} testId="acc-val-table"
        kosong={<EmptyState icon={Package} title="Tidak ada item"
          description="Sesuaikan pencarian atau saringan untuk melihat item aksesoris." />} />

      {/* Rekap per kategori */}
      {(data?.by_category || []).length > 0 && (
        <div className="space-y-2" data-testid="acc-val-by-category">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-base font-semibold">Nilai persediaan per kategori</p>
            <TombolUnduh namaBerkas="valuasi-aksesoris-per-kategori" namaLembar="Per kategori" baris={data.by_category}
              testId="acc-val-cat-unduh"
              kolom={[
                { label: 'Kategori', nilai: (c) => c.category },
                { label: 'Item', nilai: (c) => Number(c.items || 0) },
                { label: 'Stok (unit)', nilai: (c) => Number(c.qty || 0) },
                { label: 'Nilai (Rp)', nilai: (c) => Number(c.value || 0) },
                { label: 'Belum dinilai', nilai: (c) => Number(c.unvalued_items || 0) },
              ]} />
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Kategori</TableHead>
                <TableHead className="text-right">Item</TableHead>
                <TableHead className="text-right">Stok (unit)</TableHead>
                <TableHead className="text-right">Belum dinilai</TableHead>
                <TableHead className="text-right">Nilai</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.by_category.map((c) => (
                <TableRow key={c.category} data-testid={`acc-val-cat-${c.category}`}>
                  <TableCell className="font-medium">{c.category}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(c.items)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(c.qty)}</TableCell>
                  <TableCell className={`text-right tabular-nums ${c.unvalued_items ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground'}`}>
                    {fmtNum(c.unvalued_items || 0)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{fmtRp(c.value)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Kartu stok bernilai + riwayat HPP */}
      <AccessoryValuationLedger token={token} refreshKey={refreshKey} />

      {/* FASE 10 — otomasi: ringkasan harian "belum dinilai" + rapor bulanan ke email keuangan (popup) */}
      <DetailPopup open={otomasiOpen} onClose={() => setOtomasiOpen(false)} testId="acc-val-otomasi"
        judul="Otomasi valuasi" keterangan="Alarm harian item belum dinilai dan rapor bulanan otomatis ke keuangan.">
        <AccessoryValuationAutomation token={token} onChanged={load} />
      </DetailPopup>

      {/* Rapor bulanan — lampiran laporan keuangan */}
      <FormPopup open={raporOpen} onClose={() => setRaporOpen(false)} ukuran="pendek"
        onSimpan={() => downloadReport(raporFormat)} menyimpan={!!downloading} galat={formErr}
        judul="Unduh rapor valuasi" labelSimpan="Unduh rapor" testId="acc-val-rapor"
        keterangan="Nilai persediaan = posisi terkini; periode hanya menyaring tabel mutasi.">
        <Isian label="Periode mutasi" htmlFor="acc-val-month">
          <SmartNativeSelect id="acc-val-month" value={month} onChange={e => setMonth(e.target.value)}
            className="w-full" data-testid="acc-val-month">
            {MONTH_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Format">
          <FilterChips value={raporFormat} onChange={setRaporFormat} hideWhenEmpty={false} testId="acc-val-export"
            options={[{ key: 'xlsx', label: 'Excel (untuk diolah)' }, { key: 'pdf', label: 'PDF (untuk ditandatangani)' }]} />
        </Isian>
      </FormPopup>

      {/* Set HPP (popup pendek) */}
      {costForm && (
        <FormPopup open onClose={() => setCostForm(null)} ukuran="pendek" onSimpan={saveCost} menyimpan={saving}
          galat={formErr} judul="Set harga satuan (HPP)" keterangan={costForm.name} testId="acc-set-cost-modal">
          <Isian label="Harga satuan (Rp)" wajib htmlFor="acc-set-cost-input">
            <MoneyInput id="acc-set-cost-input" decimals={2} value={costForm.unit_cost}
              onChange={(e) => setCostForm({ ...costForm, unit_cost: e.target.value })}
              placeholder="0" data-testid="acc-set-cost-input" />
          </Isian>
          <Isian label="Alasan koreksi" wajib htmlFor="acc-set-cost-notes">
            <Input id="acc-set-cost-notes" value={costForm.notes} onChange={(e) => setCostForm({ ...costForm, notes: e.target.value })}
              placeholder="mis. hasil audit harga beli terakhir" data-testid="acc-set-cost-notes" />
          </Isian>
          {(() => {
            const nv = parseFloat(costForm.unit_cost);
            const delta = Number.isFinite(nv) ? (costForm.stock_qty || 0) * (nv - (costForm.old_cost || 0)) : 0;
            return (
              <div className="rounded-[var(--radius-md)] border border-[var(--glass-border)] px-3 py-2 text-sm" data-testid="acc-set-cost-preview">
                <div className="text-muted-foreground">Revaluasi stok bernilai</div>
                <div className="tabular-nums">
                  {fmtNum(costForm.stock_qty || 0)} {costForm.unit || ''} × ({Number.isFinite(nv) ? fmtRp(nv) : '—'} − {fmtRp(costForm.old_cost || 0)})
                  {' = '}<strong className={delta < 0 ? 'text-[hsl(var(--danger-text))]' : ''}>{delta < 0 ? '−' : '+'}{fmtRp(Math.abs(delta))}</strong>
                </div>
              </div>
            );
          })()}
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Set HPP mengubah nilai SELURUH stok yang ada sekarang. Selisihnya dibukukan sebagai dokumen revaluasi
            + jurnal: Persediaan Aksesoris (1-1402) lawan Selisih Persediaan (5-1950). Alasan, pelaku, dan riwayat tercatat.
          </p>
        </FormPopup>
      )}

      {/* Scrap (popup pendek) */}
      {scrapForm && (
        <FormPopup open onClose={() => setScrapForm(null)} ukuran="pendek" onSimpan={doScrap} menyimpan={saving}
          galat={formErr} judul="Scrap / susut aksesoris" labelSimpan="Scrap" testId="acc-scrap-modal"
          keterangan={`${scrapForm.name} · stok ${fmtNum(scrapForm.stock_qty)} ${scrapForm.unit}`}>
          <Isian label={`Jumlah di-scrap (${scrapForm.unit})`} wajib htmlFor="acc-scrap-qty"
            petunjuk={scrapForm.qty > 0 && scrapForm.unit_cost > 0
              ? `Nilai hapus buku ≈ ${fmtRp(parseFloat(scrapForm.qty || 0) * scrapForm.unit_cost)}` : undefined}>
            <Input id="acc-scrap-qty" type="number" min="0.01" step="0.01" value={scrapForm.qty}
              onChange={(e) => setScrapForm({ ...scrapForm, qty: e.target.value })}
              placeholder="0" data-testid="acc-scrap-qty" />
          </Isian>
          <Isian label="Alasan" wajib>
            <SmartNativeSelect value={scrapForm.reason}
              onChange={(e) => setScrapForm({ ...scrapForm, reason: e.target.value })}
              className="w-full" data-testid="acc-scrap-reason">
              <option value="">— pilih alasan —</option>
              {SCRAP_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Catatan" htmlFor="acc-scrap-notes">
            <Input id="acc-scrap-notes" value={scrapForm.notes} onChange={(e) => setScrapForm({ ...scrapForm, notes: e.target.value })}
              placeholder="Keterangan tambahan..." data-testid="acc-scrap-notes" />
          </Isian>
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Scrap = hapus buku nilai persediaan: jurnal Beban Scrap (Dr) / Persediaan (Cr) dibuat otomatis bila HPP sudah terisi.
          </p>
        </FormPopup>
      )}
    </PageLayout>
  );
}
