/**
 * Penyesuaian stok (tab di hub Stok & Akurasi) — catat barang rusak, hilang, ditemukan, atau koreksi hitung.
 * Jalur adjust RESMI: POST /api/rahaza/material-adjust (+ posting GL di server).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, form = FormPopup pendek (dulu kotak melayang buatan sendiri),
 * riwayat = TabelData + unduh Excel/CSV, label Indonesia.
 *
 * Verifikasi angka (8 Nov 2026): GET /api/rahaza/material-movements TIDAK mengenal parameter `type`
 * (lihat routes/rahaza_inventory_stock.list_movements) — `?type=adjust` diabaikan, sehingga "Riwayat adjustment"
 * dan kedua kartunya ikut menghitung penerimaan, pindah lokasi, dan pengeluaran. Kini layar mengambil 500 mutasi
 * terakhir (batas server) lalu menyaring `type === 'adjust'` di layar; kartu menyebut sumbernya.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { RefreshCw, Plus, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { useToast } from '@/hooks/use-toast';
import { formatDateTimeID } from '@/lib/format';
import { todayWIB, toWIBDate } from '@/lib/waktu';
import StorageLocationSelect from './StorageLocationSelect';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { materialOptionLabel } from '@/lib/materialFields';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatTile } from './moduleAtoms';

// 2026-11-07 (Tahap 5): tanda qty mengikuti tipe — dulu tipe hanya hiasan (tidak dikirim, tidak diperiksa),
// sehingga "Scrap" dengan qty +50 menambah stok.
const ADJ_TYPES = [
  { value: 'scrap', label: 'Rusak / afkir (mengurangi stok)', sign: -1 },
  { value: 'theft', label: 'Hilang (mengurangi stok)', sign: -1 },
  { value: 'found', label: 'Ditemukan / tambahan (menambah stok)', sign: 1 },
  { value: 'correction', label: 'Koreksi hitung stok (tambah atau kurang)', sign: 0 },
];
const BATAS_MUTASI = 500; // batas `limit` GET /rahaza/material-movements (mode tanpa halaman)
const fmtQty = (v) => Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 3 });

export default function InventoryScrapModule({ token }) {
  const [movements, setMovements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [adjustForm, setAdjustForm] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [stockInfo, setStockInfo] = useState(null);
  const [galat, setGalat] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  const { toast } = useToast();
  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token]
  );
  const URL_MUTASI = `/api/rahaza/material-movements?type=adjust&limit=${BATAS_MUTASI}`;
  const hanyaPenyesuaian = (d) => (Array.isArray(d) ? d : []).filter((m) => !m.type || m.type === 'adjust');

  const fetchMovements = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(URL_MUTASI, { headers });
      if (r.ok) setMovements(hanyaPenyesuaian(await r.json()));
    } catch (e) {
      toast({ title: 'Gagal', description: 'Gagal memuat riwayat penyesuaian', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [headers, toast, URL_MUTASI]);

  useEffect(() => {
    (async () => {
      try {
        const [mvR, matR] = await Promise.all([
          fetch(URL_MUTASI, { headers }),
          fetch('/api/rahaza/materials', { headers }),
        ]);
        if (mvR.ok) setMovements(hanyaPenyesuaian(await mvR.json()));
        if (matR.ok) {
          const d = await matR.json();
          setMaterials((Array.isArray(d) ? d : d?.items || []).filter((m) => m.active !== false));
        }
      } catch (e) {
        // Silent fail on initial load
      } finally {
        setLoading(false);
      }
    })();
  }, [headers, URL_MUTASI]);

  const checkStock = async (materialId, locationId) => {
    try {
      const r = await fetch(`/api/rahaza/material-stock?material_id=${materialId}&location_id=${locationId}`, { headers });
      if (r.ok) {
        const stocks = await r.json();
        setStockInfo(stocks[0] || null);
      }
    } catch (e) {
      // Silent fail
    }
  };

  const tutupForm = () => { setAdjustForm(null); setStockInfo(null); setGalat(''); };

  const adjust = async () => {
    if (!adjustForm) return;
    setGalat('');
    if (!adjustForm.material_id || !adjustForm.location_id || !adjustForm.qty || !adjustForm.reason) {
      setGalat('Semua isian wajib diisi.');
      return;
    }
    if (adjustForm.reason.trim().length < 5) {
      setGalat('Alasan minimal 5 karakter untuk jejak audit.');
      return;
    }
    const delta = Number(adjustForm.qty);
    if (delta === 0) {
      setGalat('Qty penyesuaian tidak boleh 0.');
      return;
    }
    const typ = ADJ_TYPES.find((t) => t.value === adjustForm.adjustment_type);
    if (typ && typ.sign < 0 && delta > 0) {
      setGalat(`${typ.label}: isi qty negatif, mis. -${delta}.`);
      return;
    }
    if (typ && typ.sign > 0 && delta < 0) {
      setGalat(`${typ.label}: isi qty positif, mis. ${Math.abs(delta)}.`);
      return;
    }
    // Check stock availability for negative adjustment
    if (delta < 0 && stockInfo && Math.abs(delta) > stockInfo.qty) {
      setGalat(`Stok tidak cukup. Tersedia: ${stockInfo.qty}`);
      return;
    }
    setMenyimpan(true);
    try {
      const r = await fetch('/api/rahaza/material-adjust', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          material_id: adjustForm.material_id,
          location_id: adjustForm.location_id,
          qty: delta,
          reason: adjustForm.reason
        })
      });
      if (r.ok) {
        toast({ title: 'Tersimpan', description: 'Penyesuaian stok dicatat' });
        tutupForm();
        fetchMovements();
      } else {
        const err = await r.json().catch(() => ({}));
        setGalat(typeof err.detail === 'string' ? err.detail : `Gagal menyimpan penyesuaian (HTTP ${r.status})`);
      }
    } catch (e) {
      setGalat('Gagal menyimpan penyesuaian.');
    } finally {
      setMenyimpan(false);
    }
  };

  // Bulan ini menurut WIB (dulu memakai jam peramban).
  const bulanIni = todayWIB().slice(0, 7);
  const bulanan = movements.filter((m) => m.created_at && String(toWIBDate(m.created_at) || '').slice(0, 7) === bulanIni);
  const totalBulanIni = bulanan.length;
  const totalScrapThisMonth = bulanan.filter((m) => Number(m.qty) < 0).length;
  const { page, setPage, totalPages, total, paged } = useClientPagination(movements, 25);

  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'keterangan', isi: (m) => (
      <span className="text-sm md:whitespace-nowrap" data-testid={`adj-row-${m.id}`}>{formatDateTimeID(m.created_at)}</span>) },
    { kunci: 'material', label: 'Material', hp: 'judul', isi: (m) => (
      <div className="min-w-0 md:max-w-[20rem]">
        <p className="font-medium">{m.material_name}</p>
        <p className="text-xs text-muted-foreground">{m.material_code}</p>
      </div>) },
    { kunci: 'lokasi', label: 'Lokasi', isi: (m) => <span className="text-sm">{m.location_name || m.from_location_name || m.to_location_name || '—'}</span> },
    { kunci: 'qty', label: 'Perubahan', rata: 'kanan', isi: (m) => (
      <span className={`tabular-nums ${Number(m.qty) < 0 ? 'text-[hsl(var(--danger-text))]' : 'text-[hsl(var(--success-text))]'}`}>
        {Number(m.qty) > 0 ? '+' : ''}{fmtQty(m.qty)} {m.unit || ''}
      </span>) },
    { kunci: 'alasan', label: 'Alasan', isi: (m) => (
      <span className="block max-w-xs truncate text-sm text-muted-foreground" title={m.notes || ''}>{m.notes || '—'}</span>) },
    { kunci: 'oleh', label: 'Oleh', isi: (m) => <span className="text-sm">{m.created_by_name || '—'}</span> },
  ];

  return (
    <PageLayout testId="inventory-scrap-page" title="Penyesuaian stok"
      subtitle="Catat barang rusak, hilang, ditemukan, atau koreksi hitung. Jurnal dibuat otomatis."
      actions={
        <Button onClick={() => { setGalat(''); setAdjustForm({ material_id: '', location_id: '', qty: 0, reason: '', adjustment_type: 'scrap' }); }}
          data-testid="adj-add">
          <Plus />Buat penyesuaian
        </Button>
      }
      tools={<>
        <TombolUnduh namaBerkas="riwayat-penyesuaian-stok" namaLembar="Penyesuaian" baris={movements} testId="adj-unduh"
          kolom={[
            { label: 'Tanggal', nilai: (m) => formatDateTimeID(m.created_at) },
            { label: 'Kode material', nilai: (m) => m.material_code },
            { label: 'Material', nilai: (m) => m.material_name },
            { label: 'Lokasi', nilai: (m) => m.location_name || m.from_location_name || m.to_location_name || '' },
            { label: 'Perubahan', nilai: (m) => Number(m.qty || 0) },
            { label: 'Satuan', nilai: (m) => m.unit || '' },
            { label: 'Alasan', nilai: (m) => m.notes || '' },
            { label: 'Oleh', nilai: (m) => m.created_by_name || '' },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchMovements} disabled={loading}
          data-testid="adj-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={movements.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Penyesuaian bulan ini" value={totalBulanIni.toLocaleString('id-ID')}
            sub={`Dari ${BATAS_MUTASI} mutasi stok terakhir.`} />
          <StatTile label="Pengurangan bulan ini" value={totalScrapThisMonth.toLocaleString('id-ID')}
            accent={totalScrapThisMonth > 0 ? 'danger' : 'default'} sub="Penyesuaian yang mengurangi stok (rusak, hilang)." />
        </div>
      ) : null}
      footer={movements.length > 25 ? (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={25} onPageChange={setPage} />
      ) : null}>
      {loading && movements.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} kunci={(m) => m.id} testId="adj-table"
          kosong={<EmptyState title="Belum ada riwayat penyesuaian"
            description="Penyesuaian stok yang dicatat dari sini atau dari baris stok tampil di daftar ini." />} />
      )}

      <FormPopup open={!!adjustForm} onClose={tutupForm} ukuran="pendek" judul="Buat penyesuaian stok"
        keterangan="Stok berubah di lokasi terpilih dan jurnalnya dibuat otomatis." onSimpan={adjust}
        menyimpan={menyimpan} galat={galat} labelSimpan="Simpan penyesuaian" testId="adj-form">
        {adjustForm && <>
          {/* 2026-11-07 (Tahap 5): material DIPILIH dari master (dulu staf harus mengetik UUID material). */}
          <Isian label="Material" wajib htmlFor="adj-material">
            <SmartNativeSelect
              id="adj-material"
              value={adjustForm.material_id}
              onChange={e => {
                setAdjustForm(f => ({ ...f, material_id: e.target.value }));
                setStockInfo(null);
                if (e.target.value && adjustForm.location_id) checkStock(e.target.value, adjustForm.location_id);
              }}
              className="w-full"
              data-testid="adj-material-id"
            >
              <option value="">Pilih material</option>
              {materials.map((m) => <option key={m.id} value={m.id}>{materialOptionLabel(m)}</option>)}
            </SmartNativeSelect>
          </Isian>
          {/* 2026-11-02 — No.18(a): lokasi DIPILIH dari daftar gudang, bukan UUID diketik. */}
          <Isian label="Lokasi" wajib>
            <StorageLocationSelect
              token={token}
              value={adjustForm.location_id}
              onChange={(v) => {
                setAdjustForm(f => ({ ...f, location_id: v }));
                setStockInfo(null);
                if (adjustForm.material_id && v) checkStock(adjustForm.material_id, v);
              }}
              testId="adj-location-id"
            />
          </Isian>
          {stockInfo && (
            <Notice tone={stockInfo.below_min ? 'warning' : 'info'} icon={stockInfo.below_min ? AlertTriangle : undefined}
              title={`Stok saat ini: ${fmtQty(stockInfo.qty)} ${stockInfo.unit || ''}`}>
              {stockInfo.below_min ? 'Stok di bawah minimum.' : null}
            </Notice>
          )}
          <Isian label="Jenis penyesuaian" htmlFor="adj-type-sel">
            <SmartNativeSelect
              id="adj-type-sel"
              value={adjustForm.adjustment_type}
              onChange={e => setAdjustForm(f => ({ ...f, adjustment_type: e.target.value }))}
              className="w-full"
              searchable={false}
              data-testid="adj-type"
            >
              {ADJ_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Qty penyesuaian" wajib htmlFor="adj-qty-in" petunjuk="Negatif (−) untuk rusak/hilang, positif (+) untuk tambahan/koreksi.">
            <Input
              id="adj-qty-in"
              type="number"
              inputMode="decimal"
              value={adjustForm.qty}
              onChange={e => setAdjustForm(f => ({ ...f, qty: e.target.value }))}
              placeholder="Contoh: -50"
              data-testid="adj-qty"
            />
          </Isian>
          <Isian label="Alasan" wajib htmlFor="adj-reason-in" petunjuk="Minimal 5 karakter untuk jejak audit.">
            <Textarea
              id="adj-reason-in"
              value={adjustForm.reason}
              onChange={e => setAdjustForm(f => ({ ...f, reason: e.target.value }))}
              rows={3}
              placeholder="Contoh: rusak/cacat saat produksi, hilang saat hitung stok"
              data-testid="adj-reason"
            />
          </Isian>
        </>}
      </FormPopup>
    </PageLayout>
  );
}
