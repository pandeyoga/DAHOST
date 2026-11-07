import { useState, useEffect, Fragment } from 'react';
import { ChevronDown, ChevronRight, FileDown, FileSpreadsheet, RefreshCw, PackageCheck, AlertTriangle, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { GlassCard } from '@/components/ui/glass';
import { EmptyState, StatTile } from '../moduleAtoms';
import { apiGet } from '../../../lib/api';
import { todayWIB } from '../../../lib/waktu';

const fmtNum = (v) => Number(v || 0).toLocaleString('id-ID');

export default function BuyerReceiptVarianceReport() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [search, setSearch] = useState('');

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try {
      const data = await apiGet('/buyer-receipt-variance');
      setRows(Array.isArray(data) ? data : []);
    } catch (e) { toast.error(e.message || 'Gagal memuat laporan'); setRows([]); }
    setLoading(false);
  };

  const toggle = (poId) => setExpanded(prev => ({ ...prev, [poId]: !prev[poId] }));

  const q = search.trim().toLowerCase();
  const filtered = q
    ? rows.filter(r => (r.po_number || '').toLowerCase().includes(q) || (r.customer_name || '').toLowerCase().includes(q) || (r.vendor_name || '').toLowerCase().includes(q))
    : rows;

  const grandShipped = filtered.reduce((s, r) => s + (r.total_shipped || 0), 0);
  const grandReceived = filtered.reduce((s, r) => s + (r.total_received || 0), 0);
  const grandVariance = grandShipped - grandReceived;
  // GAP G: dokumen surat jalan DIKOREKSI ke qty yang benar-benar diterima, jadi
  // `total_variance` bisa 0 sementara barangnya memang belum sampai. Angka yang
  // harus dilihat pengguna adalah SELISIH TERBUKA (`SEL-BYR-…` status open).
  const grandShortOpen = filtered.reduce((s, r) => s + (r.qty_short_open || 0), 0);
  const poWithVariance = filtered.filter(r => (r.total_variance || 0) !== 0 || (r.qty_short_open || 0) > 0).length;

  const varianceClass = (v) => v > 0 ? 'text-[hsl(var(--danger-text))]' : v < 0 ? 'text-[hsl(var(--warning-text))]' : 'text-muted-foreground/70';
  const varianceText = (v) => v > 0 ? fmtNum(v) : v < 0 ? `+${fmtNum(-v)}` : '0';

  const exportExcel = async () => {
    try {
      const XLSX = await import('xlsx');
      const aoa = [['No. PO', 'Customer', 'Vendor', 'SKU', 'Serial', 'Produk', 'Size/Warna', 'Dikirim', 'Diterima', 'Selisih', 'Belum sampai']];
      filtered.forEach(r => {
        (r.items || []).forEach(it => {
          aoa.push([r.po_number, r.customer_name, r.vendor_name, it.sku, it.serial_number,
            it.product_name, `${it.size || '-'}/${it.color || '-'}`, it.shipped, it.received,
            it.variance, it.qty_short_open || 0]);
        });
        aoa.push([`TOTAL ${r.po_number}`, '', '', '', '', '', '', r.total_shipped, r.total_received,
          r.total_variance, r.qty_short_open || 0]);
      });
      const ws = XLSX.utils.aoa_to_sheet(aoa);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, 'Selisih Terima');
      XLSX.writeFile(wb, `Laporan-Selisih-Terima-${todayWIB()}.xlsx`);
    } catch (e) { toast.error('Gagal mengunduh Excel: ' + e.message); }
  };

  const exportPDF = async () => {
    try {
      const { default: jsPDF } = await import('jspdf');
      const autoTable = (await import('jspdf-autotable')).default;
      const doc = new jsPDF();
      doc.setFontSize(16); doc.setFont('helvetica', 'bold');
      doc.text('LAPORAN SELISIH KIRIM vs DITERIMA', 105, 16, { align: 'center' });
      doc.setFontSize(9); doc.setFont('helvetica', 'normal');
      doc.text(`Dicetak: ${new Date().toLocaleString('id-ID')}`, 14, 24);
      doc.text(`Total Dikirim: ${fmtNum(grandShipped)} | Total Diterima: ${fmtNum(grandReceived)} | Total Selisih: ${fmtNum(grandVariance)} pcs | Belum sampai (open): ${fmtNum(grandShortOpen)} pcs`, 14, 30);
      const body = [];
      filtered.forEach(r => {
        (r.items || []).forEach(it => {
          body.push([r.po_number, it.sku || '-', it.serial_number || '-', it.product_name || '-',
            fmtNum(it.shipped), fmtNum(it.received), varianceText(it.variance),
            fmtNum(it.qty_short_open)]);
        });
      });
      autoTable(doc, {
        startY: 36,
        head: [['No. PO', 'SKU', 'Serial', 'Produk', 'Dikirim', 'Diterima', 'Selisih', 'Belum sampai']],
        body,
        styles: { fontSize: 8 }, headStyles: { fillColor: [37, 99, 235] },
      });
      doc.save(`Laporan-Selisih-Terima-${todayWIB()}.pdf`);
    } catch (e) { toast.error('Gagal mengunduh PDF: ' + e.message); }
  };

  return (
    <div className="space-y-4" data-testid="receipt-variance-report">
      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* PANDUAN_UI G5 — kartu angka = StatTile (netral; warna hanya pada angka, nol abu) */}
        {/* Standar UI/UX v2: paling banyak 4 kartu; jumlah PO berselisih jadi keterangan kartu selisih. */}
        {[
          { label: 'Total dikirim', value: fmtNum(grandShipped), suffix: 'pcs', accent: 'default', sub: `${fmtNum(filtered.length)} PO tampil` },
          { label: 'Total diterima', value: fmtNum(grandReceived), suffix: 'pcs', accent: 'default' },
          { label: 'Total selisih dokumen', value: fmtNum(grandVariance), suffix: 'pcs', accent: grandVariance > 0 ? 'danger' : 'default', sub: `${fmtNum(poWithVariance)} PO ada selisih` },
          { label: 'Belum sampai (terbuka)', value: fmtNum(grandShortOpen), suffix: 'pcs', accent: grandShortOpen > 0 ? 'danger' : 'default' },
        ].map(s => (
          <StatTile key={s.label} label={s.label} value={s.value} suffix={s.suffix} accent={s.accent} sub={s.sub}
            testId={`variance-kpi-${s.label}`} />
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Catatan: saat buyer menerima lebih sedikit, dokumen surat jalan otomatis dikoreksi ke qty
        yang benar-benar diterima (klaim awal tersimpan di jejak audit) dan kekurangannya menjadi
        dokumen selisih <strong>SEL-BYR-…</strong> berstatus <strong>open</strong> — itulah kolom
        <strong> Belum sampai</strong> di bawah.
      </p>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="w-4 h-4 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari PO, pelanggan, vendor"
            data-testid="variance-search" className="pl-8" />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="icon" onClick={fetchData} title="Muat ulang" aria-label="Muat ulang">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button variant="outline" onClick={exportPDF} data-testid="variance-export-pdf">
            <FileDown /> Unduh PDF
          </Button>
          <Button variant="outline" onClick={exportExcel} data-testid="variance-export-excel">
            <FileSpreadsheet /> Unduh Excel
          </Button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center p-4 text-muted-foreground/70"><RefreshCw className="w-8 h-8 animate-spin mx-auto mb-3" />Memuat laporan...</div>
      ) : filtered.length === 0 ? (
        <GlassCard>
          <EmptyState icon={PackageCheck} title="Belum ada data pengiriman ke buyer"
            description={q ? 'Ubah kata pencarian untuk melihat PO lain.' : 'Laporan terisi setelah ada pengiriman ke buyer yang dicatat penerimaannya.'} />
        </GlassCard>
      ) : (
        <GlassCard className="p-0 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"></TableHead>
                <TableHead>No. PO</TableHead>
                <TableHead>Pelanggan</TableHead>
                <TableHead>Vendor</TableHead>
                <TableHead className="text-right">Dikirim</TableHead>
                <TableHead className="text-right">Diterima</TableHead>
                <TableHead className="text-right">Selisih</TableHead>
                <TableHead className="text-right">Belum sampai</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(r => {
                const key = r.po_id || r.po_number;
                const isOpen = expanded[key];
                return (
                  <Fragment key={key}>
                    <TableRow className="hover:bg-muted/60 cursor-pointer" onClick={() => toggle(key)} data-testid={`variance-po-row-${r.po_number}`}>
                      <TableCell className="px-2 text-muted-foreground/70">{isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</TableCell>
                      <TableCell className="px-3 py-2.5 font-bold text-[hsl(var(--primary))]">{r.po_number || '-'}</TableCell>
                      <TableCell className="px-3 py-2.5 text-foreground/90">{r.customer_name || '-'}</TableCell>
                      <TableCell className="px-3 py-2.5 text-muted-foreground">{r.vendor_name || '-'}</TableCell>
                      <TableCell className="px-3 py-2.5 text-right font-semibold text-[hsl(var(--success-text))]">{fmtNum(r.total_shipped)}</TableCell>
                      <TableCell className="px-3 py-2.5 text-right font-semibold text-[hsl(var(--primary))]">{fmtNum(r.total_received)}</TableCell>
                      <TableCell className={`px-3 py-2.5 text-right font-bold ${varianceClass(r.total_variance)}`}>
                        {(r.total_variance || 0) !== 0 && <AlertTriangle className="w-3.5 h-3.5 inline mr-1" />}
                        {varianceText(r.total_variance)}
                      </TableCell>
                      <TableCell className={`px-3 py-2.5 text-right font-bold ${(r.qty_short_open || 0) > 0 ? 'text-[hsl(var(--danger-text))] bg-[hsl(var(--destructive)/0.1)]' : 'text-muted-foreground/70'}`}
                        data-testid={`variance-short-${r.po_number}`}>
                        {fmtNum(r.qty_short_open)}
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow key={`${key}-detail`}>
                        <TableCell colSpan={8} className="bg-foreground/[0.03] px-6 py-3">
                          <Table>
                            <TableHeader>
                              <TableRow className="text-muted-foreground border-b border-border">
                                <TableHead className="text-left py-1.5 px-2">Serial</TableHead>
                                <TableHead className="text-left py-1.5 px-2">SKU</TableHead>
                                <TableHead className="text-left py-1.5 px-2">Produk</TableHead>
                                <TableHead className="text-right py-1.5 px-2">Dikirim</TableHead>
                                <TableHead className="text-right py-1.5 px-2">Diterima</TableHead>
                                <TableHead className="text-right py-1.5 px-2">Selisih</TableHead>
                                <TableHead className="text-right py-1.5 px-2">Belum sampai</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {(r.items || []).map((it, i) => (
                                <TableRow key={i}>
                                  <TableCell className="py-1.5 px-2 tabular-nums text-[hsl(var(--warning-text))]">{it.serial_number || '—'}</TableCell>
                                  <TableCell className="py-1.5 px-2 tabular-nums text-[hsl(var(--primary))]">{it.sku || '-'}</TableCell>
                                  <TableCell className="py-1.5 px-2 text-foreground/90">{it.product_name} <span className="text-muted-foreground/70">{it.size}/{it.color}</span></TableCell>
                                  <TableCell className="py-1.5 px-2 text-right text-[hsl(var(--success-text))]">{fmtNum(it.shipped)}</TableCell>
                                  <TableCell className="py-1.5 px-2 text-right text-[hsl(var(--primary))]">{fmtNum(it.received)}</TableCell>
                                  <TableCell className={`py-1.5 px-2 text-right font-semibold ${varianceClass(it.variance)}`}>{varianceText(it.variance)}</TableCell>
                                  <TableCell className={`py-1.5 px-2 text-right font-semibold ${(it.qty_short_open || 0) > 0 ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground/70'}`}>{fmtNum(it.qty_short_open)}</TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                          {(r.short_docs || []).filter(d => d.status === 'open').length > 0 && (
                            <div className="mt-2 text-xs text-[hsl(var(--danger-text))]">
                              Dokumen selisih terbuka:{' '}
                              {(r.short_docs || []).filter(d => d.status === 'open')
                                .map(d => `${d.short_number} (${d.sku} · ${fmtNum(d.qty_open)} pcs)`).join(' · ')}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </GlassCard>
      )}
    </div>
  );
}
