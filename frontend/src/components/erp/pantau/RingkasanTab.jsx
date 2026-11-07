/**
 * Pantau Produksi › Ringkasan — alur barang, pemeriksa keseimbangan (menyebut PO penyebab), PO lewat batas
 * kirim, selesai hari ini / 7 hari, batas kirim ≤ 14 hari, peringatan seri dobel.
 * Gabungan Ringkasan pemilik (Monitoring CMT) + Pusat Kendali. Muat ulang otomatis tiap 30 detik.
 */
import { Fragment, useState } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, ClipboardList, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile } from '../moduleAtoms';
import { formatDateID, formatRupiah } from '@/lib/format';
import {
  Badge, LoadingRows, RISK_META, RefreshButton, Section, Signed, n, pct, poStatusLabel, portalBusinessType, useApi,
} from './pantauShared';

export default function RingkasanTab(props) {
  const bt = portalBusinessType(props);
  const { onNavigate } = props;
  const { data, loading, error, reload } = useApi(`/pantau/ringkasan?business_type=${bt}&days=7`, { auto: 30000 });
  const [openCheck, setOpenCheck] = useState('');
  const k = data?.kpi || {};
  const done = data?.done || {};
  const jobs = data?.jobs || {};
  const biaya = data?.biaya || {};
  const dup = data?.duplicate_serials || { count: 0, items: [] };
  const go = (m) => onNavigate && m && onNavigate(m);

  return (
    <PageLayout
      testId="pantau-ringkasan"
      title="Ringkasan"
      subtitle="Barang yang sedang berada di tiap tahap, dan PO yang perlu dikejar."
      tools={<RefreshButton onClick={reload} loading={loading} testId="pantau-ringkasan-refresh" />}
      summary={<>
        {error && <Notice tone="danger" icon={AlertCircle}>{error}</Notice>}
        {data && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="pantau-ringkasan-kpi">
            <StatTile label="PO berjalan" value={n(k.po_berjalan)} sub={`${n(k.qty_berjalan)} pcs dipesan · lolos QC ${pct(k.progress_pct)}`} testId="kpi-po-berjalan" />
            <StatTile label="Di vendor CMT" value={n(k.di_cmt)} sub="pcs potongan belum disetor" accent={k.di_cmt ? 'warning' : 'muted'} testId="kpi-di-cmt" />
            <StatTile label="Sedang QC" value={n(k.in_qc)} sub="pcs sudah di DA, belum selesai diperiksa" accent={k.in_qc ? 'warning' : 'muted'} testId="kpi-in-qc" />
            <StatTile label="Lewat batas kirim" value={n(k.telat)} sub={`${n(k.berisiko)} PO berisiko telat · ditolak QC ${pct(k.reject_rate)}`} accent={k.telat ? 'danger' : 'muted'} testId="kpi-telat" />
          </div>
        )}
      </>}
    >
      {loading && !data ? <Section><LoadingRows /></Section> : data && <>
        <Section title="Alur barang" hint="Jumlah barang yang SEDANG berada di tiap tahap (PO berjalan)." testId="pantau-alur"
          unduh={{ namaBerkas: 'alur-barang', baris: data.alur || [], kolom: [
            { label: 'Tahap', nilai: (s) => s.label }, { label: 'Pcs', nilai: (s) => Number(s.qty) || 0 },
            { label: 'Dokumen', nilai: (s) => Number(s.docs) || 0 }, { label: 'Jenis dokumen', nilai: (s) => s.doc_label || '' },
            { label: 'Catatan', nilai: (s) => s.note || '' },
          ] }}>
          <Table data-testid="pantau-alur-table">
            <TableHeader><TableRow>
              <TableHead>Tahap</TableHead><TableHead className="text-right">Pcs</TableHead>
              <TableHead className="text-right">Dokumen</TableHead><TableHead>Keterangan</TableHead><TableHead className="text-right">Buka</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.alur.map((s) => (
                <TableRow key={s.key} data-testid={`pantau-alur-${s.key}`}>
                  <TableCell className="font-medium">{s.label}</TableCell>
                  <TableCell className="text-right tabular-nums font-semibold" data-testid={`pantau-alur-${s.key}-qty`}>{n(s.qty)}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{n(s.docs)} {s.doc_label}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.note || ''}</TableCell>
                  <TableCell className="text-right">
                    {s.module && s.module !== 'pantau-produksi' && (
                      <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => go(s.module)}>Buka</Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>

        <Section title="Pemeriksa keseimbangan" hint="Angka antartahap harus cocok; yang tidak cocok menyebut PO penyebabnya." testId="pantau-balance">
          {data.balance?.all_ok && (
            <div className="p-4"><Notice tone="success" icon={CheckCircle2} testId="pantau-balance-ok">Semua angka seimbang — lima pemeriksaan cocok.</Notice></div>
          )}
          <Table data-testid="pantau-balance-table">
            <TableHeader><TableRow>
              <TableHead className="w-10" /><TableHead>Pemeriksaan</TableHead><TableHead className="text-right">Kiri</TableHead>
              <TableHead className="text-right">Kanan</TableHead><TableHead>Hasil</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {(data.balance?.checks || []).map((c) => {
                const open = openCheck === c.key;
                return (
                  <Fragment key={c.key}>
                    <TableRow data-testid={`pantau-balance-${c.key}`}>
                      <TableCell>{!c.ok && <RowToggle open={open} onClick={() => setOpenCheck(open ? '' : c.key)} label="Lihat PO penyebab" testId={`pantau-balance-toggle-${c.key}`} />}</TableCell>
                      <TableCell>{c.label}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(c.left)}</TableCell>
                      <TableCell className="text-right tabular-nums">{n(c.right)}</TableCell>
                      <TableCell>{c.ok
                        ? <Badge meta={{ label: 'Cocok', tone: 'success' }} />
                        : <Badge meta={{ label: `${n(c.offender_count)} PO tidak cocok`, tone: 'danger' }} />}</TableCell>
                    </TableRow>
                    {open && (
                      <RowDetail colSpan={5} testId={`pantau-balance-offenders-${c.key}`}>
                        <Table>
                          <TableHeader><TableRow>
                            <TableHead>PO</TableHead><TableHead className="text-right">Kiri</TableHead>
                            <TableHead className="text-right">Kanan</TableHead><TableHead className="text-right">Selisih</TableHead>
                          </TableRow></TableHeader>
                          <TableBody>
                            {c.offenders.map((o) => (
                              <TableRow key={o.po_id}>
                                <TableCell className="font-medium">{o.po_number}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(o.left)}</TableCell>
                                <TableCell className="text-right tabular-nums">{n(o.right)}</TableCell>
                                <TableCell className="text-right"><Signed v={o.diff} /></TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                        <p className="text-xs text-muted-foreground mt-2">Periksa rincian PO di tab Per PO. Penyebab umum: CMT menyetor dua kali, kiriman dibuat sebelum QC, atau penerimaan belum selesai QC.</p>
                      </RowDetail>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </Section>

        <Section title="Lewat batas kirim & berisiko" hint="Batas kirim = tanggal kirim ke pemesan; berisiko = ≤ 5 hari dan lolos QC < 70%." testId="pantau-overdue"
          unduh={{ namaBerkas: 'po-lewat-batas-kirim', baris: data.overdue, kolom: [
            { label: 'PO', nilai: (r) => r.po_number }, { label: 'Pemesan', nilai: (r) => r.customer_name || '' },
            { label: 'Vendor CMT', nilai: (r) => r.vendor_name || '' }, { label: 'Status PO', nilai: (r) => poStatusLabel(r.status) },
            { label: 'Batas kirim', nilai: (r) => formatDateID(r.deadline, { fallback: '' }) },
            { label: 'Sisa hari', nilai: (r) => (r.days_to_deadline == null ? '' : Number(r.days_to_deadline)) },
            { label: 'Dipesan', nilai: (r) => Number(r.ordered) || 0 }, { label: 'Lolos QC', nilai: (r) => Number(r.accepted) || 0 },
            { label: 'Keadaan', nilai: (r) => (RISK_META[r.risk] || {}).label || '' },
          ] }}>
          {data.overdue.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="Tidak ada PO yang telat atau berisiko" description="Semua PO berjalan masih sesuai jadwal." />
          ) : (
            <PoRiskTable rows={data.overdue} testId="pantau-overdue-table" />
          )}
        </Section>

        <Notice tone="info" icon={ClipboardList} testId="pantau-selesai">
          Hari ini <b className="tabular-nums" data-testid="pantau-qc-today">{n(done.qc_today)}</b> pcs lolos QC dan {n(done.jobs_today)} job jahit selesai.
          {' '}{data.window_days} hari terakhir: <b className="tabular-nums" data-testid="pantau-qc-window">{n(done.qc_window)}</b> pcs lolos QC, {n(done.jobs_window)} job selesai.
          {' '}Job jahit: {n(jobs.belum)} belum mulai · {n(jobs.jalan)} berjalan · {n(jobs.selesai)} selesai.
          {' '}Ongkos jahit terhitung {formatRupiah(biaya.ongkos_jahit)} · biaya permak {formatRupiah(biaya.biaya_permak)} ({n(biaya.permak_aktif)} aktif)
          {biaya.komponen_kurang ? ` · ${n(biaya.komponen_kurang)} permintaan komponen kurang (${n(biaya.komponen_kurang_qty)} pcs belum diterima)` : ''}.
        </Notice>

        <Section title="Batas kirim dalam 14 hari" testId="pantau-upcoming"
          unduh={{ namaBerkas: 'po-batas-kirim-14-hari', baris: data.upcoming, kolom: [
            { label: 'PO', nilai: (r) => r.po_number }, { label: 'Pemesan', nilai: (r) => r.customer_name || '' },
            { label: 'Vendor CMT', nilai: (r) => r.vendor_name || '' }, { label: 'Status PO', nilai: (r) => poStatusLabel(r.status) },
            { label: 'Batas kirim', nilai: (r) => formatDateID(r.deadline, { fallback: '' }) },
            { label: 'Sisa hari', nilai: (r) => (r.days_to_deadline == null ? '' : Number(r.days_to_deadline)) },
            { label: 'Dipesan', nilai: (r) => Number(r.ordered) || 0 }, { label: 'Lolos QC', nilai: (r) => Number(r.accepted) || 0 },
            { label: 'Keadaan', nilai: (r) => (RISK_META[r.risk] || {}).label || '' },
          ] }}>
          {data.upcoming.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="Tidak ada batas kirim dalam 14 hari" description="PO dengan batas kirim dekat akan muncul di sini." />
          ) : (
            <PoRiskTable rows={data.upcoming} testId="pantau-upcoming-table" />
          )}
        </Section>

        {dup.count > 0 && (
          <Section title="Seri dobel" hint="Nomor seri yang dipakai lebih dari satu baris PO." testId="pantau-seri-dobel"
            unduh={{ namaBerkas: 'seri-dobel', baris: dup.items || [], kolom: [
              { label: 'Nomor seri', nilai: (d) => d.serial || '' }, { label: 'Dipakai', nilai: (d) => (d.usages || []).length },
              { label: 'Di PO', nilai: (d) => (d.usages || []).map((u) => `${u.po_number} · ${u.sku || u.product_name}${u.size ? ` ${u.size}` : ''}`).join(' | ') },
            ] }}>
            <div className="p-4 pb-0"><Notice tone="warning" icon={Copy}>{n(dup.count)} nomor seri dipakai di lebih dari satu baris PO — periksa supaya hasil jahit tidak tertukar.</Notice></div>
            <Table data-testid="pantau-seri-table">
              <TableHeader><TableRow>
                <TableHead>Nomor seri</TableHead><TableHead className="text-right">Dipakai</TableHead><TableHead>Di PO</TableHead>
              </TableRow></TableHeader>
              <TableBody>
                {dup.items.map((d) => (
                  <TableRow key={d.serial}>
                    <TableCell className="font-medium">{d.serial}</TableCell>
                    <TableCell className="text-right tabular-nums">{n(d.count)}×</TableCell>
                    <TableCell className="text-xs">{d.usages.map((u) => `${u.po_number} · ${u.sku || u.product_name}${u.size ? ` ${u.size}` : ''}`).join(' | ')}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>
        )}
        {!data.balance?.all_ok && (
          <Notice tone="warning" icon={AlertTriangle}>Ada pemeriksaan yang tidak cocok. Buka baris pemeriksaan di atas untuk melihat PO penyebabnya.</Notice>
        )}
      </>}
    </PageLayout>
  );
}

function PoRiskTable({ rows, testId }) {
  return (
    <Table data-testid={testId}>
      <TableHeader><TableRow>
        <TableHead>PO</TableHead><TableHead>Vendor CMT</TableHead><TableHead>Status PO</TableHead><TableHead>Batas kirim</TableHead>
        <TableHead className="text-right">Sisa hari</TableHead><TableHead className="text-right">Dipesan</TableHead>
        <TableHead className="text-right">Lolos QC</TableHead><TableHead>Keadaan</TableHead>
      </TableRow></TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.po_id} data-testid={`${testId}-${r.po_number}`}>
            <TableCell className="font-medium whitespace-nowrap">{r.po_number}<div className="text-xs text-muted-foreground">{r.customer_name}</div></TableCell>
            <TableCell>{r.vendor_name || '—'}</TableCell>
            <TableCell>{poStatusLabel(r.status)}</TableCell>
            <TableCell className="whitespace-nowrap">{r.deadline ? formatDateID(r.deadline) : '—'}</TableCell>
            <TableCell className={`text-right tabular-nums ${r.days_to_deadline < 0 ? 'text-[hsl(var(--danger-text))] font-semibold' : ''}`}>
              {r.days_to_deadline == null ? '—' : r.days_to_deadline < 0 ? `telat ${n(-r.days_to_deadline)}` : n(r.days_to_deadline)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{n(r.ordered)}</TableCell>
            <TableCell className="text-right tabular-nums">{n(r.accepted)} <span className="text-muted-foreground text-xs">({pct(r.progress_pct)})</span></TableCell>
            <TableCell><Badge meta={RISK_META[r.risk]} /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
