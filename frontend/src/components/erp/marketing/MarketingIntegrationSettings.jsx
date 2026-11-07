/**
 * Integrasi API (Portal Toko) — kunci API platform marketplace + pengaturan peringatan marketing.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout; platform = tabel; form kunci API & form pengaturan peringatan
 * dibuka sebagai FormPopup (dulu terbuka di dalam kartu/halaman); riwayat evaluasi = tabel + unduh.
 * Isian, panggilan API, dan data yang disimpan tidak berubah. Waktu riwayat dari server = UTC tanpa zona → WIB.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  CheckCircle2, Trash2, Eye, EyeOff, ExternalLink, RefreshCw, AlertTriangle, Zap, Settings, Info,
} from 'lucide-react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { useToast } from '@/hooks/use-toast';
import { formatDateTimeID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;

const waktu = (v) => {
  if (!v) return '—';
  const s = String(v);
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s}Z`);
  return Number.isNaN(d.getTime()) ? '—' : formatDateTimeID(d);
};
const JENIS_PERINGATAN = {
  expiring_discount: 'Diskon akan habis',
  sla_breach: 'Batas waktu komplain terlewat',
  upcoming_launch: 'Peluncuran mendekat',
  content_today: 'Konten terjadwal hari ini',
  target_behind: 'Target tertinggal',
  budget_overrun: 'Anggaran terlampaui',
  budget_warning: 'Anggaran hampir habis',
};
/** Keterangan platform dalam bahasa staf (keterangan server memuat nama isian program). */
const CATATAN_PLATFORM = {
  shopee: 'Butuh akun Shopee Open Platform dengan ID toko dan kredensial mitra.',
  tiktok: 'Butuh akun mitra TikTok Shop dan akses ke TikTok Open Platform.',
  tokopedia: 'Butuh akun penjual Tokopedia dan akses ke Tokopedia Seller API.',
};
const labelJenis = (types) => (types || []).map((t) => JENIS_PERINGATAN[t] || 'Lainnya').join(', ') || '—';

const DEFAULT_ALERT_SETTINGS = {
  enabled: true,
  discount_expiry_days: 3,
  alert_content_today: true,
  alert_sla_breach: true,
  alert_expiring_discount: true,
  alert_upcoming_launch: true,
};
const PILIHAN_PERINGATAN = (s) => [
  { key: 'alert_expiring_discount', label: 'Diskon akan habis', desc: `${s.discount_expiry_days} hari sebelum diskon berakhir` },
  { key: 'alert_sla_breach', label: 'Batas waktu komplain terlewat', desc: 'Komplain lewat batas waktu atau hampir lewat' },
  { key: 'alert_upcoming_launch', label: 'Peluncuran mendekat', desc: 'H-7, H-3, dan H-1 sebelum peluncuran produk' },
  { key: 'alert_content_today', label: 'Konten terjadwal hari ini', desc: 'Konten terjadwal yang belum diposting' },
];

/** Form kunci API satu platform (popup). Simpan / uji koneksi / hapus kunci memakai handler yang sama seperti dulu. */
function FormPlatform({ platform, meta, config, onClose, onSave, onDisconnect, onTest }) {
  const [form, setForm] = useState({});
  const [showPass, setShowPass] = useState({});
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const connected = config?.connected;

  const handleSave = async () => {
    setSaving(true);
    const res = await onSave(platform, form);
    setSaving(false);
    setForm({});
    if (res) onClose();
  };
  const handleTest = async () => {
    setTesting(true);
    const res = await onTest(platform);
    setTestResult(res);
    setTesting(false);
  };

  return (
    <FormPopup open onClose={onClose} judul={`Kunci API ${meta?.name || platform}`} ukuran="pendek"
      keterangan={CATATAN_PLATFORM[platform] || meta?.note} onSimpan={handleSave} menyimpan={saving} labelSimpan="Simpan kunci"
      testId={`integration-form-${platform}`}
      aksiKiri={<>
        <Button type="button" variant="outline" onClick={handleTest} disabled={testing || !connected}
          title={connected ? 'Uji koneksi dengan kunci tersimpan' : 'Simpan kunci dulu'}>
          {testing ? <RefreshCw className="animate-spin" /> : <Zap />}Uji koneksi
        </Button>
        {connected && (
          <Button type="button" variant="destructive" onClick={async () => { await onDisconnect(platform); onClose(); }}>
            <Trash2 />Hapus kunci
          </Button>
        )}
      </>}>
      {meta?.docs_url && (
        <a href={meta.docs_url} target="_blank" rel="noreferrer"
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
          <ExternalLink className="h-3.5 w-3.5" />Dokumentasi API platform
        </a>
      )}
      {(meta?.fields || []).map((field) => (
        <Isian key={field.key} label={field.label} htmlFor={`int-${platform}-${field.key}`}
          petunjuk={connected && config?.credentials?.[`_${field.key}_masked`]
            ? `Tersimpan: ${config.credentials[`_${field.key}_masked`]} — kosongkan bila tidak diganti.` : undefined}>
          <div className="relative">
            <Input id={`int-${platform}-${field.key}`}
              type={field.type === 'password' && !showPass[field.key] ? 'password' : 'text'}
              placeholder={field.placeholder} value={form[field.key] || ''}
              onChange={(e) => setForm((f) => ({ ...f, [field.key]: e.target.value }))} className="pr-10" />
            {field.type === 'password' && (
              <Button type="button" variant="ghost" size="icon-sm"
                className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground"
                title={showPass[field.key] ? 'Sembunyikan' : 'Tampilkan'} aria-label={showPass[field.key] ? 'Sembunyikan' : 'Tampilkan'}
                onClick={() => setShowPass((s) => ({ ...s, [field.key]: !s[field.key] }))}>
                {showPass[field.key] ? <EyeOff /> : <Eye />}
              </Button>
            )}
          </div>
        </Isian>
      ))}
      {testResult && (
        <Notice tone={testResult.success ? 'success' : 'warning'} icon={testResult.success ? CheckCircle2 : AlertTriangle}
          title={testResult.message}>
          {testResult.note}
        </Notice>
      )}
    </FormPopup>
  );
}

/** Form pengaturan peringatan (popup). Isian dan isi yang dikirim sama dengan form lama di halaman. */
function FormPeringatan({ awal, onClose, onSimpan }) {
  const [s, setS] = useState(awal);
  const [menyimpan, setMenyimpan] = useState(false);
  const simpan = async () => {
    setMenyimpan(true);
    const ok = await onSimpan(s);
    setMenyimpan(false);
    if (ok) onClose();
  };
  return (
    <FormPopup open onClose={onClose} judul="Pengaturan peringatan marketing" ukuran="pendek"
      keterangan="Evaluasi berjalan otomatis setiap 30 menit dan mengirim notifikasi." onSimpan={simpan}
      menyimpan={menyimpan} labelSimpan="Simpan pengaturan" testId="alert-settings-form">
      <label className="flex items-center justify-between gap-3" htmlFor="alert-enabled">
        <span>
          <span className="block text-sm font-medium">Peringatan aktif</span>
          <span className="block text-xs text-muted-foreground">Matikan untuk menghentikan semua peringatan.</span>
        </span>
        <Switch id="alert-enabled" checked={s.enabled || false} onCheckedChange={(v) => setS((x) => ({ ...x, enabled: v }))} />
      </label>
      <div className="space-y-3 border-t border-[var(--glass-border)] pt-3">
        {PILIHAN_PERINGATAN(s).map((item) => (
          <label key={item.key} className="flex items-center justify-between gap-3" htmlFor={`alert-${item.key}`}>
            <span>
              <span className="block text-sm">{item.label}</span>
              <span className="block text-xs text-muted-foreground">{item.desc}</span>
            </span>
            <Switch id={`alert-${item.key}`} checked={s[item.key] || false}
              onCheckedChange={(v) => setS((x) => ({ ...x, [item.key]: v }))} />
          </label>
        ))}
      </div>
    </FormPopup>
  );
}

export default function MarketingIntegrationSettings({ token }) {
  const { toast } = useToast();
  const authH = useMemo(() => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);

  const [meta, setMeta] = useState({});
  const [configs, setConfigs] = useState({});
  const [alertSettings, setAlertSettings] = useState(DEFAULT_ALERT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [alertHistory, setAlertHistory] = useState([]);
  const [histLoading, setHistLoading] = useState(false);
  const [formPlatform, setFormPlatform] = useState(null);
  const [formAlert, setFormAlert] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3] = await Promise.allSettled([
        axios.get(`${API}/api/marketing/integration-settings/meta`, { headers: authH }),
        axios.get(`${API}/api/marketing/integration-settings`, { headers: authH }),
        axios.get(`${API}/api/marketing/alerts/settings`, { headers: authH }),
      ]);
      if (r1.status === 'fulfilled') setMeta(r1.value.data.platforms || {});
      if (r2.status === 'fulfilled') setConfigs(r2.value.data.data || {});
      if (r3.status === 'fulfilled') setAlertSettings((s) => ({ ...s, ...r3.value.data.data }));
    } catch {}
    finally { setLoading(false); }
  }, [authH]);

  const fetchHistory = useCallback(async () => {
    setHistLoading(true);
    try {
      const res = await axios.get(`${API}/api/marketing/alerts/history`, { headers: authH, params: { limit: 10 } });
      if (res.data.success) setAlertHistory(res.data.data || []);
    } catch {}
    finally { setHistLoading(false); }
  }, [authH]);

  useEffect(() => { fetchAll(); fetchHistory(); }, [fetchAll, fetchHistory]);

  const namaPlatform = (p) => meta[p]?.name || p;

  const handleSavePlatform = async (platform, form) => {
    try {
      const res = await axios.put(`${API}/api/marketing/integration-settings/${platform}`,
        { credentials: form }, { headers: authH });
      if (res.data.success) {
        toast({ title: `Kunci API ${namaPlatform(platform)} tersimpan.` });
        fetchAll();
        return true;
      }
    } catch { toast({ title: 'Gagal menyimpan kunci API', variant: 'destructive' }); }
    return false;
  };

  const handleDisconnect = async (platform) => {
    if (!(await confirmDialog({
      title: `Hapus kunci API ${namaPlatform(platform)}?`, body: 'Kunci yang tersimpan dihapus. Isi lagi bila ingin menyambung.',
      confirmLabel: 'Hapus kunci', danger: true,
    }))) return;
    try {
      await axios.delete(`${API}/api/marketing/integration-settings/${platform}`, { headers: authH });
      toast({ title: `Kunci API ${namaPlatform(platform)} dihapus.` });
      fetchAll();
    } catch { toast({ title: 'Gagal menghapus kunci API', variant: 'destructive' }); }
  };

  const handleTestPlatform = async (platform) => {
    try {
      const res = await axios.post(`${API}/api/marketing/integration-settings/${platform}/test`, {}, { headers: authH });
      return res.data;
    } catch (e) {
      return { success: false, message: 'Koneksi gagal', note: e.message };
    }
  };

  const saveAlertSettings = async (nilai) => {
    try {
      await axios.put(`${API}/api/marketing/alerts/settings`, nilai, { headers: authH });
      setAlertSettings(nilai);
      toast({ title: 'Pengaturan peringatan disimpan.' });
      return true;
    } catch { toast({ title: 'Gagal menyimpan pengaturan peringatan', variant: 'destructive' }); return false; }
  };

  const triggerNow = async () => {
    try {
      const res = await axios.post(`${API}/api/marketing/alerts/evaluate`, {}, { headers: authH });
      toast({ title: `${res.data.total_fired} peringatan dikirim.` });
      fetchHistory();
    } catch { toast({ title: 'Gagal menjalankan evaluasi peringatan', variant: 'destructive' }); }
  };

  const platforms = Object.entries(meta).map(([key, m]) => ({ id: key, key, meta: m, config: configs[key] }));
  const jumlahSambung = platforms.filter((p) => p.config?.connected).length;
  const kunciTersimpan = (p) => (p.meta?.fields || [])
    .map((f) => p.config?.credentials?.[`_${f.key}_masked`] && `${f.label}: ${p.config.credentials[`_${f.key}_masked`]}`)
    .filter(Boolean).join(' · ');

  const kolomPlatform = [
    { kunci: 'nama', label: 'Platform', hp: 'judul', isi: (p) => <span className="font-medium text-foreground">{p.meta?.name || p.key}</span> },
    { kunci: 'status', label: 'Status', isi: (p) => (p.config?.connected
      ? <StatusBadge status="terhubung" label="Kunci tersimpan" tone="success" />
      : <StatusBadge status="belum" label="Belum diatur" tone="muted" />) },
    { kunci: 'kunci', label: 'Kunci tersimpan', isi: (p) => <span className="text-sm text-muted-foreground">{kunciTersimpan(p) || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (p) => (
      <Button size="sm" variant="outline" onClick={() => setFormPlatform(p)} data-testid={`integration-edit-${p.key}`}>
        <Settings />Atur kunci
      </Button>) },
  ];

  const kolomRiwayat = [
    { kunci: 'waktu', label: 'Waktu evaluasi', hp: 'judul', isi: (r) => <span className="tabular-nums md:whitespace-nowrap">{waktu(r.ran_at)}</span> },
    { kunci: 'jumlah', label: 'Peringatan dikirim', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.fired_count ?? 0}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (r) => <span className="text-sm">{labelJenis(r.types)}</span> },
  ];

  return (
    <PageLayout testId="integration-settings-page" title="Integrasi API"
      subtitle="Kunci API platform marketplace dan pengaturan peringatan marketing."
      tools={
        <Button variant="outline" size="icon" onClick={() => { fetchAll(); fetchHistory(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      }>
      <Notice tone="info" icon={Info} title="Sinkronisasi langsung belum aktif">
        Kunci API disimpan dulu untuk sinkronisasi pesanan, stok, dan iklan langsung dari platform nanti.
        Saat ini belum ada koneksi nyata ke platform.
      </Notice>

      <section className="space-y-2" data-testid="integration-platforms">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-base font-semibold text-foreground">
            Platform · {loading ? '…' : `${jumlahSambung} dari ${platforms.length} sudah berisi kunci`}
          </p>
          <TombolUnduh namaBerkas="integrasi-platform" namaLembar="Platform" baris={platforms} testId="integration-platform-unduh"
            kolom={[{ label: 'Platform', nilai: (p) => p.meta?.name || p.key },
              { label: 'Status', nilai: (p) => (p.config?.connected ? 'Kunci tersimpan' : 'Belum diatur') },
              { label: 'Kunci tersimpan (disamarkan)', nilai: (p) => kunciTersimpan(p) }]} />
        </div>
        {loading && platforms.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat platform…</p>
        ) : (
          <TabelData kolom={kolomPlatform} baris={platforms} onKlikBaris={setFormPlatform} testId="integration-platform-table"
            kosong={<EmptyState title="Belum ada platform" description="Daftar platform belum tersedia dari server." />} />
        )}
      </section>

      <section className="space-y-2" data-testid="alert-settings">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-base font-semibold text-foreground">Peringatan marketing</p>
          <Button variant="outline" onClick={triggerNow} data-testid="alert-trigger-now"><Zap />Jalankan evaluasi sekarang</Button>
          <Button onClick={() => setFormAlert(true)} data-testid="alert-settings-edit"><Settings />Ubah pengaturan</Button>
        </div>
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {alertSettings.enabled
            ? <StatusBadge status="aktif" label="Aktif" tone="success" />
            : <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />}
          <span>
            {PILIHAN_PERINGATAN(alertSettings).filter((i) => alertSettings[i.key]).map((i) => i.label).join(' · ') || 'Tidak ada jenis peringatan yang dipilih'}
          </span>
        </p>
      </section>

      <section className="space-y-2" data-testid="alert-history">
        <div className="flex flex-wrap items-center gap-2">
          <p className="flex-1 text-base font-semibold text-foreground">Riwayat evaluasi · {alertHistory.length} terakhir</p>
          <TombolUnduh namaBerkas="riwayat-evaluasi-peringatan" namaLembar="Riwayat" baris={alertHistory} testId="alert-history-unduh"
            kolom={[
              { label: 'Waktu evaluasi', nilai: (r) => waktu(r.ran_at) },
              { label: 'Peringatan dikirim', nilai: (r) => r.fired_count ?? 0 },
              { label: 'Jenis', nilai: (r) => labelJenis(r.types) },
            ]} />
          <Button variant="outline" size="icon" onClick={fetchHistory} disabled={histLoading} title="Muat ulang riwayat" aria-label="Muat ulang riwayat">
            <RefreshCw className={histLoading ? 'animate-spin' : ''} />
          </Button>
        </div>
        <TabelData kolom={kolomRiwayat} baris={alertHistory} testId="alert-history-table"
          kosong={!histLoading && <EmptyState title="Belum ada riwayat evaluasi" description="Riwayat muncul setelah evaluasi peringatan pertama berjalan." />} />
      </section>

      {formPlatform && (
        <FormPlatform platform={formPlatform.key} meta={formPlatform.meta} config={configs[formPlatform.key]}
          onClose={() => setFormPlatform(null)} onSave={handleSavePlatform} onDisconnect={handleDisconnect} onTest={handleTestPlatform} />
      )}
      {formAlert && <FormPeringatan awal={alertSettings} onClose={() => setFormAlert(false)} onSimpan={saveAlertSettings} />}
    </PageLayout>
  );
}
