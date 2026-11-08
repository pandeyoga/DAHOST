/**
 * VendorAccountsAdminModule — menu "Vendor CMT" (Portal Produksi & Maklon, satu layar yang sama).
 *
 * Tahap 9 (7 Nov 2026, keputusan owner "menu & tampilan dua portal identik"):
 *   • Cetakan PageLayout + tabel bisa dicari & berhalaman; detail/ubah vendor DI HALAMAN (DetailPanel).
 *     Dialog hanya untuk form singkat "Vendor baru" / "Akun baru".
 *   • Tab: Vendor · Akun vendor. Tab "Semua job" DIHAPUS — model lama `vendor_jobs` tidak tersambung ke
 *     PO, kiriman, maupun tagihan (backend kini menolak tulisnya, 410).
 *   • Perbaikan: catatan vendor dulu TERHAPUS setiap kali vendor diubah (form tidak mengirim `notes`,
 *     server menimpa dengan ''). Kini catatan tampil & bisa diubah, dan PUT hanya mengirim isian yang
 *     berubah (server memperbarui sebagian).
 *   • Hapus & nonaktifkan memakai confirmDialog.
 *
 *   - vendor : GET/POST /api/vendor-portal/partners · PUT/DELETE /api/vendor-portal/partners/{id}[?hard=true]
 *   - akun   : GET/POST /api/vendor-portal/accounts · PUT/DELETE /api/vendor-portal/accounts/{id}[?hard=true]
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Building2, KeyRound, Pencil, Plus, Power, RefreshCw, Search, Trash2, Users, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import FormPopup from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Input } from '@/components/ui/input';
import { apiDelete, apiGet, apiPost, apiPut } from '../../lib/api';
import { formatDateTimeID } from '@/lib/format';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { PageLayoutSatuBaris } from './engine/DataTable';
import HubTabs from './hubs/HubTabs';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import ImportExportToolbar from './ImportExportToolbar';

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');
const OWNER_LABEL = { '': 'Vendor CMT luar', SMU: 'Tim jahit CV Sukma' };
const isActive = (r) => r?.is_active !== false;
const ActiveBadge = ({ row, testId }) => (
  <StatusBadge status={isActive(row) ? 'aktif' : 'nonaktif'} label={isActive(row) ? 'Aktif' : 'Nonaktif'}
    tone={isActive(row) ? 'success' : 'muted'} testId={testId} />
);

function Field({ label, children, hint, className = '' }) {
  return (
    <label className={`block space-y-1 ${className}`}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

function Info({ label, value, testId }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm text-foreground break-words" data-testid={testId}>{value || '—'}</p>
    </div>
  );
}

function SearchBox({ value, onChange, placeholder, testId }) {
  return (
    <div className="relative w-full sm:w-64">
      <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="pl-8" data-testid={testId} />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab Vendor
// ══════════════════════════════════════════════════════════════════════════════
const PARTNER_EDIT_KEYS = ['name', 'code', 'contact_name', 'contact_phone', 'address', 'capacity_pcs', 'capacity_note',
  'owner_entity', 'notes'];
const partnerForm = (p = {}) => ({
  name: p.name || '', code: p.code || '', contact_name: p.contact_name || '', contact_phone: p.contact_phone || '',
  address: p.address || '', capacity_pcs: p.capacity_pcs === 0 || p.capacity_pcs ? String(p.capacity_pcs) : '',
  capacity_note: p.capacity_note || '', owner_entity: p.owner_entity || '', notes: p.notes || '',
});
const normPartner = (f) => ({ ...f, capacity_pcs: f.capacity_pcs === '' ? null : Number(f.capacity_pcs) });

/** Isian yang berubah saja — PUT diperbarui SEBAGIAN (Tahap 9: catatan tidak terhapus). */
export function changedPartnerFields(original, form) {
  const a = normPartner(partnerForm(original));
  const b = normPartner(form);
  const out = {};
  PARTNER_EDIT_KEYS.forEach((k) => { if ((a[k] ?? null) !== (b[k] ?? null)) out[k] = b[k]; });
  if ('capacity_pcs' in out && out.capacity_pcs === null) delete out.capacity_pcs;
  return out;
}

function PartnerFormFields({ form, setForm, full = true }) {
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <Field label="Nama vendor *"><GlassInput value={form.name} onChange={set('name')} data-testid="partner-name" /></Field>
      <Field label="Kode (opsional)"><GlassInput value={form.code} onChange={set('code')} data-testid="partner-code" /></Field>
      <Field label="Nama kontak"><GlassInput value={form.contact_name} onChange={set('contact_name')} data-testid="partner-contact_name" /></Field>
      <Field label="No. HP"><GlassInput type="tel" value={form.contact_phone} onChange={set('contact_phone')} data-testid="partner-contact_phone" /></Field>
      <Field label="Pemilik penjahit" className="sm:col-span-2"
        hint="Tim jahit CV Sukma: jahitan PO internal ditagih CV Sukma ke CV Dewi Aditya (antar CV); PO maklon tanpa tagihan CMT.">
        <SmartNativeSelect value={form.owner_entity} onChange={set('owner_entity')} className="w-full h-9"
          data-testid="partner-owner_entity" aria-label="Pemilik penjahit">
          <option value="">Vendor CMT luar</option>
          <option value="SMU">Tim jahit CV Sukma</option>
        </SmartNativeSelect>
      </Field>
      {full && (
        <>
          <Field label="Alamat" className="sm:col-span-2"><GlassInput value={form.address} onChange={set('address')} data-testid="partner-address" /></Field>
          <Field label="Kapasitas jahit (pcs)" hint="Maksimum pcs yang bisa ditangani pada satu waktu (dipakai pantau beban vs kapasitas).">
            <GlassInput type="number" min="0" value={form.capacity_pcs} onChange={set('capacity_pcs')} placeholder="mis. 200"
              data-testid="partner-capacity_pcs" />
          </Field>
          <Field label="Catatan kapasitas">
            <GlassInput value={form.capacity_note} onChange={set('capacity_note')} placeholder="mis. 2 lini jahit, kuat hoodie"
              data-testid="partner-capacity_note" />
          </Field>
          <Field label="Catatan" className="sm:col-span-2">
            <Textarea rows={3} value={form.notes} onChange={set('notes')} placeholder="Catatan internal tentang vendor ini"
              data-testid="partner-notes" />
          </Field>
        </>
      )}
    </div>
  );
}

function PartnerDetail({ partner, onClose, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(() => partnerForm(partner));
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm(partnerForm(partner)); setEditing(false); }, [partner]);

  const save = async () => {
    if (!form.name.trim()) { toast.error('Nama vendor wajib diisi'); return; }
    const body = changedPartnerFields(partner, form);
    if (!Object.keys(body).length) { setEditing(false); return; }
    setBusy(true);
    try {
      await apiPut(`/vendor-portal/partners/${partner.id}`, body);
      toast.success(`Vendor "${form.name}" diperbarui`);
      setEditing(false);
      await onChanged(partner.id);
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setBusy(false); }
  };

  const toggle = async () => {
    const off = isActive(partner);
    const ok = await confirmDialog({
      title: off ? `Nonaktifkan vendor "${partner.name}"?` : `Aktifkan lagi vendor "${partner.name}"?`,
      body: off ? 'Vendor nonaktif tidak bisa dipilih untuk PO dan Input atas nama CMT. Riwayatnya tetap ada. '
        + 'Ditolak bila vendor masih punya akun aktif atau job berjalan.' : 'Vendor bisa dipilih lagi untuk PO baru.',
      confirmLabel: off ? 'Nonaktifkan' : 'Aktifkan', danger: off,
    });
    if (!ok) return;
    setBusy(true);
    try {
      if (off) await apiDelete(`/vendor-portal/partners/${partner.id}`);
      else await apiPut(`/vendor-portal/partners/${partner.id}`, { is_active: true });
      toast.success(off ? `Vendor "${partner.name}" dinonaktifkan` : `Vendor "${partner.name}" diaktifkan`);
      await onChanged(partner.id);
    } catch (e) { toast.error(e.message || 'Gagal'); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    const ok = await confirmDialog({
      title: `Hapus vendor "${partner.name}" permanen?`,
      body: 'Hanya bisa bila vendor belum pernah dipakai (tanpa PO, job, kiriman, dan akun login). Tindakan ini tidak bisa dibatalkan — '
        + 'untuk sekadar berhenti memakai vendor, pilih Nonaktifkan.',
      confirmLabel: 'Hapus permanen', danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await apiDelete(`/vendor-portal/partners/${partner.id}?hard=true`);
      toast.success(`Vendor "${partner.name}" dihapus`);
      onClose();
      await onChanged(null);
    } catch (e) { toast.error(e.message || 'Gagal menghapus'); }
    finally { setBusy(false); }
  };

  return (
    <DetailPanel testId="partner-detail" closeTestId="partner-detail-close" onClose={onClose}
      title={<span className="inline-flex items-center gap-2 flex-wrap">{partner.name} <ActiveBadge row={partner} testId="partner-detail-status" /></span>}
      description={`${partner.code || 'Tanpa kode'} · ${OWNER_LABEL[partner.owner_entity || ''] || 'Vendor CMT luar'}`}
      actions={!editing && (
        <>
          <Button type="button" variant="outline" onClick={() => setEditing(true)} disabled={busy} data-testid="partner-edit"><Pencil className="w-4 h-4" />Ubah</Button>
          <Button type="button" variant="outline" onClick={toggle} disabled={busy} data-testid="partner-toggle">
            <Power className="w-4 h-4" />{isActive(partner) ? 'Nonaktifkan' : 'Aktifkan'}
          </Button>
          <Button type="button" variant="outline" size="icon" onClick={remove} disabled={busy} title="Hapus permanen" aria-label="Hapus permanen"
            data-testid="partner-delete"><Trash2 className="w-4 h-4" /></Button>
        </>
      )}>
      {editing ? (
        <div className="space-y-3" data-testid="partner-form">
          <PartnerFormFields form={form} setForm={setForm} />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => { setForm(partnerForm(partner)); setEditing(false); }} disabled={busy}>Batal</Button>
            <Button type="button" onClick={save} disabled={busy} data-testid="partner-save">Simpan perubahan</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Info label="Kontak" value={partner.contact_name} />
            <Info label="No. HP" value={partner.contact_phone} />
            <Info label="Kapasitas jahit" value={partner.capacity_pcs > 0 ? `${fmtNum(partner.capacity_pcs)} pcs` : 'Belum diisi'} />
            <Info label="Dipakai" value={`${fmtNum(partner.po_count)} PO · ${fmtNum(partner.active_job_count)} job berjalan · ${fmtNum(partner.account_count)} akun`} />
            <Info label="Alamat" value={partner.address} />
            <Info label="Catatan kapasitas" value={partner.capacity_note} />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Catatan</p>
            <p className="text-sm text-foreground whitespace-pre-wrap" data-testid="partner-detail-notes">{partner.notes || '—'}</p>
          </div>
        </div>
      )}
    </DetailPanel>
  );
}

function NewPartnerDialog({ onClose, onCreated }) {
  const [form, setForm] = useState(() => partnerForm());
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!form.name.trim()) { toast.error('Nama vendor wajib diisi'); return; }
    setBusy(true);
    try {
      const r = await apiPost('/vendor-portal/partners', {
        name: form.name.trim(), code: form.code.trim(), contact_name: form.contact_name, contact_phone: form.contact_phone,
        owner_entity: form.owner_entity,
      });
      toast.success(`Vendor "${form.name}" dibuat`);
      onCreated(r?.id);
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setBusy(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="partner-create-dialog" judul="Vendor baru"
      keterangan="Alamat, kapasitas, dan catatan bisa dilengkapi dari rincian vendor setelah disimpan."
      onSimpan={save} menyimpan={busy}>
      <PartnerFormFields form={form} setForm={setForm} full={false} />
    </FormPopup>
  );
}

export function VendorPartnersTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const d = await apiGet('/vendor-portal/partners'); setRows(Array.isArray(d) ? d : []); }
    catch (e) { setError(e.message || 'Gagal memuat vendor'); setRows([]); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => ({
    all: rows.length, active: rows.filter(isActive).length, inactive: rows.filter((r) => !isActive(r)).length,
  }), [rows]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => (!status || (status === 'active' ? isActive(r) : !isActive(r)))
      && (!q || `${r.name} ${r.code} ${r.contact_name} ${r.contact_phone}`.toLowerCase().includes(q)));
  }, [rows, search, status]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const selected = rows.find((r) => r.id === selectedId) || null;
  const afterChange = async (id) => { await load(); setSelectedId(id); };
  const resetFilters = () => { setSearch(''); setStatus(''); };

  return (
    <PageLayoutSatuBaris testId="vendor-partners-tab" title="Vendor CMT" subtitle="Daftar penjahit (CMT) beserta kontak, kapasitas, dan catatan."
      actions={<Button type="button" onClick={() => setCreating(true)} data-testid="btn-add-partner"><Plus className="w-4 h-4" />Vendor baru</Button>}
      filters={<>
        <SearchBox value={search} onChange={setSearch} placeholder="Cari nama / kode / kontak…" testId="partner-search" />
        <FilterChips value={status} onChange={setStatus} testId="partner-status-filter" ariaLabel="Status vendor"
          options={[{ key: '', label: 'Semua', count: counts.all }, { key: 'active', label: 'Aktif', count: counts.active },
            { key: 'inactive', label: 'Nonaktif', count: counts.inactive }]} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas="vendor-cmt" namaLembar="Vendor" baris={filtered} testId="partner-unduh" kolom={[
          { label: 'Vendor', nilai: (p) => p.name || '' }, { label: 'Kode', nilai: (p) => p.code || '' },
          { label: 'Kontak', nilai: (p) => p.contact_name || '' }, { label: 'Telepon', nilai: (p) => p.contact_phone || '' },
          { label: 'Kapasitas (pcs)', nilai: (p) => (p.capacity_pcs > 0 ? Number(p.capacity_pcs) : '') },
          { label: 'PO', nilai: (p) => Number(p.po_count) || 0 }, { label: 'Job berjalan', nilai: (p) => Number(p.active_job_count) || 0 },
          { label: 'Akun', nilai: (p) => Number(p.account_count) || 0 }, { label: 'Pemilik', nilai: (p) => OWNER_LABEL[p.owner_entity || ''] || '' },
          { label: 'Status', nilai: (p) => (isActive(p) ? 'Aktif' : 'Nonaktif') }, { label: 'Catatan', nilai: (p) => p.notes || '' },
        ]} />
        <ImportExportToolbar collectionKey="vendor_partners" label="Vendor CMT" onImported={load} />
        <Button type="button" variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="partner-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={error && <Notice tone="danger" title="Gagal memuat vendor" testId="partner-error">{error}</Notice>}
      detail={selected && <PartnerDetail partner={selected} onClose={() => setSelectedId(null)} onChanged={afterChange} />}
      footer={filtered.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat vendor…</div>
        ) : (
          <Table data-testid="partners-list">
            <TableHeader><TableRow>
              <TableHead>Vendor</TableHead><TableHead>Kode</TableHead><TableHead>Kontak</TableHead>
              <TableHead className="text-right">Kapasitas (pcs)</TableHead><TableHead className="text-right">PO</TableHead>
              <TableHead className="text-right">Job berjalan</TableHead><TableHead className="text-right">Akun</TableHead>
              <TableHead>Pemilik</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {!paged.length && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={9} className="p-0 [&>div]:py-8">
                    {rows.length ? (
                      <EmptyState icon={Building2} title="Tidak ada vendor yang cocok" description="Ubah kata pencarian atau penyaring status."
                        action={<Button type="button" variant="outline" size="sm" onClick={resetFilters}><X className="w-3.5 h-3.5" />Tampilkan semua vendor</Button>} />
                    ) : (
                      <EmptyState icon={Building2} title="Belum ada vendor CMT" description="Klik Vendor baru untuk mendaftarkan penjahit pertama." />
                    )}
                  </TableCell>
                </TableRow>
              )}
              {paged.map((p) => (
                <TableRow key={p.id} data-testid={`partner-row-${p.id}`} className={selectedId === p.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell>
                    <Button type="button" variant="link" size="sm" className="h-auto p-0 font-semibold text-left" onClick={() => setSelectedId(p.id)}
                      data-testid={`partner-open-${p.id}`}>{p.name}</Button>
                    {p.notes && <span className="block text-xs text-muted-foreground truncate max-w-[16rem]" title={p.notes}>{p.notes}</span>}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{p.code || '—'}</TableCell>
                  <TableCell className="text-sm">{p.contact_name || '—'}{p.contact_phone ? <span className="block text-xs text-muted-foreground">{p.contact_phone}</span> : null}</TableCell>
                  <TableCell className="text-right tabular-nums">{p.capacity_pcs > 0 ? fmtNum(p.capacity_pcs) : '—'}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(p.po_count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(p.active_job_count)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNum(p.account_count)}</TableCell>
                  <TableCell className="text-xs" data-testid={`partner-owner-${p.id}`}>{OWNER_LABEL[p.owner_entity || ''] || '—'}</TableCell>
                  <TableCell><ActiveBadge row={p} testId={`partner-status-${p.id}`} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {creating && <NewPartnerDialog onClose={() => setCreating(false)} onCreated={async (id) => { setCreating(false); await afterChange(id || null); }} />}
    </PageLayoutSatuBaris>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Tab Akun vendor
// ══════════════════════════════════════════════════════════════════════════════
function AccountDetail({ account, partners, onClose, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: account.name || '', partner_id: account.cmt_vendor_id || '', password: '' });
  const [busy, setBusy] = useState(false);
  useEffect(() => { setForm({ name: account.name || '', partner_id: account.cmt_vendor_id || '', password: '' }); setEditing(false); }, [account]);

  const save = async () => {
    if (!form.name.trim()) { toast.error('Nama wajib diisi'); return; }
    if (form.password && form.password.length < 6) { toast.error('Sandi minimal 6 karakter'); return; }
    const body = {};
    if (form.name.trim() !== (account.name || '')) body.name = form.name.trim();
    if (form.partner_id && form.partner_id !== (account.cmt_vendor_id || '')) body.partner_id = form.partner_id;
    if (form.password) body.password = form.password;
    if (!Object.keys(body).length) { setEditing(false); return; }
    setBusy(true);
    try {
      const r = await apiPut(`/vendor-portal/accounts/${account.id}`, body);
      toast.success(r?.password_reset ? 'Akun diperbarui dan sandi diganti' : 'Akun diperbarui');
      setEditing(false);
      await onChanged(account.id);
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setBusy(false); }
  };
  const toggle = async () => {
    const off = isActive(account);
    if (!(await confirmDialog({
      title: off ? `Nonaktifkan akun ${account.email}?` : `Aktifkan lagi akun ${account.email}?`,
      body: off ? 'Akun tidak bisa login ke Portal Vendor sampai diaktifkan lagi.' : 'Akun bisa login lagi ke Portal Vendor.',
      confirmLabel: off ? 'Nonaktifkan' : 'Aktifkan', danger: off,
    }))) return;
    setBusy(true);
    try {
      await apiPut(`/vendor-portal/accounts/${account.id}`, { is_active: !off });
      toast.success(off ? 'Akun dinonaktifkan' : 'Akun diaktifkan');
      await onChanged(account.id);
    } catch (e) { toast.error(e.message || 'Gagal'); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!(await confirmDialog({
      title: `Hapus akun ${account.email} permanen?`,
      body: 'Akun dihapus dan tidak bisa login lagi. Tindakan ini tidak bisa dibatalkan.',
      confirmLabel: 'Hapus permanen', danger: true,
    }))) return;
    setBusy(true);
    try {
      await apiDelete(`/vendor-portal/accounts/${account.id}?hard=true`);
      toast.success('Akun dihapus');
      onClose();
      await onChanged(null);
    } catch (e) { toast.error(e.message || 'Gagal menghapus'); }
    finally { setBusy(false); }
  };

  return (
    <DetailPanel testId="account-detail" onClose={onClose}
      title={<span className="inline-flex items-center gap-2 flex-wrap">{account.name} <ActiveBadge row={account} /></span>}
      description={`${account.email} · ${account.partner_name || 'Vendor belum dipilih'}`}
      actions={!editing && (
        <>
          <Button type="button" variant="outline" onClick={() => setEditing(true)} disabled={busy} data-testid="account-edit"><Pencil className="w-4 h-4" />Ubah</Button>
          <Button type="button" variant="outline" onClick={toggle} disabled={busy} data-testid="account-toggle">
            <Power className="w-4 h-4" />{isActive(account) ? 'Nonaktifkan' : 'Aktifkan'}
          </Button>
          <Button type="button" variant="outline" size="icon" onClick={remove} disabled={busy} title="Hapus akun" aria-label="Hapus akun"
            data-testid="account-delete"><Trash2 className="w-4 h-4" /></Button>
        </>
      )}>
      {editing ? (
        <div className="space-y-3" data-testid="account-edit-form">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Field label="Nama lengkap *"><GlassInput value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} data-testid="account-edit-name" /></Field>
            <Field label="Vendor">
              <SmartNativeSelect value={form.partner_id} onChange={(e) => setForm((f) => ({ ...f, partner_id: e.target.value }))}
                className="w-full h-9" data-testid="account-edit-partner" aria-label="Vendor">
                <option value="">— Pilih vendor —</option>
                {partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </SmartNativeSelect>
            </Field>
            <Field label="Sandi baru (opsional)" hint="Kosongkan bila sandi tidak diganti.">
              <GlassInput type="password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                data-testid="account-edit-password" />
            </Field>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setEditing(false)} disabled={busy}>Batal</Button>
            <Button type="button" onClick={save} disabled={busy} data-testid="account-edit-save">Simpan perubahan</Button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Info label="Email login" value={account.email} />
          <Info label="Vendor" value={account.partner_name} />
          <Info label="Login terakhir" value={account.last_login_at ? formatDateTimeID(account.last_login_at) : 'Belum pernah'} />
          <Info label="Dibuat" value={account.created_at ? formatDateTimeID(account.created_at) : '—'} />
        </div>
      )}
    </DetailPanel>
  );
}

function NewAccountDialog({ partners, onClose, onCreated }) {
  const [form, setForm] = useState({ partner_id: '', name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const save = async () => {
    if (!form.partner_id || !form.name.trim() || !form.email.trim() || !form.password) { toast.error('Semua isian wajib diisi'); return; }
    setBusy(true);
    try {
      const r = await apiPost('/vendor-portal/accounts', form);
      toast.success(`Akun ${form.email} dibuat`);
      onCreated(r?.id);
    } catch (e) { toast.error(e.message || 'Gagal membuat akun'); }
    finally { setBusy(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="account-form" judul="Akun vendor baru"
      onSimpan={save} menyimpan={busy} labelSimpan="Buat akun">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Vendor *" className="sm:col-span-2">
            <SmartNativeSelect value={form.partner_id} onChange={set('partner_id')} className="w-full h-9"
              data-testid="account-partner-select" aria-label="Vendor">
              <option value="">— Pilih vendor —</option>
              {partners.filter(isActive).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </SmartNativeSelect>
          </Field>
          <Field label="Nama lengkap *"><GlassInput value={form.name} onChange={set('name')} data-testid="account-name" /></Field>
          <Field label="Email login *"><GlassInput value={form.email} onChange={set('email')} data-testid="account-email" /></Field>
          <Field label="Sandi *" className="sm:col-span-2"><GlassInput type="password" value={form.password} onChange={set('password')} data-testid="account-password" /></Field>
        </div>
    </FormPopup>
  );
}

export function VendorAccountsTab() {
  const [rows, setRows] = useState([]);
  const [partners, setPartners] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [partnerId, setPartnerId] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [acc, par] = await Promise.all([apiGet('/vendor-portal/accounts'), apiGet('/vendor-portal/partners')]);
      setRows(Array.isArray(acc) ? acc : []); setPartners(Array.isArray(par) ? par : []);
    } catch (e) { setError(e.message || 'Gagal memuat akun vendor'); setRows([]); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => ({
    all: rows.length, active: rows.filter(isActive).length, inactive: rows.filter((r) => !isActive(r)).length,
  }), [rows]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => (!status || (status === 'active' ? isActive(r) : !isActive(r)))
      && (!partnerId || r.cmt_vendor_id === partnerId)
      && (!q || `${r.name} ${r.email} ${r.partner_name}`.toLowerCase().includes(q)));
  }, [rows, search, status, partnerId]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const selected = rows.find((r) => r.id === selectedId) || null;
  const afterChange = async (id) => { await load(); setSelectedId(id); };

  return (
    <PageLayoutSatuBaris testId="vendor-accounts-tab" title="Akun vendor" subtitle="Login Portal Vendor untuk penjahit yang mengisi sendiri."
      actions={<Button type="button" onClick={() => setCreating(true)} data-testid="btn-add-account"><Plus className="w-4 h-4" />Akun baru</Button>}
      filters={<>
        <SearchBox value={search} onChange={setSearch} placeholder="Cari nama / email / vendor…" testId="account-search" />
        <FilterChips value={status} onChange={setStatus} testId="account-status-filter" ariaLabel="Status akun"
          options={[{ key: '', label: 'Semua', count: counts.all }, { key: 'active', label: 'Aktif', count: counts.active },
            { key: 'inactive', label: 'Nonaktif', count: counts.inactive }]} />
        {partners.length > 0 && (
          <SmartNativeSelect value={partnerId} onChange={(e) => setPartnerId(e.target.value)} className="h-9 w-64 max-w-full"
            data-testid="account-partner-filter" aria-label="Vendor">
            <option value="">Semua vendor</option>
            {partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </SmartNativeSelect>
        )}
      </>}
      tools={<>
        <TombolUnduh namaBerkas="akun-vendor-cmt" namaLembar="Akun" baris={filtered} testId="account-unduh" kolom={[
          { label: 'Nama', nilai: (u) => u.name || '' }, { label: 'Email login', nilai: (u) => u.email || '' },
          { label: 'Vendor', nilai: (u) => u.partner_name || '' },
          { label: 'Login terakhir', nilai: (u) => (u.last_login_at ? formatDateTimeID(u.last_login_at) : 'Belum pernah') },
          { label: 'Status', nilai: (u) => (isActive(u) ? 'Aktif' : 'Nonaktif') },
        ]} />
        <Button type="button" variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="account-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={error && <Notice tone="danger" title="Gagal memuat akun vendor">{error}</Notice>}
      detail={selected && <AccountDetail account={selected} partners={partners} onClose={() => setSelectedId(null)} onChanged={afterChange} />}
      footer={filtered.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !rows.length ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat akun…</div>
        ) : (
          <Table data-testid="accounts-list">
            <TableHeader><TableRow>
              <TableHead>Nama</TableHead><TableHead>Email login</TableHead><TableHead>Vendor</TableHead>
              <TableHead>Login terakhir</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {!paged.length && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={5} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Users} title={rows.length ? 'Tidak ada akun yang cocok' : 'Belum ada akun vendor'}
                      description={rows.length ? 'Ubah kata pencarian atau penyaring.' : 'Klik Akun baru untuk membuat login Portal Vendor.'} />
                  </TableCell>
                </TableRow>
              )}
              {paged.map((u) => (
                <TableRow key={u.id} data-testid={`account-row-${u.id}`} className={selectedId === u.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell>
                    <Button type="button" variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => setSelectedId(u.id)}
                      data-testid={`account-open-${u.id}`}>{u.name}</Button>
                  </TableCell>
                  <TableCell className="text-sm">{u.email}</TableCell>
                  <TableCell className="text-sm">{u.partner_name || '—'}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{u.last_login_at ? formatDateTimeID(u.last_login_at) : 'Belum pernah'}</TableCell>
                  <TableCell><ActiveBadge row={u} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {creating && <NewAccountDialog partners={partners} onClose={() => setCreating(false)}
        onCreated={async (id) => { setCreating(false); await afterChange(id || null); }} />}
    </PageLayoutSatuBaris>
  );
}

export default function VendorAccountsAdminModule(props) {
  return (
    <HubTabs hubId="vendor-admin" title="Vendor CMT" compactHeaders
      tabs={[
        { key: 'vendor', label: 'Vendor', Component: VendorPartnersTab },
        { key: 'akun', label: 'Akun vendor', Component: VendorAccountsTab },
      ]}
      {...props} />
  );
}
