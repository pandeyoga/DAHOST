import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, TrendingUp, TrendingDown, Minus, Info } from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer,
} from 'recharts';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS } from './finance/PeriodPicker';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

/**
 * Riwayat Harga Barang (sesi #33).
 *
 * Kenapa layar ini ada: `rahaza_material_cost_history` sudah terisi otomatis
 * setiap pembelian (dan setiap potong, sejak sesi #32) untuk SEMUA jenis
 * material, tetapi satu-satunya pembacanya adalah layar **Valuasi Aksesoris**.
 * Akibatnya tidak ada tempat untuk menjawab "kenapa HPP potongan/produk saya
 * berubah?" — padahal seluruh HPP sesi #31/#32 lahir dari angka ini.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout; daftar barang berupa kartu di kolom kiri (lebih besar dari isi
 * utama, bergulir sendiri) → satu pilihan "Barang" yang bisa dicari di baris penyaring; dua kotak tanggal
 * bawaan peramban → PeriodPicker (bawaan "Semua waktu" = tanpa saringan tanggal, sama seperti dulu);
 * kartu angka = StatTile; tabel → kartu ringkas di HP; unduh Excel/CSV.
 * Angka kartu = `summary` /api/rahaza/material-costs/materials (diverifikasi 8 Nov 2026 di DB uji: 1.726 barang
 * aktif, 0 riwayat di rahaza_material_cost_history, 702 barang unit_cost 0).
 */

const rp = (v) => `Rp${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}`;
const num = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 });
const JENIS_LABEL = {
  yarn: 'Bahan', fabric: 'Bahan', kain: 'Bahan', benang: 'Bahan', interlining: 'Bahan',
  accessory: 'Aksesoris', packaging: 'Aksesoris', panel: 'Potongan', fg: 'Produk jadi',
};
const jenisLabel = (t) => JENIS_LABEL[t] || 'Lainnya';
const METODE_LABEL = { moving_average: 'rata-rata bergerak', wac: 'rata-rata pembelian', manual: 'koreksi manual', opening: 'harga awal' };

function sumberDari(row) {
  const label = row.source_label || (row.source ? 'Lainnya' : '—');
  const tone = /cutting/i.test(label) ? 'primary' : /manual|koreksi/i.test(label) ? 'warning' : 'success';
  return { label, tone };
}

export default function MaterialCostHistoryModule({ token }) {
  const [mats, setMats] = useState([]);
  const [matSummary, setMatSummary] = useState(null);
  const [loadingMats, setLoadingMats] = useState(true);
  const [filterType, setFilterType] = useState('');
  const [onlyChanged, setOnlyChanged] = useState(true);
  const [selectedId, setSelectedId] = useState('');
  const [data, setData] = useState(null);
  const [loadingData, setLoadingData] = useState(false);
  const [period, setPeriod] = useState({ preset: 'all', from: '', to: '' });
  const dateFrom = period.from || '';
  const dateTo = period.to || '';

  const headers = useMemo(() => ({
    Authorization: `Bearer ${token || localStorage.getItem('erp_token')}`,
    'Content-Type': 'application/json',
  }), [token]);

  const loadMats = useCallback(async () => {
    setLoadingMats(true);
    try {
      const p = new URLSearchParams({ only_with_history: String(onlyChanged), limit: 2000 });
      if (filterType) p.set('type', filterType);
      const r = await fetch(`/api/rahaza/material-costs/materials?${p}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setMats(d.items || []);
      setMatSummary(d.summary || null);
    } catch (e) {
      toast.error(`Gagal memuat daftar barang: ${e.message}`);
    } finally { setLoadingMats(false); }
  }, [headers, filterType, onlyChanged]);

  const loadData = useCallback(async () => {
    setLoadingData(true);
    try {
      const p = new URLSearchParams({ limit: 500 });
      if (selectedId) p.set('material_id', selectedId);
      else if (filterType) p.set('type', filterType);
      if (dateFrom) p.set('date_from', dateFrom);
      if (dateTo) p.set('date_to', dateTo);
      const r = await fetch(`/api/rahaza/material-costs/history?${p}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
    } catch (e) {
      toast.error(`Gagal memuat riwayat harga: ${e.message}`);
    } finally { setLoadingData(false); }
  }, [headers, selectedId, filterType, dateFrom, dateTo]);

  useEffect(() => { loadMats(); }, [loadMats]);
  useEffect(() => { loadData(); }, [loadData]);

  const items = data?.items || [];
  const s = data?.summary || {};
  const chart = useMemo(() => [...items].reverse().map(r => ({
    t: formatDateID(r.created_at),
    harga: Number(r.new_unit_cost || 0),
  })), [items]);

  const trend = s.change_pct == null ? null : Number(s.change_pct);
  const TrendIcon = trend == null ? Minus : trend > 0 ? TrendingUp : trend < 0 ? TrendingDown : Minus;
  const trendTone = trend == null ? 'text-muted-foreground'
    : trend > 0 ? 'text-[hsl(var(--danger-text))]' : trend < 0 ? 'text-[hsl(var(--success-text))]' : 'text-muted-foreground';

  const selected = mats.find(m => m.material_id === selectedId);
  const memuat = loadingMats || loadingData;

  const kolom = [
    { kunci: 'waktu', label: 'Waktu', hp: 'keterangan', isi: (r) => <span className="whitespace-nowrap">{formatDateTimeID(r.created_at)}</span> },
    ...(!selectedId ? [{ kunci: 'barang', label: 'Barang', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <div className="tabular-nums text-xs text-muted-foreground">{r.material_code}</div>
        <div className={r.material_missing ? 'text-[hsl(var(--warning-text))]' : 'text-foreground'}>{r.material_name}</div>
      </div>) }] : []),
    { kunci: 'sumber', label: 'Sumber', isi: (r) => { const x = sumberDari(r); return <StatusBadge status="sumber" label={x.label} tone={x.tone} />; } },
    { kunci: 'qty_in', label: 'Qty masuk', rata: 'kanan', isi: (r) => <span className="tabular-nums">{num(r.qty_in)}</span> },
    { kunci: 'cost_in', label: 'Harga masuk', rata: 'kanan', isi: (r) => <span className="tabular-nums">{rp(r.unit_cost_in)}</span> },
    { kunci: 'old', label: 'Harga lama', rata: 'kanan', isi: (r) => <span className="tabular-nums text-muted-foreground">{rp(r.old_unit_cost)}</span> },
    { kunci: 'new', label: 'Harga baru', rata: 'kanan', isi: (r) => <span className="tabular-nums font-medium">{rp(r.new_unit_cost)}</span> },
    { kunci: 'pct', label: 'Perubahan', rata: 'kanan', isi: (r) => (r.change_pct == null
      ? <span className="text-xs text-muted-foreground">harga pertama</span>
      : <span className={`tabular-nums font-medium ${r.change_pct > 0 ? 'text-[hsl(var(--danger-text))]' : r.change_pct < 0 ? 'text-[hsl(var(--success-text))]' : 'text-muted-foreground'}`}
          data-testid={`cost-change-${r.id}`}>
          {r.change_pct > 0 ? '+' : ''}{String(r.change_pct).replace('.', ',')}%
        </span>) },
    { kunci: 'oleh', label: 'Oleh', isi: (r) => (
      <div className="text-muted-foreground">
        {r.actor_name}
        {r.notes && <span className="block line-clamp-1 text-xs" title={r.notes}>{r.notes}</span>}
      </div>) },
  ];

  return (
    <PageLayout testId="cost-history-page" title="Riwayat harga"
      subtitle="Setiap perubahan HPP rata-rata bergerak — dari pembelian, hasil cutting, dan koreksi manual."
      filters={<>
        <SmartNativeSelect value={selectedId} onChange={e => setSelectedId(e.target.value)} className="w-64"
          searchable aria-label="Barang" data-testid="cost-material-list" disabled={loadingMats && !mats.length}>
          <option value="">Semua perubahan terbaru</option>
          {mats.map(m => (
            <option key={m.material_id} value={m.material_id}>{`${m.code} — ${m.name} (${m.changes} kali)`}</option>
          ))}
        </SmartNativeSelect>
        <SmartNativeSelect value={filterType} onChange={e => setFilterType(e.target.value)} className="w-44"
          searchable={false} aria-label="Jenis" data-testid="cost-filter-type">
          <option value="">Semua jenis</option>
          <option value="bahan">Bahan (kain/benang)</option>
          <option value="aksesoris">Aksesoris</option>
          <option value="panel">Potongan</option>
          <option value="fg">Produk jadi</option>
        </SmartNativeSelect>
        <PeriodPicker value={period} onChange={setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId="cost-period" />
        <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-foreground">
          <Checkbox checked={onlyChanged} onCheckedChange={(v) => setOnlyChanged(!!v)} data-testid="cost-only-changed" />
          Hanya yang pernah berubah harga
        </label>
      </>}
      tools={<>
        <TombolUnduh namaBerkas={selected ? `riwayat-harga-${selected.code}` : 'riwayat-harga'} namaLembar="Riwayat harga"
          baris={items} testId="cost-history-unduh"
          kolom={[
            { label: 'Waktu', nilai: (r) => formatDateTimeID(r.created_at, { fallback: '' }) },
            { label: 'Kode barang', nilai: (r) => r.material_code || selected?.code || '' },
            { label: 'Nama barang', nilai: (r) => r.material_name || selected?.name || '' },
            { label: 'Sumber', nilai: (r) => sumberDari(r).label },
            { label: 'Qty masuk', nilai: (r) => Number(r.qty_in || 0) },
            { label: 'Harga masuk (Rp)', nilai: (r) => Number(r.unit_cost_in || 0) },
            { label: 'Harga lama (Rp)', nilai: (r) => Number(r.old_unit_cost || 0) },
            { label: 'Harga baru (Rp)', nilai: (r) => Number(r.new_unit_cost || 0) },
            { label: 'Perubahan (%)', nilai: (r) => (r.change_pct == null ? '' : Number(r.change_pct)) },
            { label: 'Oleh', nilai: (r) => r.actor_name || '' },
            { label: 'Catatan', nilai: (r) => r.notes || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { loadMats(); loadData(); }} disabled={memuat}
          title="Muat ulang" aria-label="Muat ulang" data-testid="cost-history-refresh">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={selectedId ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="cost-detail-summary">
          <StatTile label="Harga sekarang" value={rp(s.current_unit_cost)} testId="cost-sum-current"
            sub={`berubah ${num(s.changes)} kali · per ${data?.material?.unit || selected?.unit || 'satuan'}`} />
          <StatTile label="Harga pertama" value={rp(s.first_unit_cost)} testId="cost-sum-first" sub="harga tercatat paling awal" />
          <StatTile label="Terendah" value={rp(s.min_unit_cost)} testId="cost-sum-min" sub="dalam periode terpilih" />
          <StatTile label="Tertinggi" value={rp(s.max_unit_cost)} testId="cost-sum-max" sub="dalam periode terpilih" />
        </div>
      ) : matSummary ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="cost-history-summary">
          <StatTile label="Barang aktif" value={num(matSummary.materials)} testId="cost-stat-materials"
            sub={filterType ? 'sesuai jenis terpilih' : 'semua jenis'} />
          <StatTile label="Pernah berubah harga" value={num(matSummary.with_history)} testId="cost-stat-with_history"
            sub="punya minimal satu riwayat harga" />
          <StatTile label="Total perubahan tercatat" value={num(matSummary.total_changes)} testId="cost-stat-total_changes"
            sub="semua waktu" />
          <StatTile label="Belum ada harga" value={num(matSummary.unvalued)} testId="cost-stat-unvalued"
            accent={matSummary.unvalued ? 'warning' : 'default'} sub="HPP masih 0 — belum ada pembelian bernilai" />
        </div>
      ) : null}>

      {selectedId && s.changes > 0 && (
        <GlassCard className="space-y-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-foreground">
                {selected ? `${selected.code} · ${selected.name}` : 'Perubahan harga'}
              </p>
              <p className="text-xs text-muted-foreground">
                Harga per {data?.material?.unit || selected?.unit || 'satuan'} · metode{' '}
                {METODE_LABEL[data?.material?.cost_method || 'moving_average'] || 'rata-rata bergerak'}
              </p>
            </div>
            <div className={`inline-flex items-center gap-1 text-sm font-semibold ${trendTone}`} data-testid="cost-trend">
              <TrendIcon className="h-4 w-4" />
              {trend == null ? 'perubahan dari 0' : `${trend > 0 ? '+' : ''}${String(trend).replace('.', ',')}% sejak harga pertama`}
            </div>
          </div>
          <div style={{ width: '100%', height: 220 }} data-testid="cost-chart">
            <ResponsiveContainer>
              <LineChart data={chart} margin={{ top: 5, right: 12, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="t" tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }} />
                <YAxis tick={{ fontSize: 12, fill: 'hsl(var(--muted-foreground))' }}
                  tickFormatter={v => Number(v).toLocaleString('id-ID')} width={78} />
                <RTooltip formatter={v => rp(v)}
                  contentStyle={{
                    background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))',
                    borderRadius: 8, fontSize: 12, color: 'hsl(var(--foreground))',
                  }} />
                <Line type="monotone" dataKey="harga" stroke="hsl(var(--primary))" strokeWidth={2}
                  dot={{ r: 3 }} name="Harga" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>
      )}

      {loadingData && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat riwayat harga…</p>
      ) : (
        <TabelData kolom={kolom} baris={items} testId="cost-history-table"
          kosong={
            <div data-testid="cost-empty">
              <EmptyState title="Belum ada perubahan harga"
                description={
                  <span data-testid="cost-empty-reason">
                    {data?.reason || 'Riwayat terisi sendiri setiap kali barang diterima dari pembelian.'}
                    {!selectedId && onlyChanged && !mats.length && ' Coba lepas centang "Hanya yang pernah berubah harga" untuk memilih barang.'}
                  </span>
                } />
            </div>
          } />
      )}

      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Harga barang tidak pernah diketik di modul mana pun — ia lahir dari penerimaan pembelian (rata-rata bergerak).
          Baris bersumber <em>Hasil cutting</em> adalah nilai potongan yang lahir saat kain dipotong, dan <em>Koreksi manual</em>
          hanya bisa dilakukan di layar Valuasi.
        </span>
      </p>
      {selected && (
        <p className="text-xs text-muted-foreground">
          {selected.code} · {jenisLabel(selected.type)} · {selected.unit_cost > 0 ? `${rp(selected.unit_cost)}/${selected.unit}` : 'belum ada harga'}
        </p>
      )}
    </PageLayout>
  );
}
