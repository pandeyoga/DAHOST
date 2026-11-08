/**
 * Laporan Saldo antar CV (Portal Keuangan, Tahap 8 fase 2 — desain §3).
 *
 * Per pasangan: hutang di buku CV Dewi Aditya harus SAMA dengan piutang di buku CV Sukma, dan sebaliknya.
 * Per tanggal; selisih ditandai, dan rincian baris jurnal tiap sisi dibuka di bawah barisnya (RowDetail).
 * Di bawahnya daftar dokumen antar CV (tagihan jasa jahit, nota aksesoris) dengan PDF berkop CV penerbitnya.
 * 2026-11-08 (Standar UI/UX v2): "Per tanggal" = DatePicker; kedua tabel bisa diunduh Excel/CSV; warna teks token.
 *
 *   GET /api/rahaza/intercompany/balances?as_of=YYYY-MM-DD
 *   GET /api/rahaza/intercompany/documents
 *   GET /api/rahaza/intercompany/documents/{id}/pdf
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileText, Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import DatePicker from '@/components/ui/date-picker';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { cvLabel, withCvParam } from '@/lib/entitas';
import { apiFetch, apiGet } from '../../../lib/api';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';

const fmt = formatRupiah;
const KIND = { sewing: 'Tagihan jasa jahit', accessory: 'Nota aksesoris', accessory_margin: 'Margin aksesoris',
  payment: 'Pembayaran antar CV', transaction: 'Transaksi antar CV' };

function SideLines({ side }) {
  const lines = side.lines || [];
  if (!lines.length) return <p className="text-xs text-muted-foreground">Belum ada baris jurnal di akun {side.account_code || '—'}.</p>;
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium">{side.label} · {cvLabel(side.entity)} · akun {side.account_code}</p>
      {lines.map((l, i) => (
        <div key={i} className="flex flex-wrap justify-between gap-x-2 text-xs" data-testid="ic-bal-line">
          <span className="text-muted-foreground min-w-0 break-words">{formatDateID(l.date)} · {l.je_number} · {KIND[l.ic_kind] || (l.intercompany ? 'antar CV' : 'lainnya')} · {l.description}</span>
          <span className="tabular-nums whitespace-nowrap">{l.debit ? `D ${fmt(l.debit)}` : `K ${fmt(l.credit)}`}</span>
        </div>
      ))}
    </div>
  );
}

export default function IntercompanyBalanceModule() {
  const [asOf, setAsOf] = useState(todayWIB());
  const [data, setData] = useState(null);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [openKey, setOpenKey] = useState(null);
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [b, d] = await Promise.all([apiGet(`/rahaza/intercompany/balances?as_of=${asOf}`), apiGet('/rahaza/intercompany/documents')]);
      setData(b); setDocs(d.items || []);
    } catch (e) { setError(e.message || 'Gagal memuat'); }
    finally { setLoading(false); }
  }, [asOf]);
  useEffect(() => { load(); }, [load]);
  const openPdf = async (doc) => {
    try {
      const r = await apiFetch(withCvParam(`/rahaza/intercompany/documents/${doc.id}/pdf`));
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const url = URL.createObjectURL(await r.blob());
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) { toast.error(`PDF gagal dibuka: ${e.message}`); }
  };
  const pairs = data?.pairs || [];
  return (
    <PageLayout
      testId="ic-balance-page"
      title="Saldo antar CV"
      subtitle="Hutang di satu buku harus sama dengan piutang di buku CV lain; selisih bisa dirinci."
      filters={<div className="w-full sm:w-48" title="Per tanggal">
        <DatePicker value={asOf} onChange={(v) => setAsOf(v || todayWIB())} bolehKosong={false} testId="ic-bal-asof" />
      </div>}
      tools={<>
        <TombolUnduh namaBerkas={`saldo-antar-cv-${asOf}`} namaLembar="Saldo antar CV" baris={pairs} testId="ic-bal-unduh"
          kolom={[
            { label: 'Pasangan', nilai: (p) => p.label },
            { label: 'Keterangan', nilai: (p) => p.hint || '' },
            { label: 'Buku CV Dewi Aditya', nilai: (p) => Number(p.left?.balance) || 0 },
            { label: 'Akun CV Dewi Aditya', nilai: (p) => `${p.left?.label || ''} ${p.left?.account_code || ''}`.trim() },
            { label: 'Buku CV Sukma', nilai: (p) => Number(p.right?.balance) || 0 },
            { label: 'Akun CV Sukma', nilai: (p) => `${p.right?.label || ''} ${p.right?.account_code || ''}`.trim() },
            { label: 'Selisih', nilai: (p) => Number(p.difference) || 0 },
            { label: 'Status', nilai: (p) => (p.balanced ? 'Sama' : 'Selisih') },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /></Button>
      </>}
      summary={<>
        {error && <Notice tone="danger" icon={AlertTriangle}>{error}</Notice>}
        {data && (
          <p className={`flex items-center gap-1.5 text-sm ${data.balanced ? 'text-muted-foreground' : 'text-[hsl(var(--danger-text))] font-medium'}`} data-testid="ic-bal-status">
            {data.balanced
              ? <><CheckCircle2 className="w-4 h-4 text-[hsl(var(--success-text))]" /> Seimbang per {formatDateID(data.as_of)}: semua pasangan saldo sama di dua buku.</>
              : <><AlertTriangle className="w-4 h-4" /> Ada selisih antar CV per {formatDateID(data.as_of)} — buka rinciannya.</>}
          </p>
        )}
      </>}
    >
      <GlassCard className="p-0 overflow-hidden">
        {loading && !data ? (
          <div className="flex justify-center py-8"><Loader2 className="animate-spin text-muted-foreground" /></div>
        ) : (
          <Table className="min-w-[640px] md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Pasangan</TableHead>
                <TableHead className="text-right">Buku CV Dewi Aditya</TableHead>
                <TableHead className="text-right">Buku CV Sukma</TableHead>
                <TableHead className="text-right">Selisih</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pairs.map((p) => {
                const open = openKey === p.key;
                return (
                  <Fragment key={p.key}>
                    <TableRow data-testid={`ic-bal-row-${p.key}`}>
                      <TableCell><RowToggle open={open} onClick={() => setOpenKey(open ? null : p.key)} testId={`ic-bal-toggle-${p.key}`} /></TableCell>
                      <TableCell className="text-sm">
                        <p className="font-medium">{p.label}</p>
                        <p className="text-xs text-muted-foreground">{p.hint}</p>
                      </TableCell>
                      <TableCell className="text-right" data-testid={`ic-bal-left-${p.key}`}>
                        <span className="tabular-nums whitespace-nowrap">{fmt(p.left.balance)}</span>
                        <p className="text-xs text-muted-foreground">{p.left.label} · {p.left.account_code || '—'}</p>
                      </TableCell>
                      <TableCell className="text-right" data-testid={`ic-bal-right-${p.key}`}>
                        <span className="tabular-nums whitespace-nowrap">{fmt(p.right.balance)}</span>
                        <p className="text-xs text-muted-foreground">{p.right.label} · {p.right.account_code || '—'}</p>
                      </TableCell>
                      <TableCell className="text-right tabular-nums whitespace-nowrap" data-testid={`ic-bal-diff-${p.key}`}>{fmt(p.difference)}</TableCell>
                      <TableCell>{p.balanced ? <StatusBadge status="ok" label="Sama" tone="success" /> : <StatusBadge status="diff" label="Selisih" tone="danger" />}</TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={6} testId={`ic-bal-detail-${p.key}`}>
                        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 whitespace-normal">
                          <SideLines side={p.left} />
                          <SideLines side={p.right} />
                        </div>
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      <GlassCard className="p-0 overflow-hidden" data-testid="ic-docs">
        <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
          <p className="text-base font-semibold text-foreground">Dokumen antar CV</p>
          <TombolUnduh namaBerkas="dokumen-antar-cv" namaLembar="Dokumen antar CV" baris={docs} testId="ic-doc-unduh"
            kolom={[
              { label: 'Dokumen', nilai: (d) => d.invoice_number },
              { label: 'Jenis', nilai: (d) => KIND[d.ic_kind] || '' },
              { label: 'Penerbit', nilai: (d) => cvLabel(d.entity) },
              { label: 'Tanggal', nilai: (d) => formatDateID(d.issue_date) },
              { label: 'PO', nilai: (d) => d.po_number || '' },
              { label: 'Total', nilai: (d) => Number(d.total) || 0 },
              { label: 'Sisa', nilai: (d) => Number(d.balance) || 0 },
            ]} />
        </div>
        <Table className="md:min-w-0">
          <TableHeader>
            <TableRow>
              <TableHead>Dokumen</TableHead>
              <TableHead>Penerbit</TableHead>
              <TableHead>Tanggal</TableHead>
              <TableHead>PO</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Sisa</TableHead>
              <TableHead className="text-right">PDF</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {docs.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={7} className="p-0 [&>div]:py-8">
                  <EmptyState icon={FileText} title="Belum ada dokumen antar CV"
                    description="Tagihan jasa jahit lahir dari penerimaan CMT tim CV Sukma; nota aksesoris dari pengeluaran aksesoris untuk PO maklon." />
                </TableCell>
              </TableRow>
            )}
            {docs.map((d) => (
              <TableRow key={d.id} data-testid={`ic-doc-row-${d.invoice_number}`}>
                <TableCell className="text-sm"><p className="whitespace-nowrap">{d.invoice_number}</p><p className="text-xs text-muted-foreground">{KIND[d.ic_kind] || '—'}{Number(d.margin_amount) > 0 ? ` · margin ${d.margin_pct}%` : ''}</p></TableCell>
                <TableCell className="text-sm whitespace-nowrap">{cvLabel(d.entity)}</TableCell>
                <TableCell className="text-muted-foreground whitespace-nowrap">{formatDateID(d.issue_date)}</TableCell>
                <TableCell className="whitespace-nowrap">{d.po_number || '—'}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(d.total)}</TableCell>
                <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(d.balance)}</TableCell>
                <TableCell className="text-right">
                  <Button variant="outline" size="icon" onClick={() => openPdf(d)} title="Buka PDF" aria-label="Buka PDF" data-testid={`ic-doc-pdf-${d.invoice_number}`}><FileText className="w-4 h-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </GlassCard>
    </PageLayout>
  );
}
