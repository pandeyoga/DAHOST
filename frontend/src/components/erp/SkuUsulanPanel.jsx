/**
 * Jembatan SKU › bagian "Usulan AI" (14 Nov 2026).
 *
 * Untuk baris pesanan yang belum tertaut varian atau baru tertaut MODEL, per kombinasi SKU + variasi (berlaku ke
 * semua pesanan yang sama) layar ini menampilkan usulan varian master + tingkat keyakinan + alasannya:
 *   · Usulan pasti — kode model dari SKU penjual + warna/ukuran variasi bersinonim (POLKA BLACK = Polkadot Hitam, …);
 *   · Perlu AI     — model diketahui tetapi variannya belum pasti; tombol "Minta usulan AI" memanggil Asisten AI
 *                    (saklar & batas per pengguna berlaku). AI hanya mengusulkan;
 *   · Tidak bisa dipetakan — SKU kosong, "Reject Sale", "Default", SKU bukan kode model — dengan saran tindakan.
 * Penautan selalu lewat persetujuan staf (satu klik) di jalur resmi Jembatan SKU. Backend: core/sku_usulan.py.
 */
import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Link2, Loader2, Search, Sparkles, Wand2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { apiGet, apiPost } from '@/lib/api';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const fmt = (v) => Number(v || 0).toLocaleString('id-ID');
const persen = (k) => `${Math.round((Number(k) || 0) * 100)}%`;
const pct = (a, b) => (b ? `${String(Math.round((1000 * a) / b) / 10).replace('.', ',')}%` : '—');

const JENIS = {
  pasti: { label: 'Usulan pasti', tone: 'success' },
  ai: { label: 'Perlu AI', tone: 'primary' },
  tidak: { label: 'Tidak bisa dipetakan', tone: 'warning' },
};
const SUMBER_MODEL = { sku_penjual: 'dari SKU penjual', tautan_model: 'dari tautan model pesanan' };

function KeyakinanBadge({ k }) {
  const n = Number(k) || 0;
  return <StatusBadge tone={n >= 0.9 ? 'success' : n >= 0.7 ? 'info' : 'warning'} label={`${persen(n)} yakin`} />;
}

export default function SkuUsulanPanel({ reloadKey, onChanged, onPilihManual }) {
  const [data, setData] = useState(null);
  const [jenis, setJenis] = useState('');
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');          // kunci baris yang sedang disetujui / ditanya
  const [busyAi, setBusyAi] = useState(false);
  const [busyMassal, setBusyMassal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ limit: '300' });
      if (jenis) p.set('jenis', jenis);
      if (q) p.set('q', q);
      setData(await apiGet(`/sku-bridge/usulan?${p.toString()}`));
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [jenis, q]);

  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [load, reloadKey]);

  const rows = data?.rows || [];
  const ringkas = data?.ringkas || {};
  const angka = data?.angka || {};
  const ai = data?.ai || { boleh: false, alasan: '' };
  const totalKombinasi = (ringkas.pasti || 0) + (ringkas.ai || 0) + (ringkas.tidak || 0);

  const setujui = async (r) => {
    const u = r.usulan || {};
    setBusy(r.kunci);
    try {
      const res = await apiPost('/sku-bridge/usulan/setujui', {
        kunci: r.kunci, variant_id: u.variant_id, sumber: u.sumber || r.jenis, keyakinan: u.keyakinan,
        product_name: r.product_name, variation: r.variation, account_id: r.account_id,
      });
      toast.success(res.message || 'Kombinasi ditautkan');
      load(); onChanged?.();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const mintaAi = async (kunci) => {
    if (kunci) setBusy(kunci); else setBusyAi(true);
    try {
      const res = await apiPost('/sku-bridge/usulan/ai', kunci ? { kunci: [kunci] } : {});
      toast.success(res.message || 'Usulan AI siap diperiksa');
      load();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); setBusyAi(false); }
  };

  const setujuiSemuaPasti = async () => {
    const n = ringkas.pasti || 0;
    const ok = await confirmDialog({
      title: `Setujui ${fmt(n)} usulan pasti?`,
      body: 'Setiap kombinasi SKU + variasi ditautkan ke varian usulannya, dan semua pesanannya ikut tertaut. '
        + 'Periksa daftar "Usulan pasti" dulu bila ragu — tautan bisa diganti atau dilepas di bagian Sudah dipetakan.',
      confirmLabel: 'Setujui semua',
    });
    if (!ok) return;
    setBusyMassal(true);
    try {
      const res = await apiPost('/sku-bridge/usulan/setujui-pasti', {});
      toast.success(res.message);
      load(); onChanged?.();
    } catch (e) { toast.error(e.message); } finally { setBusyMassal(false); }
  };

  const kolom = [
    { kunci: 'barang', label: 'Barang dipesan pembeli', hp: 'judul', isi: (r) => (
      <div className="min-w-0 md:max-w-[15rem]">
        <p className="truncate font-medium" title={r.product_name}>{r.product_name || '(tanpa nama)'}</p>
        <p className="truncate text-xs text-muted-foreground">
          {r.account_name || '—'} · SKU penjual {r.seller_sku || '(kosong)'}
        </p>
      </div>) },
    { kunci: 'variasi', label: 'Variasi', hp: 'keterangan', isi: (r) => (
      <div className="md:max-w-[11rem]">
        <p className="text-sm">{r.variation || '—'}</p>
        {r.model_code && (
          <p className="text-xs text-muted-foreground">Model {r.model_code} {SUMBER_MODEL[r.sumber_model] || ''}</p>
        )}
      </div>) },
    { kunci: 'pcs', label: 'Pcs', rata: 'kanan', isi: (r) => (
      <span className="tabular-nums"><span className="font-medium">{fmt(r.pcs)}</span>
        <span className="block text-xs text-muted-foreground">{fmt(r.orders)} baris</span></span>) },
    { kunci: 'usulan', label: 'Usulan varian', isi: (r) => {
      const u = r.usulan;
      if (u && u.variant_id) {
        return (
          <div className="md:max-w-[19rem]" data-testid={`usulan-${r.kunci}`}>
            <p className="font-medium">{u.label}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1">
              <KeyakinanBadge k={u.keyakinan} />
              <StatusBadge tone="default" label={u.sumber === 'ai' ? 'Usulan AI' : 'Pasti'} />
            </div>
            {(u.alasan || []).length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">{u.alasan.join(' · ')}</p>
            )}
          </div>
        );
      }
      if (u && u.kosong) {
        return <p className="text-xs text-muted-foreground md:max-w-[19rem]">AI tidak menemukan varian: {(u.alasan || []).join(' ') || '—'}</p>;
      }
      return (
        <div className="md:max-w-[19rem]">
          <StatusBadge tone={JENIS[r.jenis]?.tone} label={JENIS[r.jenis]?.label || r.jenis} />
          <p className="mt-1 text-xs text-muted-foreground">{r.saran || '—'}</p>
        </div>
      );
    } },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex items-center justify-end gap-1.5 whitespace-nowrap">
        {r.usulan?.variant_id && (
          <Button size="sm" variant="success" onClick={() => setujui(r)} disabled={busy === r.kunci} data-testid={`setujui-${r.kunci}`}>
            {busy === r.kunci ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}Setujui
          </Button>
        )}
        {r.jenis === 'ai' && ai.boleh && (
          <Button size="sm" variant="outline" onClick={() => mintaAi(r.kunci)} disabled={busy === r.kunci}
            title="Minta Asisten AI mengusulkan varian untuk kombinasi ini" data-testid={`tanya-ai-${r.kunci}`}>
            <Sparkles />{r.usulan ? 'Tanya ulang' : 'Tanya AI'}
          </Button>
        )}
        <Button size="icon-sm" variant="outline" onClick={() => onPilihManual?.({ ...r, platform_sku_id: r.kunci })}
          title="Pilih varian manual" aria-label="Pilih varian manual" data-testid={`usulan-manual-${r.kunci}`}>
          <Link2 />
        </Button>
      </div>) },
  ];

  const opsi = [
    { key: '', label: 'Semua', count: totalKombinasi || undefined },
    { key: 'pasti', label: 'Usulan pasti', count: ringkas.pasti || undefined },
    { key: 'ai', label: 'Perlu AI', count: ringkas.ai || undefined },
    { key: 'tidak', label: 'Tidak bisa dipetakan', count: ringkas.tidak || undefined },
  ];

  return (
    <div className="space-y-3" data-testid="usulan-panel">
      {data && (
        <p className="text-sm text-muted-foreground" data-testid="usulan-ringkas">
          Baris pesanan: <b className="tabular-nums text-foreground">{fmt(angka.varian)}</b> tertaut varian
          ({pct(angka.varian, angka.baris)}), <b className="tabular-nums text-foreground">{fmt(angka.model)}</b> baru tertaut
          model ({pct(angka.model, angka.baris)}), <b className="tabular-nums text-foreground">{fmt(angka.belum)}</b> belum
          tertaut ({pct(angka.belum, angka.baris)}). {fmt(totalKombinasi)} kombinasi SKU + variasi perlu varian:
          {' '}{fmt(ringkas.pasti)} usulan pasti, {fmt(ringkas.ai)} perlu AI ({fmt(ringkas.ai_terjawab)} sudah dijawab),
          {' '}{fmt(ringkas.tidak)} tidak bisa dipetakan. Menyetujui satu kombinasi menautkan semua pesanannya.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChips options={opsi} value={jenis} onChange={setJenis} hideWhenEmpty={false} testId="usulan-jenis" />
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" placeholder="Cari produk, variasi, SKU, model"
            data-testid="usulan-cari" />
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">
          <Button variant="outline" onClick={() => mintaAi()} disabled={busyAi || !ai.boleh || !(ringkas.ai > ringkas.ai_terjawab)}
            title={ai.boleh ? 'Minta Asisten AI mengusulkan varian (paling banyak 20 kombinasi sekali minta)' : ai.alasan}
            data-testid="usulan-minta-ai">
            {busyAi ? <Loader2 className="animate-spin" /> : <Sparkles />}Minta usulan AI
          </Button>
          {(ringkas.pasti || 0) > 0 && (
            <Button variant="success" onClick={setujuiSemuaPasti} disabled={busyMassal} data-testid="usulan-setujui-semua">
              {busyMassal ? <Loader2 className="animate-spin" /> : <Wand2 />}Setujui semua usulan pasti
            </Button>
          )}
          <TombolUnduh namaBerkas="usulan-varian-sku" namaLembar="Usulan" baris={rows} testId="usulan-unduh"
            kolom={[
              { label: 'Toko', nilai: (r) => r.account_name || '' },
              { label: 'Nama produk', nilai: (r) => r.product_name || '' },
              { label: 'Variasi', nilai: (r) => r.variation || '' },
              { label: 'SKU penjual', nilai: (r) => r.seller_sku || '' },
              { label: 'SKU platform', nilai: (r) => r.sku_label || r.kunci },
              { label: 'Model', nilai: (r) => r.model_code || '' },
              { label: 'Pcs', nilai: (r) => Number(r.pcs || 0) },
              { label: 'Baris pesanan', nilai: (r) => Number(r.orders || 0) },
              { label: 'Kelompok', nilai: (r) => JENIS[r.jenis]?.label || r.jenis },
              { label: 'Usulan varian', nilai: (r) => r.usulan?.label || '' },
              { label: 'Keyakinan', nilai: (r) => (r.usulan?.variant_id ? persen(r.usulan.keyakinan) : '') },
              { label: 'Alasan / saran', nilai: (r) => ((r.usulan?.alasan || []).join(' · ') || r.saran || '') },
            ]} />
        </div>
      </div>
      {data && !ai.boleh && (ringkas.ai || 0) > 0 && (
        <Notice tone="info" icon={Sparkles} testId="usulan-ai-mati" title="Usulan AI belum bisa diminta">
          {ai.alasan || 'Asisten AI tidak aktif untuk akun ini.'} Usulan pasti dan Pilih manual tetap bisa dipakai.
        </Notice>
      )}
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Mencocokkan pesanan dengan varian master…</p>
      ) : (
        <TabelData kolom={kolom} baris={rows} kunci={(r) => r.kunci} testId="usulan-table"
          kosong={<EmptyState icon={CheckCircle2} testId="usulan-empty"
            title={jenis || q ? 'Tidak ada kombinasi yang cocok' : 'Semua baris pesanan sudah tertaut varian'}
            description={jenis || q ? 'Ubah pilihan kelompok atau kata pencarian.' : 'Tidak ada pesanan yang menunggu varian master.'} />} />
      )}
      {(data?.total || 0) > rows.length && (
        <p className="text-sm text-muted-foreground">Menampilkan {fmt(rows.length)} dari {fmt(data.total)} kombinasi (pcs terbanyak dulu).</p>
      )}
    </div>
  );
}
