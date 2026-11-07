/**
 * Pengaturan Sistem › Perusahaan — profil tiap CV (nama, alamat, NPWP, logo, kop PDF, status pajak).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di hub judul disembunyikan), profil tampil sebagai ringkasan
 * baca + pratinjau kop; mengubah = FormPopup (dulu form panjang di halaman, tombol Simpan di paling bawah);
 * status pajak lewat FormPopup pendek dengan pemilih tanggal seragam (dulu input tanggal bawaan browser).
 * Data, validasi PKP, dan jalur simpan tidak berubah.
 */
import { useState, useEffect } from 'react';
import { Image as ImageIcon, Pencil, Receipt, RefreshCw, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { GlassCard } from '@/components/ui/glass';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { resetTaxProfileCache } from '../../lib/taxProfile';
import FilterChips from '@/components/ui/filter-chips';
import { CV_DA, CV_SMU, cvLabel } from '@/lib/entitas';
import { formatDateID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { StatusBadge } from './moduleAtoms';

// Tahap 8 (dua CV): satu profil per CV — nama, alamat, NPWP, logo, kop PDF, dan status PKP masing-masing.
const CV_CHOICES = [{ key: CV_DA, label: cvLabel(CV_DA) }, { key: CV_SMU, label: cvLabel(CV_SMU) }];
const OPSI_PAJAK = [
  { v: false, t: 'Non-PKP', d: 'Tidak memungut PPN. PPN dari supplier masuk ke harga beli.' },
  { v: true, t: 'PKP', d: 'Memungut PPN 12% × DPP 11/12 (efektif 11%, kode 04). PPN supplier dikreditkan.' },
];

function Bagian({ judul, alat, children, testId, className }) {
  return (
    <GlassCard className={`space-y-3 p-4 ${className || ''}`} data-testid={testId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-foreground">{judul}</h3>
        {alat}
      </div>
      {children}
    </GlassCard>
  );
}

export default function CompanySettingsModule({ token, userRole }) {
  const [settings, setSettings] = useState({
    company_name: '', company_address: '', company_phone: '',
    company_email: '', company_website: '', company_logo_url: '',
    pdf_header_line1: '', pdf_header_line2: '', pdf_footer_text: '', npwp: '',
  });
  const [tersimpan, setTersimpan] = useState(null);
  // 2026-11-03: saklar Status Pajak (SSOT backend core/tax_status.py)
  const [tax, setTax] = useState({ pkp: false, pkp_since: '' });
  const [taxSaved, setTaxSaved] = useState({ pkp: false, pkp_since: '' });
  const [taxHistory, setTaxHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [cv, setCv] = useState(CV_DA);
  const [form, setForm] = useState(null); // null | 'profil' | 'pajak'

  const canEdit = ['superadmin', 'admin'].includes(userRole);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchSettings(); }, [cv]);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/company-settings?entity=${cv}`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (data && !data.error) {
        const s = {
          company_name: data.company_name || '',
          company_address: data.company_address || '',
          company_phone: data.company_phone || '',
          company_email: data.company_email || '',
          company_website: data.company_website || '',
          company_logo_url: data.company_logo_url || '',
          pdf_header_line1: data.pdf_header_line1 || '',
          pdf_header_line2: data.pdf_header_line2 || '',
          pdf_footer_text: data.pdf_footer_text || '',
          npwp: data.npwp || '',
        };
        setSettings(s); setTersimpan(s);
        const tp = { pkp: !!data.tax_profile?.pkp, pkp_since: data.tax_profile?.pkp_since || '' };
        setTax(tp); setTaxSaved(tp);
        setTaxHistory(Array.isArray(data.tax_profile_history) ? data.tax_profile_history.slice(-5).reverse() : []);
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleSave = async () => {
    const taxChanged = tax.pkp !== taxSaved.pkp || (tax.pkp && tax.pkp_since !== taxSaved.pkp_since);
    if (!settings.company_name.trim()) { toast.error('Nama perusahaan wajib diisi.'); return; }
    // 2026-11-07 (audit form Tahap 5): syarat PKP disebut sebelum simpan (dulu baru ditolak server), dan
    // konfirmasi memakai dialog aplikasi (PANDUAN_UI G9 — dulu window.confirm/alert bawaan browser).
    if (tax.pkp && !tax.pkp_since) { toast.error('Isi tanggal "PKP sejak" (tanggal pengukuhan PKP).'); return; }
    if (tax.pkp && !settings.npwp.trim()) { toast.error('Isi NPWP perusahaan dulu — wajib untuk status PKP.'); return; }
    if (taxChanged && !(await confirmDialog(tax.pkp
      ? { title: `Ubah status pajak menjadi PKP sejak ${formatDateID(tax.pkp_since)}?`, confirmLabel: 'Ubah ke PKP',
          body: 'Dokumen penjualan baru akan memungut PPN 12% × DPP 11/12, dan PPN dari supplier dikreditkan. Dokumen lama tidak berubah.' }
      : { title: 'Ubah status pajak menjadi Non-PKP?', confirmLabel: 'Ubah ke Non-PKP',
          body: 'Dokumen penjualan baru tidak memungut PPN, dan PPN dari supplier dicatat sebagai bagian harga beli. Dokumen lama tidak berubah.' }))) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/company-settings?entity=${cv}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ...settings, tax_profile: tax, entity: cv }),
      });
      if (res.ok) {
        const data = await res.json();
        const tp = { pkp: !!data.tax_profile?.pkp, pkp_since: data.tax_profile?.pkp_since || '' };
        setTax(tp); setTaxSaved(tp);
        setTaxHistory(Array.isArray(data.tax_profile_history) ? data.tax_profile_history.slice(-5).reverse() : []);
        resetTaxProfileCache();
        setTersimpan(settings);
        toast.success(`Profil ${cvLabel(cv)} tersimpan.`);
        setForm(null);
      } else {
        const data = await res.json().catch(() => ({}));
        toast.error(data.detail || data.error || 'Gagal menyimpan');
      }
    } catch (e) { toast.error('Gagal menyimpan: ' + e.message); }
    setSaving(false);
  };

  const handleLogoUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type and size
    if (!file.type.startsWith('image/')) {
      toast.error('Hanya file gambar yang diperbolehkan');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      toast.error('Ukuran file maksimal 2 MB');
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      // 2026-11-06 (pola P1/P6): /api/upload membaca entity_type/entity_id dari query dan membalas
      // `storage_path` (bukan url/filepath/filename) — dulu logo tidak pernah terisi dan penolakan
      // server diam saja. Logo dipasang lewat /api/uploads/<path> (tanpa token, aman untuk <img>).
      const res = await fetch(`/api/upload?entity_type=company_logo&entity_id=${cv === CV_DA ? 'general' : cv.toLowerCase()}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.storage_path) throw new Error(data.detail || 'server menolak berkas');
      setSettings(s => ({ ...s, company_logo_url: `/api/uploads/${data.storage_path}` }));
    } catch (e) {
      toast.error('Gagal mengunggah logo: ' + e.message);
    }
    setUploading(false);
  };

  const updateField = (field, value) => {
    setSettings(s => ({ ...s, [field]: value }));
  };

  // Batal di popup = kembalikan isian ke nilai tersimpan.
  const tutupForm = () => {
    if (tersimpan) setSettings(tersimpan);
    setTax(taxSaved);
    setForm(null);
  };

  const p = tersimpan || settings;
  const kosong = (v) => v || <span className="text-muted-foreground">—</span>;

  return (
    <PageLayout testId="company-settings-module" title="Perusahaan"
      subtitle="Informasi tiap CV untuk kop PDF dan dokumen resmi, termasuk status pajaknya."
      actions={canEdit && (
        <Button onClick={() => setForm('profil')} disabled={loading} data-testid="company-edit">
          <Pencil />Ubah profil
        </Button>
      )}
      filters={<>
        <FilterChips className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" options={CV_CHOICES} value={cv} onChange={(k) => setCv(k || CV_DA)} hideWhenEmpty={false}
          testId="company-cv-switch" ariaLabel="Pilih profil CV" />
        <p className="text-xs text-muted-foreground" data-testid="company-cv-note">
          {cv === CV_SMU ? 'Dipakai untuk dokumen maklon (invoice, surat jalan, kwitansi klien) dan buku CV Sukma.' : 'Dipakai untuk dokumen CV Dewi Aditya (toko, penjualan, pembelian, gaji).'}
        </p>
      </>}>
      {loading ? (
        <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
          <RefreshCw className="h-4 w-4 animate-spin" />Memuat profil…
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="min-w-0 space-y-4">
            <Bagian judul="Identitas perusahaan" testId="company-identity">
              <dl className="divide-y divide-[var(--glass-border)]">
                <BarisDetail label="Nama perusahaan">{kosong(p.company_name)}</BarisDetail>
                <BarisDetail label="Alamat"><span className="whitespace-pre-line">{kosong(p.company_address)}</span></BarisDetail>
                <BarisDetail label="Telepon">{kosong(p.company_phone)}</BarisDetail>
                <BarisDetail label="Email"><span className="break-all">{kosong(p.company_email)}</span></BarisDetail>
                <BarisDetail label="NPWP"><span className="break-all tabular-nums">{kosong(p.npwp)}</span></BarisDetail>
                <BarisDetail label="Website"><span className="break-all">{kosong(p.company_website)}</span></BarisDetail>
                <BarisDetail label="Kop baris 1">{kosong(p.pdf_header_line1)}</BarisDetail>
                <BarisDetail label="Kop baris 2">{kosong(p.pdf_header_line2)}</BarisDetail>
                <BarisDetail label="Kaki PDF">{kosong(p.pdf_footer_text)}</BarisDetail>
              </dl>
            </Bagian>

            <Bagian judul="Status pajak" testId="company-tax-status"
              alat={canEdit && (
                <Button variant="outline" size="sm" onClick={() => setForm('pajak')} data-testid="company-tax-edit">
                  <Receipt />Ubah status pajak
                </Button>
              )}>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <StatusBadge status={taxSaved.pkp ? 'pkp' : 'nonpkp'} label={taxSaved.pkp ? 'PKP' : 'Non-PKP'}
                  tone={taxSaved.pkp ? 'primary' : 'default'} testId="company-tax-badge" />
                {taxSaved.pkp && taxSaved.pkp_since && <span>sejak {formatDateID(taxSaved.pkp_since)}</span>}
              </div>
              <p className="text-sm text-muted-foreground">{OPSI_PAJAK.find((o) => o.v === taxSaved.pkp)?.d}</p>
              {taxHistory.length > 0 && (
                <div className="space-y-0.5 border-t border-[var(--glass-border)] pt-3 text-xs text-muted-foreground">
                  <p className="text-sm font-medium text-foreground">Riwayat perubahan</p>
                  {taxHistory.map((h, i) => (
                    <p key={i}>{formatDateID(String(h.at || '').slice(0, 10))} · {h.by}: {h.from_pkp ? 'PKP' : 'Non-PKP'} → {h.to_pkp ? `PKP (sejak ${formatDateID(h.pkp_since)})` : 'Non-PKP'}</p>
                  ))}
                </div>
              )}
            </Bagian>
          </div>

          <Bagian judul="Pratinjau kop PDF" testId="company-pdf-preview" className="self-start">
            <div className="rounded-lg border border-[var(--glass-border)] bg-white p-5 text-black/80">
              <div className="space-y-1 text-center">
                {p.company_logo_url ? (
                  <img src={p.company_logo_url} alt="Logo" className="mx-auto mb-2 h-12 object-contain" />
                ) : (
                  <p className="mx-auto mb-2 flex w-fit items-center gap-1 text-xs text-black/50"><ImageIcon className="h-4 w-4" />Belum ada logo</p>
                )}
                <p className="text-lg font-bold">{p.company_name || 'Nama perusahaan'}</p>
                {p.pdf_header_line1 && <p className="text-xs">{p.pdf_header_line1}</p>}
                {p.pdf_header_line2 && <p className="text-xs">{p.pdf_header_line2}</p>}
                {p.company_address && <p className="text-xs">{p.company_address}</p>}
                {(p.company_phone || p.company_email) && (
                  <p className="text-xs">{[p.company_phone, p.company_email].filter(Boolean).join(' | ')}</p>
                )}
              </div>
              <div className="mb-2 mt-3 border-t-2 border-black/20" />
              <p className="text-center text-sm font-bold">Judul dokumen</p>
              <p className="text-center text-xs">No. dokumen: XXX-001</p>
            </div>
          </Bagian>
        </div>
      )}

      {/* Ubah profil */}
      <FormPopup open={form === 'profil'} onClose={tutupForm} ukuran="panjang" testId="company-form"
        judul={`Ubah profil ${cvLabel(cv)}`} keterangan="Dipakai di kop PDF dan dokumen resmi CV ini."
        onSimpan={handleSave} menyimpan={saving} labelSimpan="Simpan pengaturan">
        <Isian label="Nama perusahaan" wajib htmlFor="company-name">
          <Input id="company-name" required value={settings.company_name} onChange={e => updateField('company_name', e.target.value)}
            placeholder="PT Garment Manufacturing" />
        </Isian>
        <Isian label="Alamat" htmlFor="company-address">
          <Textarea id="company-address" rows={2} value={settings.company_address} onChange={e => updateField('company_address', e.target.value)}
            placeholder="Jl. Industri No. 123, Jakarta" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Telepon" htmlFor="company-phone">
            <Input id="company-phone" value={settings.company_phone} onChange={e => updateField('company_phone', e.target.value)}
              placeholder="+62 21 1234567" />
          </Isian>
          <Isian label="Email" htmlFor="company-email">
            <Input id="company-email" type="email" value={settings.company_email} onChange={e => updateField('company_email', e.target.value)}
              placeholder="info@company.com" />
          </Isian>
          <Isian label="NPWP perusahaan" htmlFor="company-npwp-input" petunjuk="Wajib bila status pajak PKP.">
            <Input id="company-npwp-input" value={settings.npwp} onChange={e => updateField('npwp', e.target.value)}
              placeholder="00.000.000.0-000.000" data-testid="company-npwp" />
          </Isian>
          <Isian label="Website" htmlFor="company-website">
            <Input id="company-website" value={settings.company_website} onChange={e => updateField('company_website', e.target.value)}
              placeholder="www.company.com" />
          </Isian>
        </div>
        <Isian label="Logo" petunjuk="Format JPG, PNG, SVG. Maksimal 2 MB. Atau tempel alamat gambar di bawah.">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-dashed border-[var(--glass-border)]">
              {settings.company_logo_url
                ? <img src={settings.company_logo_url} alt="Logo" className="h-full w-full object-contain p-1" />
                : <ImageIcon className="h-6 w-6 text-muted-foreground" />}
            </div>
            <Button type="button" variant="outline" size="sm" asChild disabled={uploading}>
              <label className="cursor-pointer">
                <Upload />{uploading ? 'Mengunggah…' : 'Unggah logo'}
                <input type="file" accept="image/*" className="hidden" onChange={handleLogoUpload} disabled={uploading} />
              </label>
            </Button>
          </div>
          <Input className="mt-2" value={settings.company_logo_url} onChange={e => updateField('company_logo_url', e.target.value)}
            placeholder="https://example.com/logo.png" aria-label="Alamat gambar logo" />
        </Isian>
        <Isian label="Kop baris 1 (opsional)" htmlFor="company-h1" petunjuk="Teks tambahan di bawah nama perusahaan pada kop PDF.">
          <Input id="company-h1" value={settings.pdf_header_line1} onChange={e => updateField('pdf_header_line1', e.target.value)}
            placeholder="Contoh: Divisi Produksi Garmen" />
        </Isian>
        <Isian label="Kop baris 2 (opsional)" htmlFor="company-h2">
          <Input id="company-h2" value={settings.pdf_header_line2} onChange={e => updateField('pdf_header_line2', e.target.value)}
            placeholder="Contoh: ISO 9001 Certified" />
        </Isian>
        <Isian label="Kaki PDF (opsional)" htmlFor="company-footer">
          <Input id="company-footer" value={settings.pdf_footer_text} onChange={e => updateField('pdf_footer_text', e.target.value)}
            placeholder="Contoh: Dokumen ini dicetak secara otomatis oleh sistem" />
        </Isian>
      </FormPopup>

      {/* Ubah status pajak */}
      <FormPopup open={form === 'pajak'} onClose={tutupForm} ukuran="pendek" testId="company-tax-form"
        judul={`Status pajak ${cvLabel(cv)}`} keterangan="Perubahan hanya berlaku untuk dokumen baru. Faktur, nota, dan tagihan lama tidak berubah."
        onSimpan={handleSave} menyimpan={saving} labelSimpan="Simpan status pajak">
        <div className="grid gap-2" role="radiogroup" aria-label="Status pajak">
          {OPSI_PAJAK.map(o => (
            <label key={o.t} className={`cursor-pointer rounded-lg border px-4 py-3 text-sm ${tax.pkp === o.v ? 'border-primary bg-primary/5' : 'border-[var(--glass-border)]'}`}>
              <span className="flex items-center gap-2 font-medium">
                <input type="radio" name="tax-status" checked={tax.pkp === o.v} className="accent-[hsl(var(--primary))]"
                  onChange={() => setTax(t => ({ ...t, pkp: o.v }))} data-testid={`tax-status-${o.v ? 'pkp' : 'nonpkp'}`} />
                {o.t}
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">{o.d}</span>
            </label>
          ))}
        </div>
        {tax.pkp && (
          <Isian label="PKP sejak" wajib petunjuk="Tanggal pengukuhan PKP dari KPP. NPWP wajib diisi di profil.">
            <DatePicker value={tax.pkp_since} onChange={(v) => setTax(t => ({ ...t, pkp_since: v || '' }))} testId="tax-pkp-since" />
          </Isian>
        )}
      </FormPopup>
    </PageLayout>
  );
}
