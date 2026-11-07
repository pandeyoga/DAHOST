/**
 * Konfigurasi Maklon (Administrasi Sistem) — setelan sistem yang bisa diatur (pajak, ambang, kunci integrasi).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, 22 setelan = satu tabel dengan penyaring kategori (dulu 6 tab berisi
 * form di halaman), ubah satu setelan = FormPopup pendek (jalur simpan sama: POST /config/bulk), unduh Excel/CSV
 * tanpa nilai rahasia, kode setelan (`maklon_cmt_buffer_days`) dan "system_init" tidak tampil di layar.
 * Hak ubah tetap: hanya admin/owner/superadmin (isCurrentUserConfigAdmin); peran lain mode baca.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Eye, EyeOff, Lock, Pencil, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Switch } from '@/components/ui/switch';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { toast } from 'sonner';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import { isCurrentUserConfigAdmin } from '@/lib/systemConfigRoles';

const CATEGORY_META = {
  inventory:    { label: 'Gudang & stok' },
  production:   { label: 'Produksi' },
  maklon:       { label: 'Maklon & tagihan' },
  hpp:          { label: 'HPP & biaya' },
  notification: { label: 'Notifikasi (WA/TG)' },
  marketplace:  { label: 'Marketplace' },
};
// Nama setelan dari server sebagian masih berbahasa Inggris — diterjemahkan untuk tampilan saja.
const LABEL_ID = {
  hpp_profit_margin_pct: 'Target margin laba (%)',
  maklon_cmt_buffer_days: 'Cadangan waktu target CMT (hari)',
  maklon_cmt_late_grace_days: 'Toleransi telat CMT (hari, H+N)',
  maklon_invoice_prefix: 'Awalan nomor tagihan maklon',
  maklon_payment_terms_default: 'Jangka bayar bawaan',
  maklon_permak_return_grace_days: 'Toleransi kembali permak (hari, H+N)',
  maklon_qc_reject_threshold_pct: 'Ambang tolak QC (%)',
  production_require_material_issued: 'Progres produksi wajib material sudah dikeluarkan (GDG-2)',
  notification_whatsapp_api_key: 'Kunci API / token WhatsApp',
  notification_whatsapp_sender: 'Nomor pengirim WhatsApp',
  notification_telegram_bot_token: 'Token bot Telegram',
  notification_telegram_chat_id: 'ID obrolan Telegram bawaan',
};
// Keterangan dari server sebagian berbahasa Inggris / memuat nama kolom program — diganti untuk tampilan saja.
const DESC_ID = {
  hpp_profit_margin_pct: 'Target margin laba bawaan untuk menghitung harga jual.',
  inventory_allow_negative: 'Aktif: Kirim Material CMT, Pengeluaran Material, dan Cutting tetap jalan walau stok kurang atau belum ada barisnya — stok dipotong sampai minus dan baris dibuat di gudang bawaan (A-* → Ruang Aksesoris, lainnya → gudang bahan). Matikan setelah stok opname selesai agar aturan ketat berlaku lagi.',
  maklon_cmt_buffer_days: 'Selisih hari antara tenggat mitra/pembeli dan target CMT. Target CMT = tenggat pengiriman − cadangan. Dipakai pemantauan Kejar CMT.',
  maklon_cmt_late_grace_days: 'Ambang "telat": pekerjaan dianggap telat bila melewati target CMT lebih dari N hari (mis. H+5). Di bawahnya berstatus "mendekati tenggat".',
  maklon_invoice_prefix: 'Awalan nomor tagihan pesanan maklon. Contoh INV-MKL → INV-MKL-2026-0001.',
  maklon_payment_terms_default: 'Jangka pembayaran bawaan tagihan maklon (jatuh tempo setelah tagihan terbit).',
  maklon_permak_return_grace_days: 'Penanda H+N untuk permak/retur ke CMT: bila melewati tenggat kembali lebih dari N hari, permak ditandai perlu tindakan (mis. H+3).',
  maklon_qc_reject_threshold_pct: 'Ambang persentase tolak QC maklon. Di atas nilai ini sistem mengirim peringatan.',
  marketplace_shopee_enabled: 'Aktifkan integrasi Shopee Open API.',
  marketplace_tokopedia_enabled: 'Aktifkan integrasi API Tokopedia.',
  notification_telegram_chat_id: 'ID obrolan tujuan notifikasi (grup atau pengguna).',
  notification_telegram_enabled: 'Aktifkan/matikan bot Telegram untuk notifikasi.',
  notification_whatsapp_api_key: 'Token atau kunci autentikasi penyedia WhatsApp.',
  notification_whatsapp_enabled: 'Aktifkan/matikan integrasi WhatsApp (Twilio/WABA) untuk notifikasi.',
  notification_whatsapp_sender: 'Nomor pengirim terdaftar, contoh whatsapp:+6281xxxxxxx.',
  production_require_material_issued: 'Aktif: input progres pekerjaan produksi INTERNAL ditolak bila gudang belum menyerahkan material (Pengeluaran Material belum berstatus dikeluarkan). Mati (bawaan sementara): progres boleh diinput tanpa pengeluaran material.',
};
const labelSetelan = (c) => LABEL_ID[c.key] || c.label || c.key;
const keteranganSetelan = (c) => DESC_ID[c.key] || c.description;
const labelKategori = (k) => (CATEGORY_META[k] || { label: k }).label;
const oleh = (u) => (!u || u === 'system_init' ? 'bawaan sistem' : u);
const instan = (ts) => (typeof ts === 'string' && /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(ts) ? `${ts}Z` : ts);

export default function MaklonSystemConfigModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('');
  const [edited, setEdited] = useState({});
  const [showSecret, setShowSecret] = useState({});
  const [ubah, setUbah] = useState(null);
  // 2026-11-07 (Tahap 6, SY2): hanya admin/owner/superadmin yang boleh mengubah (server menolak peran lain).
  const canEdit = useMemo(() => isCurrentUserConfigAdmin(), []);

  const fetchConfigs = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/dewi/system/config', { headers });
      if (r.ok) { setConfigs(await r.json()); setEdited({}); }
      else toast.error('Gagal memuat konfigurasi');
    } catch (e) { toast.error('Gagal memuat konfigurasi'); }
    finally { setLoading(false); }
  }, [headers]);

  useEffect(() => { fetchConfigs(); }, [fetchConfigs]);

  const setValue = (key, value) => setEdited(p => ({ ...p, [key]: value }));

  const currentValue = (cfg) => {
    if (cfg.key in edited) return edited[cfg.key];
    return cfg.value !== undefined ? cfg.value : '';
  };

  // Simpan satu setelan lewat jalur yang sama (bulk) — hanya kunci yang diubah dikirim.
  const saveAll = async () => {
    if (Object.keys(edited).length === 0) { toast.info('Tidak ada perubahan'); setUbah(null); return; }
    setSaving(true);
    try {
      const r = await fetch('/api/dewi/system/config/bulk', { method: 'POST', headers, body: JSON.stringify(edited) });
      if (r.ok) {
        const d = await r.json();
        toast.success(`${d.updated} setelan disimpan`);
        if (d.errors?.length) toast.error(`Tidak tersimpan — ${d.errors.join('; ')}`);
        setUbah(null);
        fetchConfigs();
      } else {
        toast.error('Gagal menyimpan');
      }
    } finally { setSaving(false); }
  };

  const categories = [...new Set(configs.map(c => c.category))];
  const byCategory = configs.filter(c => !activeTab || c.category === activeTab);

  const tampilNilai = (cfg) => {
    const v = cfg.value;
    if (cfg.is_secret) return v || cfg.value_masked ? (cfg.value_masked || 'Tersimpan (rahasia)') : '';
    if (cfg.data_type === 'boolean') return v ? 'Aktif' : 'Nonaktif';
    if (Array.isArray(cfg.choices) && cfg.choices.length) return cfg.choices.find((c) => c.value === v)?.label || (v ? `${v} (tidak dikenal)` : '');
    if (v === null || v === undefined) return '';
    return typeof v === 'number' ? v.toLocaleString('id-ID') : String(v);
  };

  const renderInput = (cfg) => {
    const val = currentValue(cfg);
    const isSecret = cfg.is_secret;
    const show = showSecret[cfg.key];
    if (cfg.data_type === 'boolean') {
      return (
        <label className="flex items-center gap-3 text-sm">
          <Switch checked={!!val} onCheckedChange={(v) => setValue(cfg.key, v)} disabled={!canEdit} data-testid={`cfg-${cfg.key}`} />
          {val ? 'Aktif' : 'Nonaktif'}
        </label>
      );
    }
    // 2026-11-07 (Tahap 5) — setelan berkode tetap dipilih, bukan diketik (server menolak nilai lain).
    if (Array.isArray(cfg.choices) && cfg.choices.length) {
      return (
        <SmartNativeSelect value={val ?? ''} onChange={e => setValue(cfg.key, e.target.value)}
          disabled={!canEdit} className="w-full" data-testid={`cfg-${cfg.key}`}>
          {!cfg.choices.some(c => c.value === val) && <option value={val ?? ''}>{val ? `${val} (tidak dikenal)` : '— pilih —'}</option>}
          {cfg.choices.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </SmartNativeSelect>
      );
    }
    if (cfg.data_type === 'number') {
      return <Input type="number" step="any" value={val ?? ''} onChange={e => setValue(cfg.key, e.target.value)} disabled={!canEdit} className="w-40 tabular-nums" data-testid={`cfg-${cfg.key}`} />;
    }
    if (isSecret) {
      return (
        <div className="flex gap-2">
          <Input type={show ? 'text' : 'password'} autoComplete="off" value={val ?? ''} onChange={e => setValue(cfg.key, e.target.value)} placeholder={cfg.value_masked || '•••••'} disabled={!canEdit} data-testid={`cfg-${cfg.key}`} />
          <Button type="button" size="icon" variant="outline" onClick={() => setShowSecret(p => ({ ...p, [cfg.key]: !p[cfg.key] }))}
            title={show ? 'Sembunyikan' : 'Tampilkan yang diketik'} aria-label={show ? 'Sembunyikan' : 'Tampilkan yang diketik'}>
            {show ? <EyeOff /> : <Eye />}
          </Button>
        </div>
      );
    }
    return <Input value={val ?? ''} onChange={e => setValue(cfg.key, e.target.value)} disabled={!canEdit} data-testid={`cfg-${cfg.key}`} />;
  };

  const kolom = [
    { kunci: 'label', label: 'Setelan', hp: 'judul', isi: (c) => (
      <div className="min-w-0 md:max-w-[26rem]">
        <p className="font-medium text-foreground">{labelSetelan(c)}{c.is_secret && <Lock className="ml-1 inline h-3.5 w-3.5 text-muted-foreground" aria-label="rahasia" />}</p>
        {keteranganSetelan(c) && <p className="text-xs text-muted-foreground">{keteranganSetelan(c)}</p>}
      </div>) },
    { kunci: 'kategori', label: 'Kategori', isi: (c) => <span className="text-sm">{labelKategori(c.category)}</span> },
    { kunci: 'nilai', label: 'Nilai', isi: (c) => (c.data_type === 'boolean'
      ? <StatusBadge status={c.value ? 'aktif' : 'nonaktif'} label={c.value ? 'Aktif' : 'Nonaktif'} tone={c.value ? 'success' : 'muted'} />
      : <span className="break-all text-sm">{tampilNilai(c) || <span className="text-muted-foreground">Belum diisi</span>}</span>) },
    { kunci: 'diperbarui', label: 'Diperbarui', isi: (c) => (c.updated_at
      ? <span className="text-sm">{formatDateTimeID(instan(c.updated_at))}<span className="block text-xs text-muted-foreground">oleh {oleh(c.updated_by)}</span></span>
      : <span className="text-sm text-muted-foreground">—</span>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (c) => (
      <Button size="sm" variant="outline" onClick={() => { setEdited({}); setUbah(c); }} data-testid={`cfg-edit-${c.key}`}>
        {canEdit ? <><Pencil />Ubah</> : <><Eye />Lihat</>}
      </Button>) },
  ];

  return (
    <PageLayout testId="maklon-system-config" title="Konfigurasi maklon"
      subtitle="Setelan sistem yang bisa diatur tanpa mengubah program: pajak, ambang, jangka bayar, dan kunci integrasi."
      filters={configs.length > 0 && (
        <FilterChips className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" value={activeTab} onChange={setActiveTab} hideWhenEmpty={false} testId="cfg-category-filter" options={[
          { key: '', label: 'Semua', count: configs.length },
          ...categories.map((cat) => ({ key: cat, label: labelKategori(cat), count: configs.filter((c) => c.category === cat).length })),
        ]} />
      )}
      tools={<>
        <TombolUnduh namaBerkas="konfigurasi-maklon" namaLembar="Setelan" baris={byCategory} testId="cfg-unduh" kolom={[
          { label: 'Setelan', nilai: (c) => labelSetelan(c) }, { label: 'Kategori', nilai: (c) => labelKategori(c.category) },
          // Nilai rahasia TIDAK ikut diunduh.
          { label: 'Nilai', nilai: (c) => (c.is_secret ? (c.value || c.value_masked ? 'Tersimpan (rahasia)' : 'Belum diisi') : tampilNilai(c)) },
          { label: 'Keterangan', nilai: (c) => keteranganSetelan(c) || '' },
          { label: 'Diperbarui', nilai: (c) => (c.updated_at ? formatDateTimeID(instan(c.updated_at)) : '') },
          { label: 'Oleh', nilai: (c) => oleh(c.updated_by) },
        ]} />
        <Button variant="outline" size="icon" onClick={fetchConfigs} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="cfg-refresh-btn">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {!canEdit && (
        <Notice tone="info" icon={Lock} testId="cfg-readonly-note" title="Mode baca saja">
          Pengaturan sistem hanya bisa diubah oleh admin, owner, atau superadmin.
        </Notice>
      )}

      {loading && configs.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat konfigurasi…</p>
      ) : (
        <TabelData kolom={kolom} baris={byCategory} kunci={(c) => c.key} onKlikBaris={(c) => { setEdited({}); setUbah(c); }}
          testId="cfg-table" kosong={<EmptyState title="Tidak ada setelan di kategori ini" />} />
      )}

      <FormPopup open={!!ubah} onClose={() => { setEdited({}); setUbah(null); }} ukuran="pendek" testId="cfg-form"
        judul={ubah ? labelSetelan(ubah) : ''} keterangan={ubah ? keteranganSetelan(ubah) : undefined}
        onSimpan={saveAll} menyimpan={saving} bisaSimpan={canEdit && Object.keys(edited).length > 0}>
        {ubah && (
          <Isian label="Nilai" petunjuk={ubah.is_secret ? 'Nilai rahasia tidak ditampilkan. Isi untuk menggantinya.' : `Kategori: ${labelKategori(ubah.category)}`}>
            {renderInput(ubah)}
          </Isian>
        )}
        {canEdit && (
          <p className="text-xs text-muted-foreground">Perubahan berlaku setelah disimpan.</p>
        )}
      </FormPopup>
    </PageLayout>
  );
}
