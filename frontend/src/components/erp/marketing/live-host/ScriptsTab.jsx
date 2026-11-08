/**
 * Naskah live (Live Selling › Host live › Naskah).
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, daftar kartu → tabel + unduh, isi naskah lengkap di popup detail
 * (Ubah/Hapus juga ada di sana), label Indonesia (dulu "Add Script", "All Categories", "Scope"). Permintaan ke server sama.
 */
import { useState, useEffect, useCallback } from 'react';
import { Video, Plus, Edit, Trash2, RefreshCw } from 'lucide-react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { toast } from 'sonner';
import PageLayout from '../../layout/PageLayout';
import { EmptyState } from '../../moduleAtoms';
import { API } from './utils';
import ScriptModal from './ScriptModal';

export const KATEGORI_NASKAH = {
  opening: 'Pembuka', demo: 'Demo produk', promo: 'Promo', closing: 'Penutup', faq: 'Tanya jawab', objection_handling: 'Menangani keberatan',
};
const BAHASA = { indonesia: 'Indonesia', english: 'Inggris', mandarin: 'Mandarin' };

export default function ScriptsTab({ authH }) {
  const [scripts, setScripts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingScript, setEditingScript] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [detail, setDetail] = useState(null);

  const fetchScripts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (categoryFilter !== 'all') params.append('category', categoryFilter);

      const res = await fetch(`${API}/api/marketing/livehost/scripts?${params}`, { headers: authH });
      if (res.ok) {
        const data = await res.json();
        setScripts(data);
      }
    } catch (e) {
      toast.error('Gagal memuat naskah');
    } finally {
      setLoading(false);
    }
  }, [authH, categoryFilter]);

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
    fetchScripts();
    fetchAccounts();
  }, [fetchScripts, fetchAccounts]);

  const handleDelete = async (script) => {
    if (!(await confirmDialog({ title: `Hapus naskah "${script.title}"?`, confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const res = await fetch(`${API}/api/marketing/livehost/scripts/${script.id}`, {
        method: 'DELETE',
        headers: authH,
      });
      if (res.ok) {
        toast.success('Naskah dihapus.');
        setDetail(null);
        fetchScripts();
      }
    } catch (e) {
      toast.error('Gagal menghapus naskah');
    }
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(scripts, 10);
  const kategori = (s) => KATEGORI_NASKAH[s.category] || s.category || '—';
  const bahasa = (s) => BAHASA[s.language] || s.language || '—';
  const cakupan = (s) => s.account_name || 'Semua akun toko';
  const bukaBaru = () => { setEditingScript(null); setShowModal(true); };
  const ubah = (s) => { setDetail(null); setEditingScript(s); setShowModal(true); };

  const kolom = [
    { kunci: 'judul', label: 'Judul', hp: 'judul', isi: (s) => (
      <span><span className="font-medium">{s.title}</span>
        <span className="block max-w-md truncate text-xs text-muted-foreground">{s.script_text}</span></span>) },
    { kunci: 'kat', label: 'Kategori', hp: 'keterangan', isi: kategori },
    { kunci: 'bahasa', label: 'Bahasa', isi: bahasa },
    { kunci: 'cakupan', label: 'Berlaku untuk', isi: cakupan },
    { kunci: 'produk', label: 'Produk', rata: 'kanan', isi: (s) => <span className="tabular-nums">{(s.products_applicable || []).length || '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        <Button variant="ghost" size="icon-sm" onClick={() => ubah(s)} title="Ubah naskah" aria-label="Ubah naskah"><Edit /></Button>
        <Button variant="ghost" size="icon-sm" className="text-[hsl(var(--danger-text))]" onClick={() => handleDelete(s)}
          title="Hapus naskah" aria-label="Hapus naskah"><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="scripts-tab" title="Naskah live" subtitle="Naskah pembuka, demo, promo, dan penutup untuk host live."
      actions={<Button onClick={bukaBaru} data-testid="add-script-btn"><Plus />Tambah naskah</Button>}
      filters={
        <SmartNativeSelect value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="w-48" wrapperClassName="w-48 max-w-full" searchable={false}
          data-testid="filter-script-category">
          <option value="all">Semua kategori</option>
          {Object.entries(KATEGORI_NASKAH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
      }
      tools={<>
        <TombolUnduh namaBerkas="naskah-live" namaLembar="Naskah" baris={scripts} testId="script-unduh"
          kolom={[
            { label: 'Judul', nilai: (s) => s.title || '' }, { label: 'Kategori', nilai: kategori }, { label: 'Bahasa', nilai: bahasa },
            { label: 'Berlaku untuk', nilai: cakupan }, { label: 'Produk', nilai: (s) => (s.products_applicable || []).join(', ') },
            { label: 'Isi naskah', nilai: (s) => s.script_text || '' },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchScripts} title="Muat ulang" aria-label="Muat ulang" data-testid="refresh-scripts">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      footer={scripts.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}>
      {loading && scripts.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat naskah…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} testId="scripts-table" onKlikBaris={setDetail}
          kosong={<EmptyState icon={Video} title={categoryFilter === 'all' ? 'Belum ada naskah' : 'Tidak ada naskah di kategori ini'}
            description="Naskah membantu host live menjaga alur siaran."
            action={<Button onClick={bukaBaru}><Plus />Tambah naskah</Button>} />} />
      )}

      <DetailPopup open={!!detail} onClose={() => setDetail(null)} judul={detail?.title} keterangan={detail && `${kategori(detail)} · ${bahasa(detail)}`}
        testId="script-detail"
        aksi={detail && <>
          <Button variant="outline" className="text-[hsl(var(--danger-text))]" onClick={() => handleDelete(detail)}><Trash2 />Hapus</Button>
          <Button onClick={() => ubah(detail)}><Edit />Ubah</Button>
        </>}>
        {detail && <>
          <BarisDetail label="Berlaku untuk">{cakupan(detail)}</BarisDetail>
          <BarisDetail label="Produk">{(detail.products_applicable || []).join(', ') || '—'}</BarisDetail>
          <div className="mt-3 whitespace-pre-wrap rounded-md border border-[hsl(var(--glass-border))] p-3 text-sm">{detail.script_text}</div>
        </>}
      </DetailPopup>

      {showModal && (
        <ScriptModal
          script={editingScript}
          accounts={accounts}
          authH={authH}
          onClose={() => {
            setShowModal(false);
            setEditingScript(null);
          }}
          onSuccess={() => {
            setShowModal(false);
            setEditingScript(null);
            fetchScripts();
          }}
        />
      )}
    </PageLayout>
  );
}
