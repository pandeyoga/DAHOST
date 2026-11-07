/**
 * Kesehatan Akun (Portal Marketing) — skor kesehatan toko di marketplace (SES, telat kirim, batal, respons).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris, kartu StatTile dengan keterangan
 * sumber ("status terakhir tiap akun" + tanggal snapshot terbaru), tabel standar + unduh Excel/CSV, form impor
 * tangkapan layar = FormPopup (dua langkah), tanpa emoji/warna mentah.
 *
 * Perbaikan angka: panah tren dulu membandingkan baris dengan BARIS BERIKUTNYA di tabel — sering akun lain
 * (Shopee GHS dibandingkan dengan Shopee Outfit Boutique). Kini dibandingkan dengan snapshot SEBELUMNYA milik
 * akun yang sama (data yang sudah dimuat).
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  TrendingUp, TrendingDown, Minus, Activity, RefreshCw, Upload, Camera, X, Info,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { useToast } from '@/hooks/use-toast';
import { useMarketingAccounts } from '@/hooks/useMarketingAccounts';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import { formatDateID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { ActiveAccountBar } from './ActiveAccountBar';
import axios from 'axios';

const API = process.env.REACT_APP_BACKEND_URL;

const PLATFORM_LABEL = { shopee: 'Shopee', tiktok: 'TikTok', tiktokshop: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const labelPlatform = (p) => PLATFORM_LABEL[String(p || '').toLowerCase()] || p || '—';
const STATUS = {
  healthy: { label: 'Sehat', tone: 'success' },
  warning: { label: 'Perlu perhatian', tone: 'warning' },
  critical: { label: 'Kritis', tone: 'danger' },
};
const tgl = (v) => (v ? formatDateID(parseServerTime(v)) : '—');
const persen = (v) => (v != null ? `${Number(v).toLocaleString('id-ID')}%` : '—');

function StatusKesehatan({ status }) {
  const c = STATUS[status] || STATUS.healthy;
  return <StatusBadge status={status} label={c.label} tone={c.tone} />;
}

function TrendIndicator({ current, previous }) {
  if (previous == null || current == null) return <Minus size={14} className="text-muted-foreground" aria-label="Belum ada pembanding" />;
  const diff = current - previous;
  if (Math.abs(diff) < 0.5) return <Minus size={14} className="text-muted-foreground" aria-label="Stabil" />;
  return diff > 0
    ? <TrendingUp size={14} className="text-[hsl(var(--success-text))]" aria-label={`Naik dari ${previous}`} />
    : <TrendingDown size={14} className="text-[hsl(var(--danger-text))]" aria-label={`Turun dari ${previous}`} />;
}

// ── Impor tangkapan layar kesehatan akun (dua langkah: unggah → periksa) ─────────────
function OCRModal({ open, onClose, onSaved, token }) {
  const { toast } = useToast();
  const fileRef = useRef();
  const [step, setStep] = useState('upload');   // upload | review | saving
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [extracted, setExtracted] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editData, setEditData] = useState({});
  const [selectedAccountId, setSelectedAccountId] = useState('');
  const [galat, setGalat] = useState('');

  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }),
    [token]
  );
  const { accounts: masterAccounts, byId: accountById } = useMarketingAccounts(token);

  const selectedAccount = selectedAccountId ? accountById[selectedAccountId] : null;
  const platform = selectedAccount?.platform || 'shopee';
  const accountName = selectedAccount?.account_name || '';

  const reset = () => {
    setStep('upload'); setFile(null); setPreview(null);
    setExtracted(null); setEditData({}); setLoading(false);
    setSelectedAccountId(''); setGalat('');
  };

  const handleClose = () => { reset(); onClose(); };

  const handleFile = (f) => {
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  const runOCR = async () => {
    if (!file) { setGalat('Pilih tangkapan layar dulu.'); return; }
    if (!selectedAccountId) { setGalat('Pilih akun dari master dulu.'); return; }
    setLoading(true);
    setGalat('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('platform', platform);
      form.append('account_name', accountName);
      form.append('account_id', selectedAccountId);  // FK ke master
      const res = await axios.post(`${API}/api/marketing/health/ocr-screenshot`, form, {
        headers: { ...authH, 'Content-Type': 'multipart/form-data' }
      });
      if (res.data.success) {
        setExtracted(res.data.data.extracted);
        // account_id disisipkan supaya simpanan tetap tertaut ke master
        setEditData({ ...res.data.data.preview, account_id: selectedAccountId, account_name: accountName, platform });
        setStep('review');
        toast({ title: 'Tangkapan layar terbaca', description: 'Periksa hasilnya sebelum menyimpan.' });
      }
    } catch (e) {
      setGalat(`Gagal membaca tangkapan layar: ${e.response?.data?.detail || e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setStep('saving');
    setGalat('');
    try {
      await axios.post(`${API}/api/marketing/health/manual-snapshot`, editData, { headers: authH });
      toast({ title: 'Snapshot disimpan', description: `Akun ${editData.account_name} ditambahkan.` });
      onSaved();
      handleClose();
    } catch (e) {
      setGalat(e.response?.data?.detail || 'Gagal menyimpan snapshot');
      setStep('review');
    }
  };

  const numField = (key, label, unit = '') => (
    <Isian key={key} label={unit ? `${label} (${unit})` : label} htmlFor={`ocr-${key}`}>
      <Input id={`ocr-${key}`} type="number" step="0.01"
        value={editData[key] ?? ''}
        onChange={e => setEditData(d => ({ ...d, [key]: e.target.value === '' ? null : Number(e.target.value) }))} />
    </Isian>
  );

  const review = step === 'review' || step === 'saving';
  return (
    <FormPopup open={open} onClose={handleClose} ukuran="panjang" testId="health-ocr-form"
      judul="Impor tangkapan layar kesehatan akun"
      keterangan="Unggah tangkapan layar dari Seller Center Shopee/TikTok; AI membaca angkanya, Anda memeriksa sebelum menyimpan."
      onSimpan={review ? handleSave : runOCR} menyimpan={loading || step === 'saving'} galat={galat}
      bisaSimpan={review ? !!editData.account_id : (!!file && !!selectedAccountId)}
      labelSimpan={review ? 'Simpan snapshot' : 'Baca dengan AI'}
      aksiKiri={review && (
        <Button type="button" variant="outline" onClick={() => { setStep('upload'); setGalat(''); }}>
          <Camera />Unggah ulang
        </Button>
      )}>
      {!review && (
        <>
          <Isian label="Akun dari master" wajib
            petunjuk={selectedAccount
              ? `Platform ${labelPlatform(platform)}. Snapshot tertaut ke akun ini sehingga skor kesehatannya ikut diperbarui.`
              : (masterAccounts.length === 0 ? 'Belum ada akun aktif — buat dulu di Kelola akun.' : undefined)}>
            <SmartNativeSelect className="w-full sm:w-80" value={selectedAccountId} onChange={(e) => setSelectedAccountId(e.target.value)}
              data-testid="health-ocr-account-select">
              <option value="">Pilih akun…</option>
              {masterAccounts.map(acc => (
                <option key={acc.id} value={acc.id}>{acc.account_name} ({labelPlatform(acc.platform)})</option>
              ))}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Tangkapan layar" wajib petunjuk="PNG, JPG, WEBP — maks 10 MB. Dari halaman Kesehatan Toko (Shopee) atau Kesehatan Akun (TikTok).">
            <div
              role="button" tabIndex={0}
              className={`cursor-pointer rounded-md border border-dashed p-6 text-center transition-colors ${
                file ? 'border-[hsl(var(--primary))]' : 'border-[var(--glass-border)] hover:border-[hsl(var(--primary)/0.5)]'}`}
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click(); }}
              onDrop={handleDrop}
              onDragOver={e => e.preventDefault()}
              data-testid="ocr-dropzone"
            >
              {preview ? (
                <div className="relative inline-block">
                  <img src={preview} alt="Pratinjau tangkapan layar" className="mx-auto max-h-48 rounded-md object-contain" />
                  <Button type="button" variant="outline" size="icon-sm" className="absolute -right-3 -top-3"
                    aria-label="Hapus gambar" title="Hapus gambar"
                    onClick={e => { e.stopPropagation(); setFile(null); setPreview(null); }}>
                    <X />
                  </Button>
                </div>
              ) : (
                <>
                  <Upload className="mx-auto mb-2 h-6 w-6 text-muted-foreground" />
                  <p className="text-sm">Tarik gambar ke sini atau klik untuk memilih</p>
                </>
              )}
              <input ref={fileRef} type="file" accept="image/*" className="hidden"
                onChange={e => handleFile(e.target.files[0])} />
            </div>
          </Isian>
        </>
      )}

      {review && (
        <>
          {extracted?.extraction_notes && (
            <Notice tone="warning" icon={Info}>{extracted.extraction_notes}</Notice>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Isian label="Platform">
              <p className="text-sm" data-testid="snapshot-platform-readonly">{labelPlatform(editData.platform)}</p>
            </Isian>
            <Isian label="Nama akun">
              <p className="text-sm" data-testid="snapshot-account-readonly">{editData.account_name || '—'}</p>
            </Isian>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {numField('ses_score', 'Skor SES')}
            {numField('rating_score', 'Rating produk')}
            {numField('response_rate', 'Tingkat respons', '%')}
            {numField('response_time_hours', 'Waktu respons', 'jam')}
            {numField('late_shipment_rate', 'Telat kirim', '%')}
            {numField('cancellation_rate', 'Tingkat batal', '%')}
            {numField('order_defect_rate', 'Pesanan bermasalah', '%')}
            {numField('return_rate', 'Tingkat retur', '%')}
            {numField('total_reviews', 'Jumlah ulasan')}
          </div>
        </>
      )}
    </FormPopup>
  );
}

// ── Main Component ────────────────────────────────────────────────────
export default function AccountHealthDashboard({ token }) {
  const { toast } = useToast();
  const { activeAccount, setActiveAccount } = useActiveMarketingAccount();
  const { accounts: masterAccounts } = useMarketingAccounts(token);
  const [summary, setSummary] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [showOCR, setShowOCR] = useState(false);

  const [platformFilter, setPlatformFilter] = useState('');
  const [accountFilter, setAccountFilter] = useState('');
  const [accounts, setAccounts] = useState([]);
  const [days, setDays] = useState(90);

  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const res = await axios.get(`${API}/api/marketing/health/summary`, { headers: authH });
      if (res.data.success) setSummary(res.data.data);
    } catch (e) {
      toast({ title: 'Gagal memuat ringkasan', variant: 'destructive' });
    } finally {
      setSummaryLoading(false);
    }
  }, [token]); // eslint-disable-line

  const fetchTimeline = useCallback(async () => {
    setLoading(true);
    try {
      const params = { days };
      if (platformFilter) params.platform = platformFilter;
      if (accountFilter) params.account = accountFilter;
      const res = await axios.get(`${API}/api/marketing/health/timeline`, { params, headers: authH });
      if (res.data.success) setTimeline(res.data.data.snapshots || []);
    } catch (e) {
      toast({ title: 'Gagal memuat riwayat kesehatan', variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [days, platformFilter, accountFilter, token]); // eslint-disable-line

  const fetchAccounts = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/marketing/health/accounts`, { headers: authH });
      if (res.data.success) setAccounts(res.data.data.accounts || []);
    } catch (e) { /* daftar akun pilihan tetap kosong */ }
  }, [token]); // eslint-disable-line

  const onSaved = () => { fetchSummary(); fetchTimeline(); fetchAccounts(); };

  useEffect(() => { fetchSummary(); fetchAccounts(); }, [fetchSummary, fetchAccounts]);
  useEffect(() => { fetchTimeline(); }, [fetchTimeline]);

  // Pembanding tren = snapshot SEBELUMNYA milik akun yang sama (bukan baris berikutnya di tabel)
  const sebelumnya = useMemo(() => {
    const urut = [...timeline].sort((a, b) => String(a.snapshot_date).localeCompare(String(b.snapshot_date)));
    const terakhir = {};
    const out = {};
    urut.forEach((s) => {
      const k = s.account_id || s.account_name;
      out[s.id] = terakhir[k] || null;
      terakhir[k] = s;
    });
    return out;
  }, [timeline]);

  const latest = summary?.latest_snapshots || [];
  const tanggalTerbaru = latest.reduce((m, s) => (String(s.snapshot_date) > m ? String(s.snapshot_date) : m), '');
  const nilai = (v) => (summaryLoading && !summary ? '…' : (v || 0));

  const kolom = [
    { kunci: 'tgl', label: 'Tanggal', isi: (s) => <span className="text-muted-foreground md:whitespace-nowrap">{tgl(s.snapshot_date)}</span> },
    { kunci: 'akun', label: 'Akun', hp: 'judul', isi: (s) => (
      <span className="font-medium">{s.account_name}{s.source === 'manual' && <span className="ml-1 text-xs font-normal text-muted-foreground">(manual)</span>}</span>) },
    { kunci: 'platform', label: 'Platform', hp: 'keterangan', isi: (s) => labelPlatform(s.platform) },
    { kunci: 'ses', label: 'Skor SES', rata: 'kanan', isi: (s) => (
      <span className="inline-flex items-center gap-1">
        <span className="font-semibold tabular-nums">{s.ses_score ?? '—'}</span>
        <TrendIndicator current={s.ses_score} previous={sebelumnya[s.id]?.ses_score} />
      </span>) },
    { kunci: 'late', label: 'Telat kirim', rata: 'kanan', isi: (s) => <span className="tabular-nums">{persen(s.late_shipment_rate)}</span> },
    { kunci: 'cancel', label: 'Batal', rata: 'kanan', isi: (s) => <span className="tabular-nums">{persen(s.cancellation_rate)}</span> },
    { kunci: 'resp', label: 'Tingkat respons', rata: 'kanan', isi: (s) => <span className="tabular-nums">{persen(s.response_rate)}</span> },
    { kunci: 'status', label: 'Status', isi: (s) => <StatusKesehatan status={s.status} /> },
  ];

  return (
    <PageLayout testId="health-dashboard" title="Kesehatan akun"
      subtitle="Skor kesehatan toko di marketplace: skor SES, telat kirim, batal, dan tingkat respons."
      actions={<Button onClick={() => setShowOCR(true)} data-testid="import-screenshot-btn"><Camera />Impor tangkapan layar</Button>}
      filters={<>
        <ActiveAccountBar
          accounts={masterAccounts}
          activeAccount={activeAccount}
          onAccountChange={(acc) => {
            setActiveAccount(acc);
            setAccountFilter(acc ? acc.account_name : '');
          }}
          hint="Saring data kesehatan per akun"
        />
        <SmartNativeSelect className="w-40" value={platformFilter} onChange={(e) => setPlatformFilter(e.target.value)}
          data-testid="health-filter-platform">
          <option value="">Semua platform</option>
          <option value="shopee">Shopee</option>
          <option value="tiktok">TikTok</option>
          <option value="tokopedia">Tokopedia</option>
        </SmartNativeSelect>
        <SmartNativeSelect className="w-48" value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)}
          data-testid="health-filter-account">
          <option value="">Semua akun</option>
          {accounts.map(a => <option key={a} value={a}>{a}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect className="w-36" value={String(days)} onChange={(e) => setDays(Number(e.target.value))}
          data-testid="health-filter-days">
          <option value="30">30 hari</option>
          <option value="60">60 hari</option>
          <option value="90">90 hari</option>
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="kesehatan-akun-toko" namaLembar="Kesehatan akun" baris={timeline} testId="health-export-csv"
          kolom={[
            { label: 'Tanggal', nilai: (t) => tgl(t.snapshot_date) }, { label: 'Akun', nilai: (t) => t.account_name },
            { label: 'Platform', nilai: (t) => labelPlatform(t.platform) }, { label: 'Skor SES', nilai: (t) => t.ses_score ?? '' },
            { label: 'Telat kirim (%)', nilai: (t) => t.late_shipment_rate ?? '' }, { label: 'Batal (%)', nilai: (t) => t.cancellation_rate ?? '' },
            { label: 'Tingkat respons (%)', nilai: (t) => t.response_rate ?? '' },
            { label: 'Status', nilai: (t) => (STATUS[t.status] || STATUS.healthy).label },
            { label: 'Sumber', nilai: (t) => (t.source === 'manual' ? 'Manual' : 'Otomatis') },
          ]} />
        <Button variant="outline" size="icon" onClick={() => { fetchSummary(); fetchTimeline(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang" data-testid="health-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={(
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="health-kpi">
          <StatTile label="Akun dipantau" value={nilai(summary?.total_accounts)}
            sub={tanggalTerbaru ? `Snapshot terbaru ${tgl(tanggalTerbaru)}` : 'Belum ada snapshot'} />
          <StatTile label="Sehat" value={nilai(summary?.healthy)} accent="success" sub="Menurut snapshot terakhir tiap akun" />
          <StatTile label="Perlu perhatian" value={nilai(summary?.warning)} accent="warning" sub="Menurut snapshot terakhir tiap akun" />
          <StatTile label="Kritis" value={nilai(summary?.critical)} accent="danger" sub="Menurut snapshot terakhir tiap akun" />
        </div>
      )}>
      {loading && timeline.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">Memuat riwayat kesehatan…</p>
      ) : (
        <TabelData kolom={kolom} baris={timeline} testId="health-table"
          kosong={<EmptyState icon={Activity} title="Belum ada data kesehatan pada saringan ini"
            description="Ubah saringan, atau impor tangkapan layar Seller Center."
            action={<Button variant="outline" onClick={() => setShowOCR(true)}><Camera />Impor tangkapan layar</Button>} />} />
      )}

      <OCRModal open={showOCR} onClose={() => setShowOCR(false)} onSaved={onSaved} token={token} />
    </PageLayout>
  );
}
