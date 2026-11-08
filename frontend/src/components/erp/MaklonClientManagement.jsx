/**
 * MaklonClientManagement — tab "Klien" di menu Klien & Katalog Buyer (Portal Maklon).
 *
 * Tahap 9 (7 Nov 2026, keputusan owner "menu & tampilan dua portal identik"):
 *   • Cetakan PageLayout + tabel bisa dicari & berhalaman (dulu kartu 2 kolom + kartu angka warna-warni).
 *   • Standar UI/UX v2 (8 Nov 2026): rincian = popup (DetailPanel), klien baru/ubah = FormPopup panjang,
 *     akses portal klien = DetailPopup + form akun baru = FormPopup pendek (popup tidak bertumpuk), cari ± 16 rem.
 *   • Nonaktifkan/aktifkan dan aksi akun memakai confirmDialog.
 *
 *   - klien : GET/POST /api/dewi/maklon/clients · PUT /api/dewi/maklon/clients/{id}[/toggle]
 *   - portal: /api/dewi/maklon/clients/{id}/portal-status · provision-portal · portal-accounts/{acc}/…
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Copy, KeyRound, Pencil, Plus, Power, RefreshCw, Search, ShieldCheck, Trash2, Users, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup from '@/components/ui/detail-popup';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiGet, apiPost, apiPut, apiDelete } from '../../lib/api';
import { formatDateID, formatRupiah } from '@/lib/format';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import ImportExportToolbar from './ImportExportToolbar';

const PRODUCT_SPECIALIZATIONS = ['Rok', 'Blouse', 'Dress', 'Celana', 'Set/Setelan', 'Baju Anak', 'Hijab', 'Aksesoris', 'Lainnya'];
const TERMS = { net_7: '7 hari', net_14: '14 hari', net_30: '30 hari', net_60: '60 hari' };
const QUALITY = { standard: 'Standar', premium: 'Premium', luxury: 'Mewah' };
const EMPTY_FORM = {
  code: '', name: '', pic_name: '', pic_phone: '', pic_email: '', address: '', city: '',
  contract_type: 'per_order', standard_rate_per_pcs: '', payment_terms: 'net_30',
  product_specialization: [], quality_standard: 'standard', notes: '',
};
const isActive = (c) => c?.status !== 'inactive';
const ActiveBadge = ({ c }) => (
  <StatusBadge status={isActive(c) ? 'aktif' : 'nonaktif'} label={isActive(c) ? 'Aktif' : 'Nonaktif'} tone={isActive(c) ? 'success' : 'muted'} />
);

/** Isian standar; tanda * di label → `wajib`. */
function Field({ label, children, className = '' }) {
  const wajib = /\*\s*$/.test(label);
  return <Isian label={label.replace(/\s*\*\s*$/, '')} wajib={wajib} className={className}>{children}</Isian>;
}
function Info({ label, value, className = '' }) {
  return (
    <div className={`min-w-0 ${className}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm text-foreground break-words">{value || value === 0 ? value : '—'}</p>
    </div>
  );
}

// ── Form klien (baru / ubah) — FormPopup panjang ─────────────────────────────
function ClientForm({ data, onCancel, onSaved }) {
  const isEdit = !!data;
  const [form, setForm] = useState(() => ({ ...EMPTY_FORM, ...(data || {}),
    standard_rate_per_pcs: data?.standard_rate_per_pcs ?? '', product_specialization: data?.product_specialization || [] }));
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((p) => ({ ...p, [k]: e.target.value }));
  const toggleSpec = (s) => setForm((p) => ({ ...p, product_specialization: p.product_specialization.includes(s)
    ? p.product_specialization.filter((x) => x !== s) : [...p.product_specialization, s] }));

  const save = async () => {
    if (!String(form.code).trim() || !String(form.name).trim()) { toast.error('Kode dan nama klien wajib diisi'); return; }
    setSaving(true);
    const body = {
      code: String(form.code).trim(), name: String(form.name).trim(), pic_name: form.pic_name, pic_phone: form.pic_phone,
      pic_email: form.pic_email, address: form.address, city: form.city, contract_type: form.contract_type || 'per_order',
      standard_rate_per_pcs: Number(form.standard_rate_per_pcs || 0), payment_terms: form.payment_terms,
      product_specialization: form.product_specialization, quality_standard: form.quality_standard, notes: form.notes,
    };
    try {
      const r = isEdit ? await apiPut(`/dewi/maklon/clients/${data.id}`, body) : await apiPost('/dewi/maklon/clients', body);
      toast.success(isEdit ? `Klien ${body.name} diperbarui` : `Klien ${body.name} ditambahkan`);
      onSaved(isEdit ? data.id : r?.id);
    } catch (e) { toast.error(e.message || 'Gagal menyimpan'); }
    finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onCancel} ukuran="panjang" testId="maklon-client-form" onSimpan={save} menyimpan={saving}
      judul={isEdit ? `Ubah klien · ${data.name}` : 'Klien baru'}
      keterangan={isEdit ? 'Kode klien dipakai di nomor akun piutang & pendapatan klien.' : 'Akun piutang & pendapatan klien dibuat otomatis setelah disimpan.'}
      labelSimpan={isEdit ? 'Simpan perubahan' : 'Simpan klien'}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Kode klien *"><Input value={form.code} onChange={set('code')} placeholder="mis. KLN01" data-testid="client-form-code" /></Field>
        <Field label="Nama perusahaan / merek *"><Input value={form.name} onChange={set('name')} data-testid="client-form-name" /></Field>
        <Field label="Nama PIC"><Input value={form.pic_name} onChange={set('pic_name')} data-testid="client-form-pic" /></Field>
        <Field label="No. HP PIC"><Input value={form.pic_phone} onChange={set('pic_phone')} /></Field>
        <Field label="Email PIC"><Input type="email" value={form.pic_email} onChange={set('pic_email')} /></Field>
        <Field label="Kota"><Input value={form.city} onChange={set('city')} /></Field>
        <Field label="Alamat" className="sm:col-span-2"><Input value={form.address} onChange={set('address')} /></Field>
        <Field label="Tarif standar (Rp/pcs)"><MoneyInput value={form.standard_rate_per_pcs} onChange={set('standard_rate_per_pcs')} data-testid="client-form-rate" /></Field>
        <Field label="Termin pembayaran">
          <SmartNativeSelect value={form.payment_terms} onChange={set('payment_terms')} className="w-full h-9" searchable={false}
            data-testid="client-form-payment-terms" aria-label="Termin pembayaran">
            {Object.entries(TERMS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Field>
        <Field label="Standar kualitas">
          <SmartNativeSelect value={form.quality_standard} onChange={set('quality_standard')} className="w-full h-9" searchable={false}
            data-testid="client-form-quality" aria-label="Standar kualitas">
            {Object.entries(QUALITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SmartNativeSelect>
        </Field>
      </div>
      <Isian label="Spesialisasi produk">
        <div className="flex flex-wrap gap-x-4 gap-y-1.5" data-testid="client-form-spec">
          {PRODUCT_SPECIALIZATIONS.map((s) => (
            <label key={s} className="inline-flex cursor-pointer items-center gap-1.5 text-sm">
              <Checkbox checked={form.product_specialization.includes(s)} onCheckedChange={() => toggleSpec(s)} />{s}
            </label>
          ))}
        </div>
      </Isian>
      <Field label="Catatan"><Textarea rows={2} value={form.notes} onChange={set('notes')} data-testid="client-form-notes" /></Field>
    </FormPopup>
  );
}

// ── Rincian klien — popup (DetailPanel) ───────────────────────────────────────
function ClientDetail({ client, onClose, onEdit, onPortal, onChanged }) {
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    const off = isActive(client);
    if (!(await confirmDialog({
      title: off ? `Nonaktifkan klien ${client.name}?` : `Aktifkan lagi klien ${client.name}?`,
      body: off ? 'Klien nonaktif tidak bisa dipilih untuk PO maklon baru. Riwayat order dan piutangnya tetap ada.'
        : 'Klien bisa dipilih lagi untuk PO maklon baru.',
      confirmLabel: off ? 'Nonaktifkan' : 'Aktifkan', danger: off,
    }))) return;
    setBusy(true);
    try {
      await apiPut(`/dewi/maklon/clients/${client.id}/toggle`, {});
      toast.success(off ? `Klien ${client.name} dinonaktifkan` : `Klien ${client.name} diaktifkan`);
      await onChanged(client.id);
    } catch (e) { toast.error(e.message || 'Gagal mengubah status'); }
    finally { setBusy(false); }
  };
  return (
    <DetailPanel testId="maklon-client-detail" onClose={onClose}
      title={<span className="inline-flex items-center gap-2 flex-wrap">{client.name} <ActiveBadge c={client} /></span>}
      description={`${client.code || '—'} · ${client.city || 'Kota belum diisi'}`}
      actions={<>
        <Button variant="outline" onClick={onEdit} disabled={busy} data-testid={`maklon-client-edit-${client.id}`}><Pencil className="w-4 h-4" />Ubah</Button>
        <Button variant="outline" onClick={onPortal} disabled={busy} data-testid={`maklon-client-portal-${client.id}`}><KeyRound className="w-4 h-4" />Akses portal</Button>
        <Button variant="outline" onClick={toggle} disabled={busy} data-testid={`maklon-client-toggle-${client.id}`}>
          <Power className="w-4 h-4" />{isActive(client) ? 'Nonaktifkan' : 'Aktifkan'}
        </Button>
      </>}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Info label="PIC" value={client.pic_name} />
        <Info label="No. HP" value={client.pic_phone} />
        <Info label="Email" value={client.pic_email} />
        <Info label="Alamat" value={client.address} />
        <Info label="Tarif standar" value={`${formatRupiah(client.standard_rate_per_pcs || 0)}/pcs`} />
        <Info label="Termin pembayaran" value={TERMS[client.payment_terms] || client.payment_terms} />
        <Info label="Standar kualitas" value={QUALITY[client.quality_standard] || client.quality_standard} />
        <Info label="Penilaian" value={`${client.rating || 0} dari 5`} />
        <Info label="Spesialisasi" value={(client.product_specialization || []).join(', ')} className="col-span-2" />
        <Info label="Catatan" value={client.notes} className="col-span-2" />
      </div>
    </DetailPanel>
  );
}

// ── Akses portal klien — DetailPopup; akun baru = FormPopup pendek (menggantikan rincian sementara) ──
function PortalAccessDialog({ client, onClose }) {
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [provisionMode, setProvisionMode] = useState(false);
  const [email, setEmail] = useState(client.pic_email || '');
  const [picName, setPicName] = useState(client.pic_name || '');
  const [credential, setCredential] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { const d = await apiGet(`/dewi/maklon/clients/${client.id}/portal-status`); setAccounts(d?.accounts || []); }
    catch (e) { toast.error(e.message || 'Gagal memuat akun portal'); }
    finally { setLoading(false); }
  }, [client.id]);
  useEffect(() => { load(); }, [load]);

  const run = async (fn, okMsg) => {
    setBusy(true);
    try { const d = await fn(); if (okMsg) toast.success(okMsg); return d; }
    catch (e) { toast.error(e.message || 'Gagal'); return null; }
    finally { setBusy(false); }
  };
  const provision = async () => {
    if (!email.trim()) { toast.error('Email wajib diisi'); return; }
    const d = await run(() => apiPost(`/dewi/maklon/clients/${client.id}/provision-portal`, { email: email.trim(), name: picName }), 'Akun portal klien dibuat');
    if (d) { setCredential({ email: d.email, password: d.password }); setProvisionMode(false); load(); }
  };
  const reset = async (acc) => {
    if (!(await confirmDialog({ title: `Ganti sandi ${acc.email}?`, body: 'Sandi lama tidak berlaku lagi. Sandi baru ditampilkan sekali setelah ini.',
      confirmLabel: 'Ganti sandi' }))) return;
    const d = await run(() => apiPost(`/dewi/maklon/clients/${client.id}/portal-accounts/${acc.id}/reset-password`, {}), 'Sandi diganti');
    if (d) setCredential({ email: d.email, password: d.password });
  };
  const toggle = async (acc) => {
    const off = acc.status === 'active';
    if (!(await confirmDialog({ title: off ? `Nonaktifkan akun ${acc.email}?` : `Aktifkan lagi akun ${acc.email}?`,
      body: off ? 'Klien tidak bisa login dengan akun ini sampai diaktifkan lagi.' : 'Klien bisa login lagi dengan akun ini.',
      confirmLabel: off ? 'Nonaktifkan' : 'Aktifkan', danger: off }))) return;
    if (await run(() => apiPost(`/dewi/maklon/clients/${client.id}/portal-accounts/${acc.id}/toggle`, {}), 'Status akun diubah')) load();
  };
  const remove = async (acc) => {
    if (!(await confirmDialog({ title: `Hapus akun portal ${acc.email}?`, body: 'Klien tidak bisa login lagi dengan akun ini. Tindakan ini tidak bisa dibatalkan.',
      confirmLabel: 'Hapus akun', danger: true }))) return;
    if (await run(() => apiDelete(`/dewi/maklon/clients/${client.id}/portal-accounts/${acc.id}`), 'Akun dihapus')) load();
  };
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); toast.success('Disalin'); } catch { /* clipboard ditolak */ } };

  return (
    <>
      <DetailPopup open={!provisionMode} onClose={onClose} judul={`Akses portal klien · ${client.name}`} testId="maklon-portal-access-dialog"
        keterangan="Klien login di alamat /client untuk melihat status order, menyetujui sampel, dan melihat faktur."
        aksi={<Button size="sm" onClick={() => setProvisionMode(true)} data-testid="maklon-portal-provision-btn"><Plus className="w-4 h-4" />Akun portal baru</Button>}>
        {credential && (
          <Notice tone="success" icon={ShieldCheck} title="Data login hanya tampil sekali — catat sekarang" testId="maklon-portal-credential">
            <span className="flex items-center gap-2 text-sm">Email: <span className="font-semibold">{credential.email}</span>
              <Button size="icon-sm" variant="ghost" onClick={() => copy(credential.email)} title="Salin email" aria-label="Salin email"><Copy className="w-3 h-3" /></Button></span>
            <span className="flex items-center gap-2 text-sm">Sandi: <span className="font-semibold tabular-nums">{credential.password}</span>
              <Button size="icon-sm" variant="ghost" onClick={() => copy(credential.password)} title="Salin sandi" aria-label="Salin sandi"><Copy className="w-3 h-3" /></Button></span>
            <span className="block text-xs text-muted-foreground">Klien wajib mengganti sandi saat login pertama.</span>
          </Notice>
        )}
        {loading ? <p className="text-sm text-muted-foreground">Memuat akun…</p> : (
          <div className="divide-y divide-[var(--glass-border)]" data-testid="maklon-portal-accounts">
            {accounts.map((acc) => (
              <div key={acc.id} className="flex flex-wrap items-center justify-between gap-2 py-2" data-testid={`maklon-portal-account-${acc.id}`}>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{acc.email}</p>
                  <p className="text-xs text-muted-foreground">
                    {acc.status === 'active' ? 'Aktif' : 'Nonaktif'}{acc.must_change_password ? ' · wajib ganti sandi' : ''}
                    {acc.last_login_at ? ` · login terakhir ${formatDateID(acc.last_login_at)}` : ' · belum pernah login'}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="outline" onClick={() => reset(acc)} disabled={busy} data-testid={`maklon-portal-reset-${acc.id}`}>Ganti sandi</Button>
                  <Button size="sm" variant="outline" onClick={() => toggle(acc)} disabled={busy}>{acc.status === 'active' ? 'Nonaktifkan' : 'Aktifkan'}</Button>
                  <Button size="icon-sm" variant="ghost" onClick={() => remove(acc)} disabled={busy} title="Hapus akun" aria-label="Hapus akun"><Trash2 className="w-3.5 h-3.5" /></Button>
                </div>
              </div>
            ))}
            {!accounts.length && (
              <EmptyState icon={KeyRound} title="Belum ada akun portal untuk klien ini" className="py-6"
                description="Buat akun supaya klien bisa memantau order dan sampel sendiri." />
            )}
          </div>
        )}
      </DetailPopup>
      <FormPopup open={provisionMode} onClose={() => setProvisionMode(false)} ukuran="pendek" judul={`Akun portal baru · ${client.name}`}
        keterangan="Sandi dibuat otomatis dan ditampilkan setelah akun dibuat." onSimpan={provision} menyimpan={busy}
        labelSimpan="Buat akun" testId="maklon-portal-provision-form">
        <Field label="Email login *"><Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="klien@perusahaan.id" data-testid="maklon-portal-email-input" /></Field>
        <Field label="Nama PIC (opsional)"><Input value={picName} onChange={(e) => setPicName(e.target.value)} /></Field>
      </FormPopup>
    </>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
export default function MaklonClientManagement() {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [panel, setPanel] = useState(null); // null | {mode:'view'|'edit', id} | {mode:'new'}
  const [portalFor, setPortalFor] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const d = await apiGet('/dewi/maklon/clients'); setClients(Array.isArray(d) ? d : []); }
    catch (e) { setError(e.message || 'Gagal memuat data klien'); setClients([]); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => ({ all: clients.length, active: clients.filter(isActive).length,
    inactive: clients.filter((c) => !isActive(c)).length }), [clients]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return clients.filter((c) => (!status || (status === 'active' ? isActive(c) : !isActive(c)))
      && (!q || `${c.name} ${c.code} ${c.pic_name} ${c.city}`.toLowerCase().includes(q)));
  }, [clients, search, status]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const current = panel?.id ? clients.find((c) => c.id === panel.id) : null;
  const afterSave = async (id) => { await load(); setPanel(id ? { mode: 'view', id } : null); };

  let detail = null;
  if (panel?.mode === 'new') detail = <ClientForm onCancel={() => setPanel(null)} onSaved={afterSave} />;
  else if (panel?.mode === 'edit' && current) detail = <ClientForm data={current} onCancel={() => setPanel({ mode: 'view', id: current.id })} onSaved={afterSave} />;
  else if (panel?.mode === 'view' && current) {
    detail = <ClientDetail client={current} onClose={() => setPanel(null)} onEdit={() => setPanel({ mode: 'edit', id: current.id })}
      onPortal={() => setPortalFor(current)} onChanged={afterSave} />;
  }

  return (
    <PageLayout testId="maklon-clients" title="Klien maklon" subtitle="Data klien jasa maklon: kontak, tarif standar, termin, dan akses portal klien."
      actions={<Button onClick={() => setPanel({ mode: 'new' })} data-testid="maklon-client-add"><Plus className="w-4 h-4" />Klien baru</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama, kode, PIC, kota" className="pl-8"
            data-testid="maklon-client-search" />
        </div>
        <FilterChips value={status} onChange={setStatus} testId="maklon-client-status" ariaLabel="Status klien"
          options={[{ key: '', label: 'Semua', count: counts.all }, { key: 'active', label: 'Aktif', count: counts.active },
            { key: 'inactive', label: 'Nonaktif', count: counts.inactive }]} />
      </>}
      tools={<>
        <ImportExportToolbar collectionKey="maklon_clients" label="Klien Maklon" onImported={load} />
        <Button size="icon" variant="outline" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="maklon-client-refresh">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={error && <Notice tone="danger" title="Gagal memuat data klien">{error}</Notice>}
      detail={portalFor ? null : detail /* akses portal menggantikan popup rincian sementara (tidak bertumpuk) */}
      footer={filtered.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      <GlassCard className="p-0 overflow-hidden">
        {loading && !clients.length ? (
          <div className="p-4 text-sm text-muted-foreground">Memuat klien…</div>
        ) : !paged.length ? (
          <EmptyState icon={Users} title={clients.length ? 'Tidak ada klien yang cocok' : 'Belum ada klien terdaftar'}
            description={clients.length ? 'Ubah kata pencarian atau penyaring status.' : 'Klik Klien baru untuk menambahkan klien maklon pertama.'}
            action={clients.length && (search || status) ? <Button variant="outline" size="sm" onClick={() => { setSearch(''); setStatus(''); }}><X className="w-3.5 h-3.5" />Tampilkan semua</Button> : null} />
        ) : (
          <Table data-testid="maklon-client-table">
            <TableHeader><TableRow>
              <TableHead>Klien</TableHead><TableHead>PIC</TableHead><TableHead>Kota</TableHead>
              <TableHead className="text-right">Tarif standar</TableHead><TableHead>Termin</TableHead>
              <TableHead>Kualitas</TableHead><TableHead>Status</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {paged.map((c) => (
                <TableRow key={c.id} data-testid={`maklon-client-row-${c.id}`} className={panel?.id === c.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell>
                    <Button variant="link" size="sm" className="h-auto p-0 font-semibold text-left" onClick={() => setPanel({ mode: 'view', id: c.id })}
                      data-testid={`maklon-client-view-${c.id}`}>{c.name}</Button>
                    <span className="block text-xs text-muted-foreground">{c.code}</span>
                  </TableCell>
                  <TableCell className="text-sm">{c.pic_name || '—'}{c.pic_phone ? <span className="block text-xs text-muted-foreground">{c.pic_phone}</span> : null}</TableCell>
                  <TableCell className="text-sm">{c.city || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{formatRupiah(c.standard_rate_per_pcs || 0)}</TableCell>
                  <TableCell className="text-sm">{TERMS[c.payment_terms || 'net_30'] || c.payment_terms}</TableCell>
                  <TableCell className="text-sm">{QUALITY[c.quality_standard] || c.quality_standard || '—'}</TableCell>
                  <TableCell><ActiveBadge c={c} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {portalFor && <PortalAccessDialog client={portalFor} onClose={() => setPortalFor(null)} />}
    </PageLayout>
  );
}
