/**
 * Belum masuk jurnal — Paket 1 audit keuangan (25 Nov 2026).
 *
 * Satu daftar dokumen yang mengubah uang/stok tetapi jurnalnya gagal (dulu hanya tercatat diam-diam di dokumen
 * masing-masing). "Posting ulang" memanggil fungsi posting resmi dokumen itu di server (`core/jurnal_tertunda.py`);
 * jurnal yang sudah ada tidak dibuat dua kali. Jenis tanpa posting ulang di sini dibuka di layarnya sendiri.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, CheckCircle2, RefreshCw, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FilterChips from '@/components/ui/filter-chips';
import TombolUnduh from '@/components/ui/tombol-unduh';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { apiFetch, ApiError } from '@/lib/apiFetch';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState } from '../moduleAtoms';

const rupiah = (v) => (v === null || v === undefined ? '—' : `Rp ${Math.round(Number(v) || 0).toLocaleString('id-ID')}`);
const tgl = (v) => (v ? formatDateID(v) : '—');

function buka(onNavigate, modul, tab) {
  if (tab) {
    try { sessionStorage.setItem(`hub_tab_${modul}`, tab); } catch { /* penyimpanan diblokir */ }
  }
  onNavigate?.(modul);
}

export default function JurnalTertundaModule({ onNavigate }) {
  const [rows, setRows] = useState([]);
  const [bolehUlang, setBolehUlang] = useState(false);
  const [memuat, setMemuat] = useState(true);
  const [jenis, setJenis] = useState('');
  const [proses, setProses] = useState('');

  const muat = useCallback(async () => {
    setMemuat(true);
    try {
      const r = await apiFetch('/rahaza/finance/jurnal-tertunda');
      setRows(Array.isArray(r?.data) ? r.data : []);
      setBolehUlang(Boolean(r?.boleh_ulang));
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) toast.error('Gagal memuat dokumen yang belum masuk jurnal');
      setRows([]);
    } finally {
      setMemuat(false);
    }
  }, []);
  useEffect(() => { muat(); }, [muat]);

  const pilihan = useMemo(() => {
    const per = new Map();
    rows.forEach((r) => per.set(r.jenis, { key: r.jenis, label: r.label, count: (per.get(r.jenis)?.count || 0) + 1 }));
    return [{ key: '', label: 'Semua', count: rows.length }, ...per.values()];
  }, [rows]);
  const tampil = useMemo(() => (jenis ? rows.filter((r) => r.jenis === jenis) : rows), [rows, jenis]);
  const { page, setPage, totalPages, total, paged } = useClientPagination(tampil, 15);

  const ulang = async (r) => {
    const kunci = `${r.jenis}-${r.id}`;
    setProses(kunci);
    try {
      const out = await apiFetch(`/rahaza/finance/jurnal-tertunda/${encodeURIComponent(r.jenis)}/${encodeURIComponent(r.id)}/ulang`,
        { method: 'POST' });
      toast.success(out?.pesan || 'Sudah masuk jurnal');
      await muat();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) {
        toast.error(e instanceof ApiError && typeof e.detail === 'string' ? e.detail : 'Posting ulang gagal');
      }
    } finally {
      setProses('');
    }
  };

  return (
    <PageLayout
      title="Belum masuk jurnal"
      subtitle="Dokumen yang sudah mengubah uang atau stok, tetapi jurnalnya gagal dibuat. Perbaiki penyebabnya, lalu posting ulang."
      testId="jurnal-tertunda"
      filters={<FilterChips value={jenis} onChange={(k) => { setJenis(k); setPage(1); }} options={pilihan}
        testId="jurnal-tertunda-jenis" ariaLabel="Jenis dokumen" />}
      tools={(
        <>
          <Button variant="outline" size="icon" onClick={muat} title="Muat ulang" aria-label="Muat ulang"
            data-testid="jurnal-tertunda-muat"><RefreshCw /></Button>
          <TombolUnduh namaBerkas="belum-masuk-jurnal" namaLembar="Belum masuk jurnal" baris={tampil}
            testId="jurnal-tertunda-unduh"
            kolom={[
              { label: 'Jenis', nilai: (r) => r.label || '' },
              { label: 'Dokumen', nilai: (r) => r.nama || '' },
              { label: 'Tanggal', nilai: (r) => r.tanggal || '' },
              { label: 'Nilai', nilai: (r) => (r.nilai === null || r.nilai === undefined ? '' : Math.round(r.nilai)) },
              { label: 'CV', nilai: (r) => r.cv || '' },
              { label: 'Penyebab', nilai: (r) => r.galat || '' },
            ]} />
        </>
      )}
      footer={<PaginationLite page={page} totalPages={totalPages} total={total} pageSize={15} onPageChange={setPage} />}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Dokumen</TableHead>
            <TableHead className="hidden sm:table-cell">Tanggal</TableHead>
            <TableHead className="hidden md:table-cell text-right">Nilai</TableHead>
            <TableHead>Penyebab</TableHead>
            <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {paged.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5}>
                <EmptyState icon={CheckCircle2} title={memuat ? 'Memuat…' : 'Semua dokumen sudah masuk jurnal'}
                  description={memuat ? '' : 'Bila ada jurnal yang gagal dibuat, dokumennya muncul di sini.'} />
              </TableCell>
            </TableRow>
          ) : paged.map((r) => {
            const kunci = `${r.jenis}-${r.id}`;
            return (
              <TableRow key={kunci} data-testid={`tertunda-${kunci}`}>
                <TableCell className="font-medium">
                  {r.nama}
                  <span className="block text-xs font-normal text-muted-foreground">
                    {r.label}{r.cv ? ` · ${r.cv}` : ''}<span className="sm:hidden"> · {tgl(r.tanggal)}</span>
                  </span>
                </TableCell>
                <TableCell className="hidden whitespace-nowrap sm:table-cell">{tgl(r.tanggal)}</TableCell>
                <TableCell className="hidden whitespace-nowrap text-right tabular-nums md:table-cell">{rupiah(r.nilai)}</TableCell>
                <TableCell className="text-sm text-muted-foreground" title={r.galat_asli || ''}>{r.galat || '—'}</TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    {r.modul && onNavigate && (
                      <Button variant="link" size="sm" onClick={() => buka(onNavigate, r.modul, r.tab)}>Buka<ArrowRight /></Button>
                    )}
                    {r.bisa_ulang && bolehUlang && (
                      <Button variant="outline" size="sm" disabled={proses === kunci} onClick={() => ulang(r)}
                        data-testid={`ulang-${kunci}`}>
                        <RotateCcw />{proses === kunci ? 'Memproses…' : 'Posting ulang'}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </PageLayout>
  );
}
