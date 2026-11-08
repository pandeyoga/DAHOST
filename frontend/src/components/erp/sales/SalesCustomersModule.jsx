/**
 * Master Pelanggan (Portal Penjualan).
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout · cari ± 16 rem · tabel standar (kartu ringkas di HP) · form = popup
 * standar (FormPopup panjang) · nonaktifkan lewat konfirmasi. Unduh/impor tetap lewat ImportExportToolbar
 * (Excel & CSV dari server). Isian, validasi, dan panggilan server tidak berubah.
 */
import { useEffect, useMemo, useState } from 'react';
import { Ban, Contact, Pencil, Plus, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import ImportExportToolbar from '../ImportExportToolbar';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { apiGet, apiPost, apiPut, apiDelete, getToken } from '../../../lib/api';
import DocNumberField, { useDocNumberPolicy, docNumberPayload } from '../docnum/DocNumberField';

export const TERMS = [
  { v: 'cash', l: 'Tunai' }, { v: 'net_7', l: 'Tempo 7 hari' }, { v: 'net_14', l: 'Tempo 14 hari' }, { v: 'net_30', l: 'Tempo 30 hari' },
];
const EMPTY = { code: '', name: '', company_type: 'personal', phone: '', email: '', npwp: '', address: '', payment_terms: 'cash', credit_limit: 0, notes: '' };
const labelTermin = (v) => TERMS.find((t) => t.v === v)?.l || v || '—';

export default function SalesCustomersModule() {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState('');
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [memuat, setMemuat] = useState(false);
  const numPolicy = useDocNumberPolicy('rahaza_customers.code', getToken());

  const load = async () => {
    setMemuat(true);
    try { setRows(await apiGet('/sales/customers?include_inactive=true')); } catch (e) { toast.error(e.message); }
    finally { setMemuat(false); }
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => rows.filter((r) => !q || `${r.code} ${r.name} ${r.phone}`.toLowerCase().includes(q.toLowerCase())), [rows, q]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);

  const save = async () => {
    if (!form.name?.trim()) return toast.error('Nama pelanggan wajib.');
    setBusy(true);
    try {
      if (form.id) await apiPut(`/sales/customers/${form.id}`, form);
      else { const { code, ...rest } = form; await apiPost('/sales/customers', { ...rest, ...docNumberPayload(numPolicy, 'code', code) }); }
      toast.success('Pelanggan tersimpan'); setForm(null); load();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  // 2026-11-07 (audit form Tahap 5): konfirmasi dialog aplikasi + pelanggan nonaktif bisa diaktifkan lagi.
  const deactivate = async (r) => {
    if (!(await confirmDialog({ title: `Nonaktifkan pelanggan ${r.name}?`, body: 'Pelanggan tidak bisa dipilih di nota baru. Riwayat tetap ada.', confirmLabel: 'Nonaktifkan', danger: true }))) return;
    try { await apiDelete(`/sales/customers/${r.id}`); toast.success('Dinonaktifkan'); load(); } catch (e) { toast.error(e.message); }
  };
  const reactivate = async (r) => {
    try { await apiPut(`/sales/customers/${r.id}`, { active: true }); toast.success(`${r.name} diaktifkan lagi`); load(); } catch (e) { toast.error(e.message); }
  };
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const kolom = [
    { kunci: 'kode', label: 'Kode', hp: 'keterangan', isi: (r) => <span className="tabular-nums">{r.code}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (r) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{r.name}</p>
        <p className="text-xs text-muted-foreground">{r.company_type === 'company' ? 'Perusahaan' : 'Perorangan'}{r.npwp ? ` · NPWP ${r.npwp}` : ''}</p>
      </div>) },
    { kunci: 'kontak', label: 'Kontak', isi: (r) => (
      <div className="min-w-0">
        <p>{r.phone || '—'}</p>
        {r.email && <p className="text-xs text-muted-foreground">{r.email}</p>}
      </div>) },
    { kunci: 'termin', label: 'Termin', isi: (r) => labelTermin(r.payment_terms) },
    { kunci: 'limit', label: 'Limit kredit', rata: 'kanan', isi: (r) => <span className="tabular-nums">{Number(r.credit_limit || 0).toLocaleString('id-ID')}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => (r.active === false
      ? <StatusBadge status="nonaktif" label="Nonaktif" tone="muted" />
      : <StatusBadge status="aktif" label="Aktif" tone="success" />) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => (
      <div className="flex justify-end gap-1.5" data-testid={`cust-row-${r.code}`}>
        <Button size="sm" variant="outline" onClick={() => setForm({ ...EMPTY, ...r })} data-testid={`cust-edit-${r.code}`}><Pencil />Ubah</Button>
        {r.active !== false
          ? <Button size="icon-sm" variant="ghost" onClick={() => deactivate(r)} title="Nonaktifkan" aria-label="Nonaktifkan" data-testid={`cust-deactivate-${r.code}`}><Ban /></Button>
          : <Button size="sm" variant="outline" onClick={() => reactivate(r)} data-testid={`cust-reactivate-${r.code}`}>Aktifkan</Button>}
      </div>) },
  ];

  return (
    <PageLayout testId="sales-customers" title="Master Pelanggan"
      subtitle="Pelanggan penjualan langsung beserta termin bayar dan limit kreditnya."
      actions={<Button onClick={() => setForm({ ...EMPTY })} data-testid="cust-add"><Plus />Pelanggan baru</Button>}
      filters={<div className="relative w-full sm:w-64">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode, nama, telepon" className="pl-8" data-testid="cust-search" />
      </div>}
      tools={<>
        <ImportExportToolbar collectionKey="customers" label="Master Pelanggan" onImported={load} />
        <Button variant="outline" size="icon" onClick={load} disabled={memuat} title="Muat ulang" aria-label="Muat ulang" data-testid="cust-refresh">
          <RefreshCw className={memuat ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={filtered.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />
      )}>
      <TabelData kolom={kolom} baris={paged} testId="cust-table"
        kosong={<EmptyState icon={Contact} testId="cust-empty"
          title={rows.length ? 'Tidak ada pelanggan yang cocok' : 'Belum ada pelanggan'}
          description={rows.length ? 'Ubah kata pencarian.' : 'Klik Pelanggan baru untuk menambahkan pelanggan pertama.'} />} />

      <FormPopup open={!!form} onClose={() => setForm(null)} ukuran="panjang" onSimpan={save} menyimpan={busy}
        judul={form?.id ? `Ubah pelanggan ${form.code}` : 'Pelanggan baru'}
        keterangan="Sub-akun piutang pelanggan dibuat otomatis." testId="cust-form">
        {form && (
          <div className="grid gap-4 sm:grid-cols-2">
            {form.id
              ? <Isian label="Kode" htmlFor="cust-code"><Input id="cust-code" value={form.code || ''} disabled data-testid="cust-form-code" /></Isian>
              : <DocNumberField policy={numPolicy} value={form.code} onChange={(v) => set('code', v)} testId="cust-form-code" label="Kode pelanggan" />}
            <Isian label="Nama" wajib htmlFor="cust-name"><Input id="cust-name" value={form.name} onChange={(e) => set('name', e.target.value)} data-testid="cust-form-name" /></Isian>
            <Isian label="Jenis">
              <SmartNativeSelect className="h-9 w-full" searchable={false} value={form.company_type} onChange={(e) => set('company_type', e.target.value)}
                aria-label="Jenis" data-testid="cust-form-type"><option value="personal">Perorangan</option><option value="company">Perusahaan</option></SmartNativeSelect>
            </Isian>
            <Isian label="Termin bayar">
              <SmartNativeSelect className="h-9 w-full" searchable={false} value={form.payment_terms} onChange={(e) => set('payment_terms', e.target.value)}
                aria-label="Termin bayar" data-testid="cust-form-terms">{TERMS.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}</SmartNativeSelect>
            </Isian>
            <Isian label="Telepon" htmlFor="cust-phone"><Input id="cust-phone" value={form.phone || ''} onChange={(e) => set('phone', e.target.value)} data-testid="cust-form-phone" /></Isian>
            <Isian label="Email" htmlFor="cust-email"><Input id="cust-email" value={form.email || ''} onChange={(e) => set('email', e.target.value)} data-testid="cust-form-email" /></Isian>
            <Isian label="NPWP" htmlFor="cust-npwp"><Input id="cust-npwp" value={form.npwp || ''} onChange={(e) => set('npwp', e.target.value)} data-testid="cust-form-npwp" /></Isian>
            <Isian label="Limit kredit (Rp)"><MoneyInput value={form.credit_limit ?? 0} onChange={(e) => set('credit_limit', e.target.value)} data-testid="cust-form-limit" /></Isian>
            <Isian label="Alamat" htmlFor="cust-address" className="sm:col-span-2"><Input id="cust-address" value={form.address || ''} onChange={(e) => set('address', e.target.value)} data-testid="cust-form-address" /></Isian>
            <Isian label="Catatan" htmlFor="cust-notes" className="sm:col-span-2"><Input id="cust-notes" value={form.notes || ''} onChange={(e) => set('notes', e.target.value)} data-testid="cust-form-notes" /></Isian>
          </div>
        )}
      </FormPopup>
    </PageLayout>
  );
}
