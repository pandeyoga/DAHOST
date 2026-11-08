/**
 * Host live (Live Selling › Host live) — daftar host live.
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, penyaring satu baris (akun aktif kini pilihan di baris penyaring, dulu bar
 * lebar), tabel + unduh, form = FormPopup (AddEditHostModal), label Indonesia.
 */
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { useState, useEffect, useCallback } from 'react';
import { Users, Plus, Edit, Trash2, RefreshCw, Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import { useActiveMarketingAccount } from '@/hooks/useActiveMarketingAccount';
import PageLayout from '../../layout/PageLayout';
import { EmptyState } from '../../moduleAtoms';
import { API, fmtRp } from './utils';
import { StatusBadge, EmploymentTypeBadge, LABEL_STATUS_HOST, LABEL_JENIS_KERJA } from './Badges';
import AddEditHostModal from './AddEditHostModal';

export default function LiveHostsTab({ authH }) {
  const [hosts, setHosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [accounts, setAccounts] = useState([]);

  // Shared persistent account context (localStorage)
  const { activeAccount: activeAccountCtx, setActiveAccount: setActiveAccountCtx } = useActiveMarketingAccount();
  const filterAccountId = activeAccountCtx?.id || '';
  const setFilterAccountId = (id) => {
    const acc = accounts.find((a) => a.id === id);
    setActiveAccountCtx(acc || null);
  };

  const [showAddEditModal, setShowAddEditModal] = useState(false);
  const [editingHost, setEditingHost] = useState(null);

  const fetchHosts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.append('status', statusFilter);
      if (searchQuery) params.append('search', searchQuery);

      const res = await fetch(`${API}/api/marketing/livehost?${params}`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setHosts(data);
      }
    } catch (e) {
      toast.error('Gagal memuat host live');
    } finally {
      setLoading(false);
    }
  }, [authH, statusFilter, searchQuery]);

  const fetchAccounts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/marketing/accounts?status=active`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setAccounts(data);
      }
    } catch (e) {}
  }, [authH]);

  useEffect(() => {
    fetchHosts();
    fetchAccounts();
  }, [fetchHosts, fetchAccounts]);

  const handleDelete = async (host) => {
    if (!(await confirmDialog({ title: `Hapus host live "${host.name}"?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const res = await fetch(`${API}/api/marketing/livehost/${host.id}`, {
        method: 'DELETE',
        headers: authH,
      });
      if (res.ok) {
        toast.success('Host live dihapus.');
        fetchHosts();
      } else {
        const err = await res.json();
        toast.error(err.detail || 'Gagal menghapus host live');
      }
    } catch (e) {
      toast.error('Gagal menghapus host live');
    }
  };

  const displayedHosts = filterAccountId
    ? hosts.filter((h) => (h.assigned_accounts || []).some((a) => a.id === filterAccountId))
    : hosts;
  const { page, setPage, totalPages, total, paged } = useClientPagination(displayedHosts, 10);
  const namaToko = (h) => (h.assigned_accounts || []).map((a) => accounts.find((x) => x.id === a.id)?.account_name || a.name).filter(Boolean).join(', ');
  const bukaBaru = () => { setEditingHost(null); setShowAddEditModal(true); };

  const kolom = [
    { kunci: 'nama', label: 'Nama', hp: 'judul', isi: (h) => <span className="font-medium" data-testid={`host-row-${h.id}`}>{h.name}</span> },
    { kunci: 'email', label: 'Email', hp: 'keterangan', isi: (h) => <span className="text-muted-foreground">{h.email}</span> },
    { kunci: 'jenis', label: 'Jenis kerja', isi: (h) => <EmploymentTypeBadge type={h.employment_type} /> },
    { kunci: 'tarif', label: 'Tarif per jam', rata: 'kanan', isi: (h) => <span className="tabular-nums">{fmtRp(h.hourly_rate)}</span> },
    { kunci: 'toko', label: 'Toko yang ditugaskan', isi: (h) => <span className="text-sm">{namaToko(h) || <span className="text-muted-foreground">Belum ditugaskan</span>}</span> },
    { kunci: 'status', label: 'Status', isi: (h) => <StatusBadge status={h.status} /> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (h) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="icon-sm" onClick={() => { setEditingHost(h); setShowAddEditModal(true); }}
          data-testid={`edit-host-${h.id}`} title="Ubah host" aria-label="Ubah host"><Edit /></Button>
        <Button variant="ghost" size="icon-sm" className="text-[hsl(var(--danger-text))]" onClick={() => handleDelete(h)}
          data-testid={`delete-host-${h.id}`} title="Hapus host" aria-label="Hapus host"><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="livehosts-tab" title="Host live" subtitle="Daftar host live, jenis kerja, tarif, dan toko yang ditugaskan."
      actions={<Button onClick={bukaBaru} data-testid="add-livehost-btn"><Plus />Tambah host</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari nama atau email" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8" data-testid="search-livehost" />
        </div>
        <SmartNativeSelect value={filterAccountId} onChange={(e) => setFilterAccountId(e.target.value)} className="w-full" wrapperClassName="w-48 max-w-full" data-testid="filter-account">
          <option value="">Semua toko</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-full" wrapperClassName="w-40 max-w-full" searchable={false} data-testid="filter-status">
          <option value="all">Semua status</option>
          {Object.entries(LABEL_STATUS_HOST).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="host-live" namaLembar="Host" baris={displayedHosts} testId="livehost-unduh"
          kolom={[
            { label: 'Nama', nilai: (h) => h.name }, { label: 'Email', nilai: (h) => h.email || '' }, { label: 'Telepon', nilai: (h) => h.phone || '' },
            { label: 'Jenis kerja', nilai: (h) => LABEL_JENIS_KERJA[h.employment_type] || '' }, { label: 'Tarif per jam', nilai: (h) => Number(h.hourly_rate) || 0 },
            { label: 'Toko', nilai: namaToko }, { label: 'Status', nilai: (h) => LABEL_STATUS_HOST[h.status] || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchHosts} data-testid="refresh-hosts" title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={displayedHosts.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && hosts.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat host live…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="livehosts-table" onKlikBaris={(h) => { setEditingHost(h); setShowAddEditModal(true); }}
          kosong={<EmptyState icon={Users} title={hosts.length ? 'Tidak ada host yang cocok' : 'Belum ada host live'}
            description={hosts.length ? 'Ubah penyaring.' : 'Tambahkan host live pertama untuk mulai menjadwalkan shift.'}
            action={!hosts.length && <Button onClick={bukaBaru}><Plus />Tambah host</Button>} />} />
      )}

      {showAddEditModal && (
        <AddEditHostModal
          host={editingHost}
          accounts={accounts}
          authH={authH}
          onClose={() => { setShowAddEditModal(false); setEditingHost(null); }}
          onSuccess={() => { setShowAddEditModal(false); setEditingHost(null); fetchHosts(); }}
        />
      )}
    </PageLayout>
  );
}
