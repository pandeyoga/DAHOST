import { useState, useEffect, useCallback } from 'react';
import { Plus, RefreshCw, Edit2, Trash2, PieChart } from 'lucide-react';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState, Notice } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { MoneyInput } from '@/components/ui/money-input';
import { formatRupiah } from '@/lib/format';

const PAGE_SIZE = 25;
const catLabel = (c) => (c ? c.charAt(0).toUpperCase() + c.slice(1).replace(/_/g, ' ') : '—');

/**
 * Pusat biaya (menu Pengaturan Keuangan › Pusat biaya).
 * 2026-11-05 (PANDUAN_UI G1): cetakan PageLayout; formulir di dialog aplikasi (dulu lapisan buatan sendiri).
 */
export default function RahazaCostCentersModule({ token }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchRows = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/cost-centers', { headers });
      if (r.ok) setRows(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  useEffect(() => { fetchRows(); }, [fetchRows]);

  const save = async (body) => {
    setError('');
    const url = body.id ? `/api/rahaza/cost-centers/${body.id}` : '/api/rahaza/cost-centers';
    const method = body.id ? 'PUT' : 'POST';
    const r = await fetch(url, { method, headers, body: JSON.stringify(body) });
    if (!r.ok) setError(`Gagal menyimpan (HTTP ${r.status})`); else { setEditing(null); fetchRows(); }
  };
  const del = async (id) => {
    if (!(await confirmDialog({ title: 'Nonaktifkan pusat biaya ini?', confirmLabel: 'Nonaktifkan', danger: true }))) return;
    const r = await fetch(`/api/rahaza/cost-centers/${id}`, { method: 'DELETE', headers });
    if (r.ok) fetchRows();
  };

  const { page, setPage, totalPages, total, paged } = useClientPagination(rows, PAGE_SIZE);
  return (
    <PageLayout
      testId="rahaza-cost-centers-page"
      title="Pusat biaya"
      subtitle="Pusat biaya untuk alokasi biaya dan overhead ke HPP."
      actions={<Button onClick={() => setEditing({ code: '', name: '', category: 'umum', overhead_rate_per_pcs: 0 })} data-testid="cc-add"><Plus className="w-4 h-4" />Pusat biaya baru</Button>}
      tools={<>
        <TombolUnduh namaBerkas="pusat-biaya" namaLembar="Pusat biaya" baris={rows} testId="cc-unduh"
          kolom={[
            { label: 'Kode', nilai: (r) => r.code },
            { label: 'Nama', nilai: (r) => r.name },
            { label: 'Kategori', nilai: (r) => catLabel(r.category) },
            { label: 'Overhead per pcs', nilai: (r) => Number(r.overhead_rate_per_pcs) || 0 },
          ]} />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchRows} data-testid="cc-refresh"><RefreshCw className="w-4 h-4" /></Button>
      </>}
      summary={error && <Notice tone="danger">{error}</Notice>}
      footer={!loading && rows.length > 0 && (
        <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading ? (
          <Skeleton className="h-40 m-4" />
        ) : rows.length === 0 ? (
          <EmptyState icon={PieChart} title="Belum ada pusat biaya" description="Tambahkan pusat biaya untuk mengalokasikan biaya dan overhead ke HPP." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead><tr><th className="text-left">Kode</th><th className="text-left">Nama</th><th className="text-left">Kategori</th><th className="text-right">Overhead per pcs</th><th className="text-right">Aksi</th></tr></thead>
              <tbody>
                {paged.map(r => (
                  <tr key={r.id} data-testid={`cc-row-${r.code}`}>
                    <td className="whitespace-nowrap text-foreground">{r.code}</td>
                    <td className="text-foreground">{r.name}</td>
                    <td className="text-muted-foreground">{catLabel(r.category)}</td>
                    <td className="text-right tabular-nums text-foreground">{formatRupiah(r.overhead_rate_per_pcs || 0)}</td>
                    <td className="text-right">
                      <div className="flex gap-1 justify-end">
                        <Button variant="ghost" size="icon-sm" onClick={() => setEditing({ ...r })} title="Ubah" aria-label="Ubah" data-testid={`cc-edit-${r.code}`}><Edit2 className="w-4 h-4" /></Button>
                        <Button variant="ghost" size="icon-sm" onClick={() => del(r.id)} title="Nonaktifkan" aria-label="Nonaktifkan" className="text-[hsl(var(--danger-text))]" data-testid={`cc-delete-${r.code}`}><Trash2 className="w-4 h-4" /></Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      {editing && <CCEditor value={editing} onClose={() => setEditing(null)} onSave={save} />}
    </PageLayout>
  );
}

function CCEditor({ value, onClose, onSave }) {
  const [s, setS] = useState(value);
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="cc-editor"
      judul={s.id ? 'Ubah pusat biaya' : 'Pusat biaya baru'} onSimpan={() => onSave(s)}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Kode"><GlassInput value={s.code} onChange={e => upd('code', e.target.value.toUpperCase())} disabled={!!s.id} data-testid="cc-code" /></Isian>
        <Isian label="Nama"><GlassInput value={s.name} onChange={e => upd('name', e.target.value)} data-testid="cc-name" /></Isian>
        <Isian label="Kategori"><GlassInput value={s.category} onChange={e => upd('category', e.target.value)} placeholder="mis. produksi, gudang, umum" /></Isian>
        <Isian label="Overhead per pcs (Rp)"><MoneyInput glass value={s.overhead_rate_per_pcs || 0} onChange={e => upd('overhead_rate_per_pcs', Number(e.target.value))} data-testid="cc-overhead" /></Isian>
      </div>
    </FormPopup>
  );
}
