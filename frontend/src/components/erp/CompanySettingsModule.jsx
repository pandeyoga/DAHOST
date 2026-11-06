
import { useState, useEffect } from 'react';
import { Settings, Save, Upload, Building2, FileText, RefreshCw, CheckCircle, Image, Receipt } from 'lucide-react';
import { resetTaxProfileCache } from '../../lib/taxProfile';

export default function CompanySettingsModule({ token, userRole }) {
  const [settings, setSettings] = useState({
    company_name: '', company_address: '', company_phone: '',
    company_email: '', company_website: '', company_logo_url: '',
    pdf_header_line1: '', pdf_header_line2: '', pdf_footer_text: '', npwp: '',
  });
  // 2026-11-03: saklar Status Pajak (SSOT backend core/tax_status.py)
  const [tax, setTax] = useState({ pkp: false, pkp_since: '' });
  const [taxSaved, setTaxSaved] = useState({ pkp: false, pkp_since: '' });
  const [taxHistory, setTaxHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [uploading, setUploading] = useState(false);

  const canEdit = ['superadmin', 'admin'].includes(userRole);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetchSettings(); }, []);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/company-settings', { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (data && !data.error) {
        setSettings({
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
        });
        const tp = { pkp: !!data.tax_profile?.pkp, pkp_since: data.tax_profile?.pkp_since || '' };
        setTax(tp); setTaxSaved(tp);
        setTaxHistory(Array.isArray(data.tax_profile_history) ? data.tax_profile_history.slice(-5).reverse() : []);
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    const taxChanged = tax.pkp !== taxSaved.pkp || (tax.pkp && tax.pkp_since !== taxSaved.pkp_since);
    if (taxChanged && !window.confirm(tax.pkp
      ? `Ubah status pajak menjadi PKP sejak ${tax.pkp_since || '-'}?\n\nDokumen penjualan BARU akan memungut PPN 12% × DPP 11/12, dan PPN dari supplier dikreditkan. Dokumen lama tidak berubah.`
      : 'Ubah status pajak menjadi NON-PKP?\n\nDokumen penjualan BARU tidak memungut PPN, dan PPN dari supplier dicatat sebagai bagian harga beli. Dokumen lama tidak berubah.')) return;
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch('/api/company-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ...settings, tax_profile: tax }),
      });
      if (res.ok) {
        const data = await res.json();
        const tp = { pkp: !!data.tax_profile?.pkp, pkp_since: data.tax_profile?.pkp_since || '' };
        setTax(tp); setTaxSaved(tp);
        setTaxHistory(Array.isArray(data.tax_profile_history) ? data.tax_profile_history.slice(-5).reverse() : []);
        resetTaxProfileCache();
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } else {
        const data = await res.json().catch(() => ({}));
        alert(data.detail || data.error || 'Gagal menyimpan');
      }
    } catch (e) { alert('Gagal menyimpan: ' + e.message); }
    setSaving(false);
  };

  const handleLogoUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    // Validate file type and size
    if (!file.type.startsWith('image/')) {
      alert('Hanya file gambar yang diperbolehkan');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      alert('Ukuran file maksimal 2MB');
      return;
    }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      // 2026-11-06 (pola P1/P6): /api/upload membaca entity_type/entity_id dari query dan membalas
      // `storage_path` (bukan url/filepath/filename) — dulu logo tidak pernah terisi dan penolakan
      // server diam saja. Logo dipasang lewat /api/uploads/<path> (tanpa token, aman untuk <img>).
      const res = await fetch('/api/upload?entity_type=company_logo&entity_id=general', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.storage_path) throw new Error(data.detail || 'server menolak berkas');
      setSettings(s => ({ ...s, company_logo_url: `/api/uploads/${data.storage_path}` }));
    } catch (e) {
      alert('Gagal upload logo: ' + e.message);
    }
    setUploading(false);
  };

  const updateField = (field, value) => {
    setSettings(s => ({ ...s, [field]: value }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Pengaturan Perusahaan</h1>
          <p className="text-muted-foreground text-sm mt-1">Kelola informasi perusahaan untuk header PDF dan dokumen resmi</p>
        </div>
        {saved && (
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-2 text-sm text-emerald-700">
            <CheckCircle className="w-4 h-4" /> Berhasil disimpan!
          </div>
        )}
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Company Info */}
        <div className="bg-[var(--card-surface)] rounded-xl border border-border shadow-sm">
          <div className="flex items-center gap-2 px-5 py-4 border-b border-border">
            <Building2 className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Informasi Perusahaan</h3>
          </div>
          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="block text-sm font-medium text-foreground mb-1">Nama Perusahaan *</label>
                <input type="text" required disabled={!canEdit}
                  className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                  value={settings.company_name} onChange={e => updateField('company_name', e.target.value)}
                  placeholder="PT Garment Manufacturing" />
              </div>
              <div className="col-span-2">
                <label className="block text-sm font-medium text-foreground mb-1">Alamat</label>
                <textarea rows="2" disabled={!canEdit}
                  className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                  value={settings.company_address} onChange={e => updateField('company_address', e.target.value)}
                  placeholder="Jl. Industri No. 123, Jakarta" />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Telepon</label>
                <input type="text" disabled={!canEdit}
                  className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                  value={settings.company_phone} onChange={e => updateField('company_phone', e.target.value)}
                  placeholder="+62 21 1234567" />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Email</label>
                <input type="email" disabled={!canEdit}
                  className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                  value={settings.company_email} onChange={e => updateField('company_email', e.target.value)}
                  placeholder="info@company.com" />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">NPWP Perusahaan</label>
                <input type="text" disabled={!canEdit}
                  className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                  value={settings.npwp} onChange={e => updateField('npwp', e.target.value)}
                  placeholder="00.000.000.0-000.000" data-testid="company-npwp" />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Website</label>
                <input type="text" disabled={!canEdit}
                  className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                  value={settings.company_website} onChange={e => updateField('company_website', e.target.value)}
                  placeholder="www.company.com" />
              </div>
            </div>
          </div>
        </div>

        {/* Status Pajak — saklar PKP */}
        <div className="bg-[var(--card-surface)] rounded-xl border border-border shadow-sm" data-testid="company-tax-status">
          <div className="flex items-center gap-2 px-5 py-4 border-b border-border">
            <Receipt className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Status Pajak</h3>
          </div>
          <div className="p-5 space-y-4 text-sm">
            <div className="flex flex-wrap gap-3">
              {[{ v: false, t: 'Non-PKP', d: 'Tidak memungut PPN. PPN dari supplier masuk ke harga beli.' },
                { v: true, t: 'PKP', d: 'Memungut PPN 12% × DPP 11/12 (efektif 11%, kode 04). PPN supplier dikreditkan.' }].map(o => (
                <label key={o.t} className={`flex-1 min-w-[220px] cursor-pointer rounded-lg border px-4 py-3 ${tax.pkp === o.v ? 'border-primary bg-primary/5' : 'border-border'}`}>
                  <div className="flex items-center gap-2 font-medium">
                    <input type="radio" name="tax-status" disabled={!canEdit} checked={tax.pkp === o.v}
                      onChange={() => setTax(t => ({ ...t, pkp: o.v }))} data-testid={`tax-status-${o.v ? 'pkp' : 'nonpkp'}`} />
                    {o.t}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">{o.d}</p>
                </label>
              ))}
            </div>
            {tax.pkp && (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">PKP sejak *</label>
                  <input type="date" disabled={!canEdit} required
                    className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                    value={tax.pkp_since} onChange={e => setTax(t => ({ ...t, pkp_since: e.target.value }))} data-testid="tax-pkp-since" />
                  <p className="text-xs text-muted-foreground mt-1">Tanggal pengukuhan PKP dari KPP. NPWP wajib diisi.</p>
                </div>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Perubahan hanya berlaku untuk dokumen BARU. Faktur, nota, dan tagihan yang sudah dibuat tidak berubah.
            </p>
            {taxHistory.length > 0 && (
              <div className="text-xs text-muted-foreground border-t border-border pt-3 space-y-0.5">
                <div className="font-medium text-foreground">Riwayat perubahan</div>
                {taxHistory.map((h, i) => (
                  <div key={i}>{String(h.at || '').slice(0, 10)} · {h.by}: {h.from_pkp ? 'PKP' : 'Non-PKP'} → {h.to_pkp ? `PKP (sejak ${h.pkp_since})` : 'Non-PKP'}</div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Logo Upload */}
        <div className="bg-[var(--card-surface)] rounded-xl border border-border shadow-sm">
          <div className="flex items-center gap-2 px-5 py-4 border-b border-border">
            <Image className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Logo Perusahaan</h3>
          </div>
          <div className="p-5">
            <div className="flex items-start gap-6">
              <div className="w-32 h-32 border-2 border-dashed border-border rounded-xl flex items-center justify-center bg-[var(--glass-bg)] overflow-hidden flex-shrink-0">
                {settings.company_logo_url ? (
                  <img src={settings.company_logo_url} alt="Logo" className="w-full h-full object-contain p-2" />
                ) : (
                  <div className="text-center">
                    <Image className="w-8 h-8 text-muted-foreground mx-auto" />
                    <p className="text-xs text-muted-foreground mt-1">No Logo</p>
                  </div>
                )}
              </div>
              <div className="flex-1">
                {canEdit && (
                  <div>
                    <label className="flex items-center gap-2 px-4 py-2 bg-primary/10 border border-primary/20 rounded-lg text-sm text-primary cursor-pointer hover:bg-primary/15 w-fit">
                      <Upload className="w-4 h-4" />
                      {uploading ? 'Mengupload...' : 'Upload Logo'}
                      <input type="file" accept="image/*" className="hidden" onChange={handleLogoUpload} disabled={uploading} />
                    </label>
                    <p className="text-xs text-muted-foreground mt-2">Format: JPG, PNG, SVG. Maksimal 2MB.</p>
                  </div>
                )}
                <div className="mt-3">
                  <label className="block text-sm font-medium text-foreground mb-1">Atau masukkan URL Logo</label>
                  <input type="text" disabled={!canEdit}
                    className="w-full border border-border rounded-lg px-3 py-2 text-sm disabled:bg-[var(--glass-bg)]"
                    value={settings.company_logo_url} onChange={e => updateField('company_logo_url', e.target.value)}
                    placeholder="https://example.com/logo.png" />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* PDF Settings */}
        <div className="bg-[var(--card-surface)] rounded-xl border border-border shadow-sm">
          <div className="flex items-center gap-2 px-5 py-4 border-b border-border">
            <FileText className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-foreground">Pengaturan Header & Footer PDF</h3>
          </div>
          <div className="p-5 space-y-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Header Baris 1 (opsional)</label>
              <input type="text" disabled={!canEdit}
                className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                value={settings.pdf_header_line1} onChange={e => updateField('pdf_header_line1', e.target.value)}
                placeholder="Contoh: Divisi Produksi Garmen" />
              <p className="text-xs text-muted-foreground mt-1">Teks tambahan di bawah nama perusahaan pada header PDF</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Header Baris 2 (opsional)</label>
              <input type="text" disabled={!canEdit}
                className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                value={settings.pdf_header_line2} onChange={e => updateField('pdf_header_line2', e.target.value)}
                placeholder="Contoh: ISO 9001 Certified" />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">Footer PDF (opsional)</label>
              <input type="text" disabled={!canEdit}
                className="w-full border border-border rounded-lg px-3 py-2.5 text-sm disabled:bg-[var(--glass-bg)]"
                value={settings.pdf_footer_text} onChange={e => updateField('pdf_footer_text', e.target.value)}
                placeholder="Contoh: Dokumen ini dicetak secara otomatis oleh sistem" />
            </div>
          </div>
        </div>

        {/* PDF Preview */}
        <div className="bg-[var(--card-surface)] rounded-xl border border-border shadow-sm">
          <div className="px-5 py-4 border-b border-border">
            <h3 className="font-semibold text-foreground">Preview Header PDF</h3>
          </div>
          <div className="p-5">
            <div className="border-2 border-border rounded-lg p-6 bg-[var(--card-surface)] max-w-md mx-auto">
              <div className="text-center space-y-1">
                {settings.company_logo_url && (
                  <img src={settings.company_logo_url} alt="Logo" className="h-12 mx-auto mb-2 object-contain" />
                )}
                <p className="text-lg font-bold text-foreground">{settings.company_name || 'Nama Perusahaan'}</p>
                {settings.pdf_header_line1 && <p className="text-xs text-muted-foreground">{settings.pdf_header_line1}</p>}
                {settings.pdf_header_line2 && <p className="text-xs text-muted-foreground">{settings.pdf_header_line2}</p>}
                {settings.company_address && <p className="text-xs text-muted-foreground">{settings.company_address}</p>}
                {(settings.company_phone || settings.company_email) && (
                  <p className="text-xs text-muted-foreground">
                    {[settings.company_phone, settings.company_email].filter(Boolean).join(' | ')}
                  </p>
                )}
              </div>
              <div className="border-t-2 border-border mt-3 mb-2"></div>
              <p className="text-center text-sm font-bold text-muted-foreground">JUDUL DOKUMEN</p>
              <p className="text-center text-xs text-muted-foreground">No. Dokumen: XXX-001</p>
            </div>
          </div>
        </div>

        {canEdit && (
          <button type="submit" disabled={saving}
            className="flex items-center gap-2 px-6 py-3 bg-primary text-foreground rounded-xl text-sm font-medium hover:brightness-110 disabled:opacity-50 shadow-sm">
            <Save className="w-4 h-4" />
            {saving ? 'Menyimpan...' : 'Simpan Pengaturan'}
          </button>
        )}
      </form>
    </div>
  );
}
