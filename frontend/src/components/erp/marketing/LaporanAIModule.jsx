/**
 * Laporan AI (Portal Marketing) — laporan mingguan/bulanan dengan analisis Asisten AI.
 *
 * Angka di layar ini = PAKET FAKTA yang dihitung sistem dari pembaca resmi (`GET /api/marketing/laporan-ai/fakta`):
 * KPI vs periode sebelumnya, per toko, anomali, kualitas data. Tombol "Susun laporan AI" membuka percakapan
 * Asisten AI yang membaca paket fakta yang sama, menulis analisis + rekomendasi, lalu membuat PDF/Excel —
 * penjaga angka menolak laporan yang memuat angka di luar paket fakta.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import { Skeleton } from '@/components/ui/skeleton';
import { formatNumber, formatRupiah } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { kalimatAnomali, pilihanBulan, pilihanPekan } from './laporanAIAturan';

const API = process.env.REACT_APP_BACKEND_URL;

async function panggil(path, { method = 'GET', body } = {}) {
  const token = localStorage.getItem('erp_token');
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let pesan = 'Permintaan gagal. Coba lagi.';
    try { const d = await res.json(); if (typeof d.detail === 'string') pesan = d.detail; } catch { /* abaikan */ }
    throw new Error(pesan);
  }
  return res.json();
}

const persen = (v) => (v == null ? '—' : `${String(v).replace('.', ',')}%`);

export default function LaporanAIModule() {
  const [jenis, setJenis] = useState('mingguan');
  const pilihan = useMemo(() => (jenis === 'bulanan' ? pilihanBulan() : pilihanPekan()), [jenis]);
  const [idx, setIdx] = useState(0);
  const [toko, setToko] = useState('');
  const [daftarToko, setDaftarToko] = useState([]);
  const [fakta, setFakta] = useState(null);
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [menyusun, setMenyusun] = useState(false);
  const p = pilihan[Math.min(idx, pilihan.length - 1)];

  useEffect(() => {
    panggil('/api/marketing/impor-paket/pilihan').then((d) => setDaftarToko(d.toko || [])).catch(() => {});
  }, []);

  const muat = useCallback(async () => {
    setMemuat(true); setGalat('');
    try {
      const q = new URLSearchParams({ jenis, dari: p.dari, sampai: p.sampai, simpan: 'false' });
      if (toko) q.set('toko_id', toko);
      setFakta(await panggil(`/api/marketing/laporan-ai/fakta?${q}`));
    } catch (e) { setGalat(e.message); setFakta(null); } finally { setMemuat(false); }
  }, [jenis, p, toko]);
  useEffect(() => { muat(); }, [muat]);

  const susun = async () => {
    setMenyusun(true);
    try {
      const d = await panggil('/api/marketing/laporan-ai/susun', { method: 'POST',
        body: { jenis, dari: p.dari, sampai: p.sampai, toko_id: toko || null } });
      toast.success(d.pesan);
      window.dispatchEvent(new CustomEvent('erp:navigate-module', { detail: { moduleId: 'asisten-ai', params: { sesi: d.sesi_id } } }));
    } catch (e) { toast.error(e.message); } finally { setMenyusun(false); }
  };

  const k = fakta?.kpi || {};
  const lalu = fakta?.pembanding?.periode_sebelumnya;
  const kolomToko = [
    { kunci: 'toko', label: 'Toko', hp: 'judul' },
    { kunci: 'omzet', label: 'Omzet (Rp)', rata: 'kanan', isi: (r) => formatNumber(r.omzet) },
    { kunci: 'selisih', label: 'Vs sebelumnya', rata: 'kanan', isi: (r) => persen(r.selisih_persen) },
    { kunci: 'pesanan', label: 'Pesanan', rata: 'kanan', isi: (r) => formatNumber(r.pesanan) },
    { kunci: 'iklan', label: 'Iklan (Rp)', rata: 'kanan', isi: (r) => formatNumber(r.belanja_iklan) },
    { kunci: 'tacos', label: 'TACoS', rata: 'kanan', isi: (r) => persen(r.tacos_persen) },
    { kunci: 'hari', label: 'Hari berdata', rata: 'kanan', isi: (r) => (r.hari_ada_data == null ? '—' : `${r.hari_ada_data}/${fakta?.periode?.hari}`) },
  ];
  const kolomProduk = [
    { kunci: 'label', label: 'Produk', hp: 'judul' },
    { kunci: 'omzet', label: 'Omzet (Rp)', rata: 'kanan', isi: (r) => formatNumber(r.omzet) },
    { kunci: 'unit', label: 'Unit', rata: 'kanan', isi: (r) => formatNumber(r.unit) },
    { kunci: 'margin', label: 'Margin', rata: 'kanan', isi: (r) => persen(r.margin_persen) },
  ];
  const kolomKampanye = [
    { kunci: 'kampanye', label: 'Kampanye', hp: 'judul' },
    { kunci: 'belanja', label: 'Biaya (Rp)', rata: 'kanan', isi: (r) => formatNumber(r.belanja) },
    { kunci: 'omzet_atribusi', label: 'Omzet atribusi (Rp)', rata: 'kanan', isi: (r) => formatNumber(r.omzet_atribusi) },
    { kunci: 'roas', label: 'ROAS', rata: 'kanan', isi: (r) => (r.roas == null ? '—' : String(r.roas).replace('.', ',')) },
  ];

  return (
    <PageLayout testId="laporan-ai-module" title="Laporan AI"
      subtitle="Laporan mingguan atau bulanan: angka dihitung sistem, analisis & rekomendasi disusun Asisten AI."
      actions={<Button onClick={susun} disabled={menyusun || memuat || !fakta} data-testid="lap-ai-susun">
        <Sparkles />{menyusun ? 'Menyiapkan…' : 'Susun laporan AI'}</Button>}
      filters={<>
        <SmartNativeSelect value={jenis} onChange={(e) => { setJenis(e.target.value); setIdx(0); }} className="w-40"
          aria-label="Jenis laporan" data-testid="lap-ai-jenis">
          <option value="mingguan">Mingguan</option>
          <option value="bulanan">Bulanan</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={String(idx)} onChange={(e) => setIdx(Number(e.target.value))} className="w-56"
          aria-label="Periode" data-testid="lap-ai-periode">
          {pilihan.map((o, i) => <option key={o.dari} value={String(i)}>{o.label}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={toko} onChange={(e) => setToko(e.target.value)} className="w-56" aria-label="Toko"
          data-testid="lap-ai-toko">
          <option value="">Semua toko</option>
          {daftarToko.map((t) => <option key={t.id} value={t.id}>{t.nama}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<Button variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" onClick={muat}><RefreshCw /></Button>}
      summary={fakta && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Omzet" value={formatRupiah(k.omzet)} hint="Sesudah diskon penjual; batal & belum dibayar tidak dihitung."
            sub={lalu ? `${persen(lalu.selisih_omzet_persen)} vs ${formatRupiah(lalu.omzet)}` : undefined}
            subTone={lalu?.selisih_omzet_persen > 0 ? 'success' : lalu?.selisih_omzet_persen < 0 ? 'danger' : undefined} />
          <StatTile label="Pesanan" value={formatNumber(k.pesanan)} hint="Pesanan yang dihitung omzet."
            sub={`AOV ${formatRupiah(k.aov)} · batal ${persen(k.persen_batal)}`} />
          <StatTile label="Belanja iklan" value={k.belanja_iklan ? formatRupiah(k.belanja_iklan) : '—'}
            hint="Dari laporan iklan yang diimpor; TACoS = iklan ÷ omzet." sub={k.belanja_iklan ? `TACoS ${persen(k.tacos_persen)} · ROAS ${k.roas_iklan ?? '—'}` : 'Laporan iklan belum diimpor'} />
          <StatTile label="Biaya platform" value={k.biaya_platform ? formatRupiah(k.biaya_platform) : '—'}
            hint="Dari laporan dana dilepas (tanggal dana dilepas, bisa tertinggal)."
            sub={k.biaya_platform ? `${persen(k.biaya_platform_persen)} dari penjualan setoran` : 'Laporan penghasilan belum dicatat'} />
        </div>
      )}>
      {memuat && <Skeleton className="h-40 w-full" />}
      {galat && <Notice tone="danger" icon={AlertTriangle} title="Laporan tidak bisa dimuat">{galat}</Notice>}
      {fakta && !memuat && (<>
        {(fakta.anomali || []).length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} title={`${fakta.anomali.length} hal perlu diperhatikan`} testId="lap-ai-anomali">
            <ul className="list-disc pl-4">
              {fakta.anomali.slice(0, 8).map((a, i) => <li key={i}>{kalimatAnomali(a, formatRupiah)}</li>)}
            </ul>
          </Notice>
        )}
        {(fakta.kualitas_data?.catatan || []).length > 0 && (
          <Notice tone="info" title="Catatan data">{fakta.kualitas_data.catatan.slice(0, 3).join(' ')}</Notice>
        )}
        <p className="text-sm font-medium">Per toko</p>
        <TabelData kolom={kolomToko} baris={fakta.per_toko || []} kunci={(r) => r.toko} testId="lap-ai-toko-tabel"
          kosong={<EmptyState title="Belum ada omzet pada periode ini" description="Impor pesanan atau isi rekap harian toko dulu." />} />
        <p className="text-sm font-medium">Produk teratas</p>
        <TabelData kolom={kolomProduk} baris={fakta.produk_teratas || []} kunci={(r) => r.label} testId="lap-ai-produk-tabel"
          kosong={<EmptyState title="Belum ada rincian produk" description="Rincian produk berasal dari pesanan impor." />} />
        <p className="text-sm font-medium">Kampanye iklan</p>
        <TabelData kolom={kolomKampanye} baris={fakta.iklan_kampanye || []} kunci={(r) => r.kampanye} testId="lap-ai-iklan-tabel"
          kosong={<EmptyState title="Belum ada laporan iklan" description="Impor laporan iklan CPC Shopee atau GMV Max TikTok." />} />
      </>)}
    </PageLayout>
  );
}
