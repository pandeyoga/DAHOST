/**
 * Pembuat konten (tab di AI Marketing, Portal Toko) — caption & hashtag AI untuk Instagram, TikTok, Shopee, Tokopedia.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (judul disembunyikan di hub); form isian dibuka sebagai FormPopup (dulu form
 * di halaman berdampingan dengan hasil); hasil terakhir tampil di halaman dengan tombol salin; riwayat = tabel + unduh
 * (dulu kartu per riwayat); pilihan = SmartNativeSelect; tombol standar (dulu gradasi warna, kontras rendah).
 * F14b tetap: produk WAJIB dari Master Produk; kategori/material/warna mengikuti master.
 * Panggilan AI hanya terjadi saat tombol "Buat caption" di form ditekan.
 * Perbaikan ikut: riwayat dulu tidak dimuat ulang saat penyaring jenis diganti (memakai nilai lama).
 */
import { useState, useCallback, useEffect } from 'react';
import { Sparkles, Copy, RefreshCw, CheckCircle2 } from 'lucide-react';
import apiFetch from '@/lib/apiFetch';
import { Button } from '@/components/ui/button';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { GlassCard } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { useToast } from '@/hooks/use-toast';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
// F14b — produk untuk caption WAJIB dari Master Produk: caption yang tayang ke pembeli memuat bahan & harga.
import MasterProductSelect from '../pickers/MasterProductSelect';

const PLATFORM_CONFIG = {
  instagram: { label: 'Instagram', limit: 150 },
  tiktok: { label: 'TikTok', limit: 100 },
  shopee: { label: 'Shopee', limit: 200 },
  tokopedia: { label: 'Tokopedia', limit: 180 },
};

function CopyButton({ text, label = 'Salin' }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <Button size="sm" variant="outline" onClick={handleCopy}>
      {copied ? <CheckCircle2 className="text-[hsl(var(--success-text))]" /> : <Copy />}{copied ? 'Tersalin' : label}
    </Button>
  );
}

/** Form pembuatan caption (popup). F14b — identitas produk dari master, bukan ketikan. */
function FormCaption({ open, onClose, onHasil }) {
  const { toast } = useToast();
  const [form, setForm] = useState({ model_id: '', master: null, colors: '', price: '', platform: 'instagram', custom_notes: '' });
  const [loading, setLoading] = useState(false);
  const [galat, setGalat] = useState('');
  const handleChange = useCallback((field, value) => setForm(prev => ({ ...prev, [field]: value })), []);

  const handleGenerate = async () => {
    setGalat('');
    if (!form.model_id || !form.master) {
      setGalat('Pilih produk dari Master Produk — caption ditulis untuk produk yang benar-benar dijual.');
      return;
    }
    setLoading(true);
    try {
      const m = form.master;
      const payload = {
        // Identitas produk DIAMBIL DARI MASTER, bukan dari ketikan.
        product_name: m.name,
        model_id: m.model_id,
        platform: form.platform,
        ...(m.category_name && { category: m.category_name }),
        ...(m.material && { material: m.material }),
        ...(form.colors && { colors: form.colors.split(',').map(c => c.trim()).filter(Boolean) }),
        ...(form.price && { price: parseFloat(form.price) }),
        ...(form.custom_notes && { custom_notes: form.custom_notes }),
      };
      const data = await apiFetch('/marketing/ai-content/generate-caption', { method: 'POST', body: payload });
      onHasil({ ...data.data, platform: form.platform, product_name: m.name });
      toast({ title: 'Caption selesai dibuat.' });
      onClose();
    } catch (err) {
      setGalat(err.message || 'Gagal membuat caption');
    } finally {
      setLoading(false);
    }
  };

  const warna = [...new Set((form.master?.variants || []).map(v => v.color).filter(Boolean))];
  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" judul="Buat caption dengan AI"
      keterangan="Isi informasi produk supaya caption relevan." onSimpan={handleGenerate} menyimpan={loading}
      labelSimpan="Buat caption" galat={galat} testId="caption-form">
      <Isian label="Platform" wajib htmlFor="cap-platform">
        <SmartNativeSelect id="cap-platform" value={form.platform} searchable={false} onChange={(e) => handleChange('platform', e.target.value)}>
          {Object.entries(PLATFORM_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      {/* F14b — satu pemilih menggantikan tiga kotak ketik (nama, kategori, material). */}
      <MasterProductSelect
        value={form.model_id}
        testId="caption-product-select"
        label="Produk (dari Master Produk)"
        onChange={(m) => setForm(prev => ({
          ...prev,
          model_id: m?.model_id || '',
          master: m || null,
          // Harga berangkat dari harga RESMI master; boleh ditimpa untuk caption promo.
          price: prev.price !== '' && prev.price != null ? prev.price : (m?.retail_price_master ?? ''),
        }))}
        helpText="Caption yang tayang ke pembeli memuat bahan & harga — keduanya harus berasal dari master, bukan ketikan."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kategori (dari master)">
          <p className="flex h-9 items-center text-sm" data-testid="caption-category-readonly">
            {form.master ? (form.master.category_name || <span className="text-muted-foreground">Belum dicatat di master</span>)
              : <span className="text-muted-foreground">Pilih produk dulu</span>}
          </p>
        </Isian>
        <Isian label="Bahan (dari master)">
          <p className="flex h-9 items-center text-sm" data-testid="caption-material-readonly">
            {form.master ? (form.master.material || <span className="text-muted-foreground">Belum dicatat di master</span>)
              : <span className="text-muted-foreground">Pilih produk dulu</span>}
          </p>
        </Isian>
        <Isian label="Warna (dari varian master)" htmlFor="cap-color">
          <SmartNativeSelect id="cap-color" value={form.colors || ''} disabled={!form.master} data-testid="caption-color-select"
            onChange={(e) => handleChange('colors', e.target.value)}>
            <option value="">{form.master ? 'Semua warna' : 'Pilih produk dulu'}</option>
            {warna.map(c => <option key={c} value={c}>{c}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Harga (Rp)"
          galat={form.master && Number(form.master.retail_price_master || 0) > 0 && Number(form.price || 0) > 0
            && Number(form.price) !== Number(form.master.retail_price_master)
            ? `Beda dari harga resmi master (Rp ${Number(form.master.retail_price_master).toLocaleString('id-ID')}).` : undefined}>
          <MoneyInput placeholder="85.000" value={form.price} onChange={e => handleChange('price', e.target.value)} data-testid="caption-price-input" />
        </Isian>
      </div>
      <Isian label="Catatan tambahan" petunjuk="Opsional." htmlFor="cap-notes">
        <Textarea id="cap-notes" rows={2} placeholder="Promo flash sale, keunggulan khusus, sasaran pembeli…"
          value={form.custom_notes} onChange={e => handleChange('custom_notes', e.target.value)} />
      </Isian>
    </FormPopup>
  );
}

export default function AIContentGeneratorModule() {
  const [formBuka, setFormBuka] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState('all');

  const loadHistory = useCallback(async () => {
    setLoading(true);
    try {
      const type = filter === 'all' ? '' : filter;
      const data = await apiFetch(`/marketing/ai-content/history?limit=30${type ? `&content_type=${type}` : ''}`);
      setHistory(data.data || []);
    } catch (err) {
      setHistory([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const cfg = PLATFORM_CONFIG[result?.platform] || PLATFORM_CONFIG.instagram;
  const baris = history || [];
  const tgl = (v) => (v ? formatDateID(v) : '—');
  const kolom = [
    { kunci: 'produk', label: 'Produk', hp: 'judul', isi: (it) => <span className="font-medium">{it.product_name || it.prompt || '—'}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (it) => <StatusBadge status={it.type} label={it.type === 'caption' ? 'Caption' : 'Gambar'} tone="muted" /> },
    { kunci: 'platform', label: 'Platform', isi: (it) => (PLATFORM_CONFIG[it.platform]?.label || it.platform || '—') },
    { kunci: 'isi', label: 'Isi', hp: 'keterangan', isi: (it) => <p className="line-clamp-2 text-sm text-muted-foreground md:max-w-[26rem]">{it.caption || '—'}</p> },
    { kunci: 'tgl', label: 'Dibuat', isi: (it) => <span className="tabular-nums md:whitespace-nowrap">{tgl(it.generated_at)}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (it) => (it.caption ? <CopyButton text={`${it.caption}${it.hashtags ? `\n\n${it.hashtags}` : ''}`} /> : null) },
  ];

  return (
    <PageLayout testId="ai-content-generator" title="Pembuat konten"
      subtitle="Caption & hashtag dari AI untuk Instagram, TikTok, Shopee, dan Tokopedia."
      actions={<Button onClick={() => setFormBuka(true)} data-testid="btn-generate-caption"><Sparkles />Buat caption</Button>}
      filters={
        <SmartNativeSelect value={filter} onChange={(e) => setFilter(e.target.value)} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false} data-testid="caption-history-filter">
          <option value="all">Semua jenis</option>
          <option value="caption">Caption</option>
          <option value="image">Gambar</option>
        </SmartNativeSelect>
      }
      tools={<>
        <TombolUnduh namaBerkas="riwayat-konten-ai" namaLembar="Riwayat" baris={baris} testId="caption-history-unduh"
          kolom={[
            { label: 'Produk', nilai: (it) => it.product_name || it.prompt || '' },
            { label: 'Jenis', nilai: (it) => (it.type === 'caption' ? 'Caption' : 'Gambar') },
            { label: 'Platform', nilai: (it) => PLATFORM_CONFIG[it.platform]?.label || it.platform || '' },
            { label: 'Caption', nilai: (it) => it.caption || '' },
            { label: 'Hashtag', nilai: (it) => it.hashtags || '' },
            { label: 'Dibuat', nilai: (it) => tgl(it.generated_at) },
          ]} />
        <Button size="icon" variant="outline" onClick={loadHistory} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {result && (
        <GlassCard className="space-y-3 p-4" data-testid="caption-result">
          <div className="flex flex-wrap items-center gap-2">
            <p className="flex-1 text-base font-semibold">Hasil terakhir · {result.product_name} · {cfg.label}</p>
            <CopyButton text={`${result.caption}\n\n${result.hashtags}`} label="Salin semua" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <p className="flex-1 text-sm font-medium text-muted-foreground">Caption</p>
              <CopyButton text={result.caption} />
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{result.caption}</p>
            <p className="text-xs text-muted-foreground">{result.caption?.length || 0} karakter (maks. {cfg.limit})</p>
          </div>
          <div className="space-y-1 border-t border-[var(--glass-border)] pt-3">
            <div className="flex items-center gap-2">
              <p className="flex-1 text-sm font-medium text-muted-foreground">Hashtag</p>
              <CopyButton text={result.hashtags} />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {result.hashtags?.split(' ').filter(h => h.startsWith('#')).map((h, i) => <StatusBadge key={i} status="tag" label={h} tone="muted" />)}
            </div>
          </div>
        </GlassCard>
      )}

      {loading && !history ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat riwayat…</p>
      ) : (
        <TabelData kolom={kolom} baris={baris} kunci={(it) => `${it.generated_at}-${it.product_name || it.prompt}`} testId="caption-history-table"
          kosong={<EmptyState icon={Sparkles} title="Belum ada riwayat" description='Klik "Buat caption" untuk membuat caption pertama.' />} />
      )}

      <FormCaption open={formBuka} onClose={() => setFormBuka(false)} onHasil={(r) => { setResult(r); loadHistory(); }} />
    </PageLayout>
  );
}
