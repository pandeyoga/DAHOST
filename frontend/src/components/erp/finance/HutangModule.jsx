/**
 * Hutang — Portal Keuangan › Hutang (11 Nov 2026, owner).
 *
 * Owner: "tagihan tidak usah beda tab … jangan malah tab, lebih baik filter saja … nama menunya hutang piutang saja".
 * Dulu menu "Hutang Pemasok & CMT" punya 3 tab (Tagihan [+ pil Daftar tagihan / Penerimaan belum difakturkan],
 * Hutang CMT terjadwal, Umur hutang). Kini SATU daftar semua hutang dengan penyaring:
 *   • status  — Belum lunas (bawaan) · Terjadwal · Belum difakturkan · Belum dibayar · Dibayar sebagian ·
 *               Lewat jatuh tempo · Lunas · Semua;
 *   • jenis   — Pemasok / CMT;  • nama pemasok / CMT;  • cari;
 *   • CV      — pilihan CV Portal Keuangan di bagian atas (header X-CV, tidak dibuat dua kali); Gabungan → kolom CV.
 * Isi daftar:
 *   • faktur pemasok            (/api/rahaza/ap-invoices)
 *   • tagihan CMT               (/api/production/cmt-billing) — hutang nyata, lahir saat barang lolos QC;
 *   • terjadwal                 (/api/production/cmt-billing/schedules?perkiraan_internal=1) — upah jahit barang yang
 *                                masih di CMT: jadwal PO maklon (CV Sukma) + PERKIRAAN PO DA. Tanpa tombol Bayar;
 *   • penerimaan belum difakturkan (/api/rahaza/grs/available-for-invoice) — tombol Buat faktur.
 * Umur: baris terjadwal = hari sejak kirim ke CMT (hijau 0–7 · kuning 8–14 · merah > 14, seperti Excel owner);
 * tagihan = dari jatuh tempo. Ringkasan di slot `summary`; rincian dibuka sebagai popup (keputusan owner 8 Nov).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, HandCoins, Receipt, RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PageLayout, { DetailPanel } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import {
  CMT_PAYABLE, CreateInvoicePanel, InvoiceDetail, PayInvoiceModal, canPay, cmtPayable, cmtToRow,
} from '../procurement/SupplierInvoiceModule';
import { JadwalBarisBarang, sisaJadwal } from '../engine/JadwalHutangCmtTabel';
import { apiGet, apiPost } from '../../../lib/api';
import { currentRole } from '../portalAccess';
import { isFinanceRole } from '../../../lib/financeRoles';
import { CV_ALL, ownerLabel, useCvOr } from '@/lib/entitas';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { ambilPetunjukTab } from '../hubs/petunjukTab';
import { KELOMPOK_KIRIM, UmurJatuhTempo, UmurKirim, hariTerlambat, jumlahPerKelompokKirim, teksJatuhTempo } from './umurTagihan';

const fmt = formatRupiah;

export const STATUS_HUTANG = {
  terjadwal: { label: 'Terjadwal', tone: 'info' },
  belum_difakturkan: { label: 'Belum difakturkan', tone: 'muted' },
  draf: { label: 'Faktur draf', tone: 'muted' },
  belum_dibayar: { label: 'Belum dibayar', tone: 'warning' },
  sebagian: { label: 'Dibayar sebagian', tone: 'warning' },
  lunas: { label: 'Lunas', tone: 'success' },
  batal: { label: 'Dibatalkan', tone: 'muted' },
};
const TERBUKA = new Set(['terjadwal', 'belum_difakturkan', 'draf', 'belum_dibayar', 'sebagian']);
const TAGIHAN_TERBUKA = new Set(['belum_dibayar', 'sebagian']);
const JENIS = { pemasok: 'Pemasok', cmt: 'CMT' };

// ─── Baris daftar (satu bentuk untuk empat sumber) ────────────────────────────
export function barisFakturPemasok(i, hariIni = todayWIB()) {
  const st = String(i.status || '').toLowerCase();
  const total = Number(i.total || 0);
  const dibayar = Number(i.paid_amount || 0);
  const sisa = Math.max(Number(i.balance ?? total - dibayar) || 0, 0);
  const status = st === 'draft' ? 'draf' : st === 'paid' ? 'lunas' : ['cancelled', 'void'].includes(st) ? 'batal'
    : st === 'partial_paid' ? 'sebagian' : sisa <= 0.5 ? 'lunas' : 'belum_dibayar';
  return {
    key: `ap-${i.id}`, src: 'ap', jenis: 'pemasok', status, nomor: i.invoice_number, pihak: i.vendor_name || '(tanpa nama)',
    ref: (i.po_numbers || []).join(', ') || (i.gr_numbers || []).join(', '), tanggal: i.issue_date, jatuhTempo: i.due_date,
    total, dibayar, sisa: TERBUKA.has(status) ? sisa : 0, entity: i.entity || 'DA', antarCv: !!i.intercompany,
    terlambat: TAGIHAN_TERBUKA.has(status) ? hariTerlambat(i.due_date, hariIni) : null,
    raw: { ...i, kind: 'ap' },
  };
}

export function barisTagihanCmt(p, hariIni = todayWIB()) {
  const r = cmtToRow(p);
  const st = r.status;
  const sisa = Math.max(Number(r.balance ?? 0) || 0, 0);
  const status = st === 'paid' ? 'lunas' : ['cancelled', 'void', 'voided'].includes(st) ? 'batal'
    : st === 'partial_paid' ? 'sebagian' : sisa <= 0.5 ? 'lunas' : 'belum_dibayar';
  const jatuhTempo = r.due_date || r.issue_date;   // sama dengan core.payables: tagihan CMT jatuh tempo saat terbit
  return {
    key: `cmt-${r.id}`, src: 'cmt', jenis: 'cmt', status, nomor: r.invoice_number, pihak: r.vendor_name || '(tanpa nama)',
    ref: (r.po_numbers || []).join(', '), tanggal: r.issue_date, jatuhTempo, total: Number(r.total || 0),
    dibayar: Number(r.paid_amount || 0), sisa: TERBUKA.has(status) ? sisa : 0, entity: r.entity, antarCv: r.intercompany,
    belumDijurnal: !r.gl_posted && TERBUKA.has(status),
    terlambat: TAGIHAN_TERBUKA.has(status) ? hariTerlambat(jatuhTempo, hariIni) : null,
    raw: r,
  };
}

/** Jadwal hutang CMT / perkiraan PO DA → baris "Terjadwal" (hanya yang masih punya sisa belum jatuh tempo). */
export function barisJadwalCmt(s) {
  return {
    key: `jadwal-${s.id}`, src: 'jadwal', jenis: 'cmt', status: 'terjadwal', nomor: s.po_number,
    pihak: s.vendor_name || 'Vendor belum ditentukan',
    ref: `${Number(s.remaining_qty ?? Math.max(0, Number(s.scheduled_qty || 0) - Number(s.matured_pcs || 0))).toLocaleString('id-ID')} pcs belum lolos QC`,
    tanggal: s.kirim_pertama, jatuhTempo: null,
    total: Number(s.scheduled_amount || 0), dibayar: 0, sisa: Number(sisaJadwal(s) || 0), entity: s.entity,
    perkiraan: s.jenis === 'perkiraan', umurKirim: { hari: s.umur_kirim_hari ?? null, kelompok: s.umur_kirim || null },
    terlambat: null, raw: s,
  };
}

export function barisPenerimaan(g) {
  const nilai = Number(g.receivable_amount || 0);
  return {
    key: `gr-${g.id}`, src: 'gr', jenis: 'pemasok', status: 'belum_difakturkan', nomor: g.receipt_number,
    pihak: g.supplier_name || '(tanpa nama)', ref: g.po_number || '', tanggal: g.received_at, jatuhTempo: null,
    total: nilai, dibayar: 0, sisa: nilai, entity: null, terlambat: null, raw: g,
  };
}

/** Semua baris Hutang dari empat sumber; jadwal tanpa sisa tidak ikut (seluruhnya sudah jadi tagihan). */
export function susunHutang({ faktur = [], cmt = [], jadwal = [], penerimaan = [] }, hariIni = todayWIB()) {
  return [
    ...faktur.map((i) => barisFakturPemasok(i, hariIni)),
    ...cmt.map((p) => barisTagihanCmt(p, hariIni)),
    ...jadwal.filter((s) => Number(sisaJadwal(s) || 0) > 0.5).map(barisJadwalCmt),
    ...penerimaan.map(barisPenerimaan),
  ];
}

/** Belum lunas di atas (yang paling lama menunggu dulu), lalu yang sudah selesai (terbaru dulu). */
export function urutkanHutang(rows) {
  const acuan = (r) => String(r.jatuhTempo || r.tanggal || '9999');
  return [...rows].sort((a, b) => {
    const ta = TERBUKA.has(a.status) ? 0 : 1;
    const tb = TERBUKA.has(b.status) ? 0 : 1;
    if (ta !== tb) return ta - tb;
    return ta === 0 ? acuan(a).localeCompare(acuan(b)) : String(b.tanggal || '').localeCompare(String(a.tanggal || ''));
  });
}

export function cocokStatus(r, status) {
  if (!status || status === 'terbuka') return TERBUKA.has(r.status);
  if (status === 'semua') return true;
  if (status === 'lewat') return TAGIHAN_TERBUKA.has(r.status) && Number(r.terlambat) > 0;
  return r.status === status;
}

/** Ringkasan (mengikuti penyaring jenis / nama / cari, tidak mengikuti pil status). */
export function ringkasHutang(rows) {
  const jumlah = (f) => rows.filter(f).reduce((t, r) => t + Number(r.sisa || 0), 0);
  return {
    belumDibayar: jumlah((r) => TAGIHAN_TERBUKA.has(r.status)),
    lewat: jumlah((r) => TAGIHAN_TERBUKA.has(r.status) && Number(r.terlambat) > 0),
    terjadwal: jumlah((r) => r.status === 'terjadwal'),
    belumDifakturkan: jumlah((r) => r.status === 'belum_difakturkan'),
    draf: jumlah((r) => r.status === 'draf'),
    totalTerbuka: jumlah((r) => TERBUKA.has(r.status)),
    perCv: {
      DA: jumlah((r) => TERBUKA.has(r.status) && r.entity === 'DA'),
      SMU: jumlah((r) => TERBUKA.has(r.status) && r.entity === 'SMU'),
    },
    kirim: jumlahPerKelompokKirim(rows.filter((r) => r.status === 'terjadwal'), (r) => r.sisa),
    belumDijurnal: rows.filter((r) => r.belumDijurnal),
  };
}


/** Petunjuk dari tautan lama (makeRedirect `fin-ap-hub` + tab / Beranda Keuangan) → pil status awal. */
const PETUNJUK_TAB = {
  aging: 'belum_dibayar', bills: 'terbuka', 'cmt-terjadwal': 'terjadwal', lewat: 'lewat',
  belum_dibayar: 'belum_dibayar', terjadwal: 'terjadwal', belum_difakturkan: 'belum_difakturkan',
};

// ─── Rincian popup ─────────────────────────────────────────────────────────────
function RincianTerjadwal({ row, onClose }) {
  const s = row.raw;
  return (
    <DetailPanel testId="hutang-rincian-jadwal" onClose={onClose}
      title={`${row.perkiraan ? 'Perkiraan hutang jahit' : 'Jadwal hutang CMT'} ${s.po_number}`}
      description={`${row.pihak} · ${ownerLabel(s.entity)}`}>
      <p className="text-sm text-muted-foreground">
        Jadwal (qty × upah) <b className="text-foreground tabular-nums">{fmt(s.scheduled_amount)}</b> · sudah lolos QC
        (jadi tagihan) <b className="text-foreground tabular-nums">{fmt(s.matured_amount)}</b> · belum jatuh tempo
        {' '}<b className="text-foreground tabular-nums">{fmt(row.sisa)}</b>.
        {s.kirim_pertama && <> Dikirim ke CMT {formatDateID(s.kirim_pertama)}.</>}
      </p>
      <p className="text-sm text-muted-foreground">
        {row.perkiraan
          ? 'Perkiraan PO DA: dihitung dari pcs di penjahit × upah jahit, tidak disimpan dan tanpa jurnal.'
          : 'Belum bisa dibayar: hutang nyata lahir saat barang lolos QC dan tampil sebagai tagihan CMT di daftar ini.'}
      </p>
      <JadwalBarisBarang lines={s.lines} testId="hutang-rincian-jadwal-barang" />
    </DetailPanel>
  );
}

function RincianTagihanCmt({ row, finance, onClose, onPay, onPost }) {
  const r = row.raw;
  const bisaBayar = cmtPayable(r);
  return (
    <DetailPanel testId="hutang-rincian-cmt" onClose={onClose} title={`Tagihan CMT ${r.invoice_number}`}
      description={`${row.pihak} · ${ownerLabel(r.entity)}`}
      actions={finance && <>
        {row.belumDijurnal && <Button variant="outline" onClick={() => onPost(row)} data-testid="hutang-rincian-cmt-jurnal">Jurnal</Button>}
        {CMT_PAYABLE.includes(r.status) && row.sisa > 0 && (
          <Button variant="success" onClick={() => onPay(row)} data-testid="hutang-rincian-cmt-bayar"><HandCoins className="w-4 h-4" />Bayar</Button>
        )}
      </>}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div><div className="text-xs text-muted-foreground">PO</div><div className="font-medium">{row.ref || '—'}</div></div>
        <div><div className="text-xs text-muted-foreground">Tanggal</div><div>{row.tanggal ? formatDateID(row.tanggal) : '—'}</div></div>
        <div><div className="text-xs text-muted-foreground">Pcs lolos QC</div><div className="tabular-nums">{Number(r.total_pcs || 0).toLocaleString('id-ID')}</div></div>
        <div><div className="text-xs text-muted-foreground">Jurnal</div><div>{r.gl_posted ? 'Sudah dijurnal' : 'Belum dijurnal'}</div></div>
        <div><div className="text-xs text-muted-foreground">Total</div><div className="tabular-nums">{fmt(r.total)}</div></div>
        <div><div className="text-xs text-muted-foreground">Dibayar</div><div className="tabular-nums">{fmt(r.paid_amount)}</div></div>
        <div><div className="text-xs text-muted-foreground">Tertahan selisih</div><div className="tabular-nums">{fmt(r.blocked_amount)}</div></div>
        <div><div className="text-xs text-muted-foreground">Bisa dibayar</div><div className="font-semibold tabular-nums">{fmt(bisaBayar)}</div></div>
      </div>
      {Number(r.blocked_amount || 0) > 0 && (
        <p className="text-xs text-muted-foreground">Bagian yang tertahan karena selisih tagihan diselesaikan di Portal Produksi/Maklon › Tagihan CMT.</p>
      )}
    </DetailPanel>
  );
}

// ─── Layar ─────────────────────────────────────────────────────────────────────
export default function HutangModule({ token, initialStatus }) {
  const cv = useCvOr();
  const gabungan = cv === CV_ALL;
  const finance = isFinanceRole(currentRole());
  const [data, setData] = useState({ faktur: [], cmt: [], jadwal: [], penerimaan: [] });
  const [loading, setLoading] = useState(true);
  const [gagal, setGagal] = useState([]);
  const [status, setStatus] = useState(() => initialStatus || PETUNJUK_TAB[ambilPetunjukTab('fin-ap-hub')] || 'terbuka');
  const [jenis, setJenis] = useState('');
  const [pihak, setPihak] = useState('');
  const [cari, setCari] = useState('');
  const [rincian, setRincian] = useState(null);
  const [buatFaktur, setBuatFaktur] = useState(null);
  const [bayar, setBayar] = useState(null);
  const [menyetujui, setMenyetujui] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const sumber = [
      ['faktur', 'faktur pemasok', '/api/rahaza/ap-invoices?limit=5000', (d) => (Array.isArray(d) ? d : d?.items || [])],
      ['cmt', 'tagihan CMT', '/api/production/cmt-billing?business_type=all', (d) => d?.items || []],
      ['jadwal', 'hutang CMT terjadwal', '/api/production/cmt-billing/schedules?perkiraan_internal=1', (d) => d?.items || []],
      ['penerimaan', 'penerimaan belum difakturkan', '/api/rahaza/grs/available-for-invoice', (d) => d?.items || []],
    ];
    const hasil = await Promise.all(sumber.map(async ([key, label, url, ambil]) => {
      try { return [key, ambil(await apiGet(url)), null]; } catch (e) { return [key, [], `${label}: ${e?.message || e}`]; }
    }));
    setData(Object.fromEntries(hasil.map(([k, v]) => [k, v])));
    const err = hasil.map(([, , e]) => e).filter(Boolean);
    setGagal(err);
    if (err.length) toast.error(`Sebagian data hutang gagal dimuat: ${err.join('; ')}`);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const semua = useMemo(() => urutkanHutang(susunHutang(data)), [data]);
  // penyaring selain status — dasar hitungan pil dan ringkasan
  const dasar = useMemo(() => {
    const s = cari.trim().toLowerCase();
    return semua.filter((r) => (!jenis || r.jenis === jenis) && (!pihak || r.pihak === pihak)
      && (!s || [r.nomor, r.pihak, r.ref].filter(Boolean).some((v) => String(v).toLowerCase().includes(s))));
  }, [semua, jenis, pihak, cari]);
  const rows = useMemo(() => dasar.filter((r) => cocokStatus(r, status)), [dasar, status]);
  const hitung = (st) => dasar.filter((r) => cocokStatus(r, st)).length;
  const ringkas = useMemo(() => ringkasHutang(dasar), [dasar]);
  const daftarPihak = useMemo(() => [...new Set(semua.filter((r) => !jenis || r.jenis === jenis).map((r) => r.pihak))]
    .sort((a, b) => a.localeCompare(b, 'id')), [semua, jenis]);
  const { page, setPage, totalPages, paged, pageSize } = useClientPagination(rows, 25);
  useEffect(() => { setPage(1); }, [status, jenis, pihak, cari, setPage]);

  const pilStatus = [
    { key: 'terbuka', label: 'Belum lunas' }, { key: 'terjadwal', label: 'Terjadwal' },
    { key: 'belum_difakturkan', label: 'Belum difakturkan' }, { key: 'draf', label: 'Faktur draf' },
    { key: 'belum_dibayar', label: 'Belum dibayar' }, { key: 'sebagian', label: 'Dibayar sebagian' },
    { key: 'lewat', label: 'Lewat jatuh tempo' }, { key: 'lunas', label: 'Lunas' }, { key: 'semua', label: 'Semua' },
  ].map((o) => ({ ...o, count: hitung(o.key) }))
    .filter((o) => o.key !== 'draf' || o.count > 0 || status === 'draf');

  const setujui = async (inv) => {
    setMenyetujui(true);
    try {
      const out = await apiPost(`/api/rahaza/ap-invoices/${inv.id}/send`, {});
      const posting = out?._posting_result;
      if (posting?.ok) toast.success(`Faktur ${inv.invoice_number} disetujui & dicatat ke buku besar`);
      else {
        toast.warning(`Faktur ${inv.invoice_number} disetujui, tetapi BELUM tercatat ke buku besar: `
          + `${posting?.error || 'hasil posting tidak diketahui'}. Perbaiki penyebabnya lalu posting ulang.`, { duration: 10000 });
      }
      setRincian(null);
      await load();
    } catch (e) { toast.error(e.message); } finally { setMenyetujui(false); }
  };
  const jurnalCmt = async (row) => {
    try {
      const out = await apiPost(`/api/dewi/maklon/finance/cmt-payments/${row.raw.id}/post-ap`, {});
      toast.success(`Tagihan CMT ${row.nomor} dijurnal${out?.je_number ? ` · ${out.je_number}` : ''}`);
      setRincian(null);
      await load();
    } catch (e) { toast.error(e.message); }
  };
  const bisaBayar = (r) => finance && (r.src === 'cmt'
    // tombol ada selama masih bersisa; dialog menjelaskan bila semuanya tertahan (bisa dibayar 0)
    ? CMT_PAYABLE.includes(r.raw.status) && r.sisa > 0
    : r.src === 'ap' && canPay(r.raw));
  const buka = (r) => (r.src === 'gr' ? setBuatFaktur(r.raw) : setRincian(r));

  const kolom = 8;
  const detail = rincian && (
    rincian.src === 'ap' ? (
      <InvoiceDetail inv={rincian.raw} token={token} onClose={() => setRincian(null)} onSend={setujui} sending={menyetujui}
        onPay={finance ? (inv) => { setRincian(null); setBayar(inv); } : null} />
    ) : rincian.src === 'cmt' ? (
      <RincianTagihanCmt row={rincian} finance={finance} onClose={() => setRincian(null)} onPost={jurnalCmt}
        onPay={(r) => { setRincian(null); setBayar(r.raw); }} />
    ) : <RincianTerjadwal row={rincian} onClose={() => setRincian(null)} />
  );

  return (
    <PageLayout
      testId="fin-hutang"
      title="Hutang"
      subtitle="Semua hutang ke pemasok dan CMT dalam satu daftar: terjadwal, belum difakturkan, belum dibayar, sampai lunas."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari nama, no. PO, no. tagihan" value={cari}
            onChange={(e) => setCari(e.target.value)} data-testid="hutang-cari" />
        </div>
        <SmartNativeSelect value={jenis} onChange={(e) => { setJenis(e.target.value); setPihak(''); }} searchable={false}
          className="h-9 w-40" aria-label="Jenis hutang" data-testid="hutang-jenis">
          <option value="">Semua jenis</option>
          <option value="pemasok">Pemasok</option>
          <option value="cmt">CMT</option>
        </SmartNativeSelect>
        <SmartNativeSelect value={pihak} onChange={(e) => setPihak(e.target.value)} className="h-9 w-full sm:w-56"
          aria-label="Nama pemasok atau CMT" data-testid="hutang-pihak">
          <option value="">Semua pemasok & CMT</option>
          {daftarPihak.map((n) => <option key={n} value={n}>{n}</option>)}
        </SmartNativeSelect>
        <FilterChips value={status} onChange={setStatus} testId="hutang-status" ariaLabel="Status hutang"
          hideWhenEmpty={false} options={pilStatus} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`hutang-${todayWIB()}`} namaLembar="Hutang" baris={rows} testId="hutang-unduh"
          kolom={[
            { label: 'Nomor', nilai: (r) => r.nomor || '' }, { label: 'Jenis', nilai: (r) => JENIS[r.jenis] },
            { label: 'Pemasok / CMT', nilai: (r) => r.pihak }, { label: 'Referensi', nilai: (r) => r.ref || '' },
            { label: 'CV', nilai: (r) => (r.entity ? ownerLabel(r.entity) : '') },
            { label: 'Tanggal', nilai: (r) => (r.tanggal ? formatDateID(r.tanggal) : '') },
            { label: 'Jatuh tempo', nilai: (r) => (r.jatuhTempo && r.src !== 'jadwal' ? formatDateID(r.jatuhTempo) : '') },
            { label: 'Umur', nilai: (r) => (r.umurKirim?.hari != null ? `${r.umurKirim.hari} hari sejak kirim ke CMT` : teksJatuhTempo(r.terlambat)) },
            { label: 'Total', nilai: (r) => r.total }, { label: 'Sisa', nilai: (r) => r.sisa },
            { label: 'Status', nilai: (r) => STATUS_HUTANG[r.status]?.label || r.status },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="hutang-muat-ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {gagal.length > 0 && <Notice tone="danger" icon={AlertTriangle} title="Sebagian data gagal dimuat">{gagal.join(' · ')}</Notice>}
        {!(loading && !semua.length) && <div className="space-y-1.5 text-sm text-muted-foreground" data-testid="hutang-ringkasan">
          <p>
            Belum dibayar <b className="text-foreground tabular-nums">{fmt(ringkas.belumDibayar)}</b>
            {ringkas.lewat > 0 && <> (lewat jatuh tempo <b className="text-[hsl(var(--danger-text))] tabular-nums">{fmt(ringkas.lewat)}</b>)</>}
            {' · '}terjadwal <b className="text-foreground tabular-nums">{fmt(ringkas.terjadwal)}</b>
            {' · '}belum difakturkan <b className="text-foreground tabular-nums">{fmt(ringkas.belumDifakturkan)}</b>
            {ringkas.draf > 0 && <>{' · '}faktur draf <b className="text-foreground tabular-nums">{fmt(ringkas.draf)}</b></>}
            {' · '}total belum lunas <b className="text-foreground tabular-nums" data-testid="hutang-total">{fmt(ringkas.totalTerbuka)}</b>
            {gabungan && <> (CV Dewi Aditya {fmt(ringkas.perCv.DA)} · CV Sukma {fmt(ringkas.perCv.SMU)})</>}
          </p>
          {ringkas.terjadwal > 0 && (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="hutang-umur-kirim">
              <span>Terjadwal menurut lama di CMT:</span>
              {Object.entries(KELOMPOK_KIRIM).map(([k, m]) => (
                <span key={k} className="inline-flex items-center gap-1.5 whitespace-nowrap">
                  <StatusBadge status={k} label={m.label} tone={m.tone} />
                  <b className="text-foreground tabular-nums">{fmt(ringkas.kirim[k])}</b>
                </span>
              ))}
            </p>
          )}
          <p className="text-xs">Terjadwal = upah jahit untuk barang yang masih di CMT; belum bisa dibayar. Hutang nyata lahir saat barang lolos QC.</p>
        </div>}
        {ringkas.belumDijurnal.length > 0 && (
          <Notice tone="warning" icon={AlertTriangle} testId="hutang-belum-dijurnal">
            {ringkas.belumDijurnal.length} tagihan CMT ({fmt(ringkas.belumDijurnal.reduce((t, r) => t + r.sisa, 0))}) belum
            dijurnal sehingga belum masuk buku besar — tekan Jurnal di barisnya.
          </Notice>
        )}
      </>}
      detail={detail}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={rows.length} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !semua.length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : (
          <Table data-testid="hutang-tabel" className="md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead>Nomor</TableHead>
                <TableHead>Pemasok / CMT</TableHead>
                <TableHead>Referensi</TableHead>
                <TableHead>Tanggal</TableHead>
                <TableHead>Umur</TableHead>
                <TableHead className="text-right">Sisa</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={kolom} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Receipt} testId="hutang-kosong"
                      title={semua.length ? 'Tidak ada hutang yang cocok' : 'Belum ada hutang'}
                      description={semua.length ? 'Ubah pencarian atau penyaring.'
                        : 'Hutang muncul dari faktur pemasok, penerimaan barang, tagihan CMT, dan jadwal upah jahit PO.'} />
                  </TableCell>
                </TableRow>
              )}
              {paged.map((r) => (
                <TableRow key={r.key} data-testid={`hutang-baris-${r.key}`}>
                  <TableCell className="min-w-[8rem]">
                    <Button variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => buka(r)}
                      data-testid={`hutang-buka-${r.key}`}>{r.nomor || '—'}</Button>
                    <div className="flex flex-wrap gap-1">
                      {r.perkiraan && <StatusBadge status="perkiraan" label="Perkiraan" tone="muted" testId={`hutang-perkiraan-${r.key}`} />}
                      {r.antarCv && <StatusBadge status="antar-cv" label="Antar CV" tone="info" />}
                      {r.belumDijurnal && <StatusBadge status="belum-dijurnal" label="Belum dijurnal" tone="warning" />}
                    </div>
                  </TableCell>
                  <TableCell>
                    {r.pihak}
                    <span className="block text-xs text-muted-foreground">
                      {[JENIS[r.jenis], gabungan && r.entity ? ownerLabel(r.entity) : null].filter(Boolean).join(' · ')}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{r.ref || '—'}</TableCell>
                  <TableCell className="whitespace-nowrap">{r.tanggal ? formatDateID(r.tanggal) : '—'}</TableCell>
                  <TableCell>
                    {r.status === 'terjadwal'
                      ? <UmurKirim hari={r.umurKirim?.hari} kelompok={r.umurKirim?.kelompok} testId={`hutang-umur-${r.key}`} />
                      : <UmurJatuhTempo hari={r.terlambat} testId={`hutang-umur-${r.key}`} />}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    <span className="font-medium" data-testid={`hutang-sisa-${r.key}`}>{fmt(r.sisa)}</span>
                    {Math.abs(Number(r.total) - Number(r.sisa)) > 0.5 && (
                      <span className="block text-xs text-muted-foreground">dari {fmt(r.total)}</span>
                    )}
                  </TableCell>
                  <TableCell><StatusBadge status={r.status} label={STATUS_HUTANG[r.status]?.label} tone={STATUS_HUTANG[r.status]?.tone} /></TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-1">
                      {r.src === 'gr' && (
                        <Button size="sm" variant="outline" onClick={() => setBuatFaktur(r.raw)} data-testid={`hutang-buat-faktur-${r.key}`}>Buat faktur</Button>
                      )}
                      {r.src === 'ap' && r.status === 'draf' && (
                        <Button size="sm" variant="outline" onClick={() => setRincian(r)} data-testid={`hutang-setujui-${r.key}`}>Setujui</Button>
                      )}
                      {finance && r.belumDijurnal && (
                        <Button size="sm" variant="outline" onClick={() => jurnalCmt(r)} title="Catat tagihan CMT ini ke buku besar"
                          data-testid={`hutang-jurnal-${r.key}`}>Jurnal</Button>
                      )}
                      {bisaBayar(r) && (
                        <Button size="sm" variant="success" onClick={() => setBayar(r.raw)} data-testid={`hutang-bayar-${r.key}`}>Bayar</Button>
                      )}
                      {r.src === 'jadwal' && (
                        <Button size="sm" variant="outline" onClick={() => setRincian(r)} data-testid={`hutang-rincian-${r.key}`}>Rincian</Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {buatFaktur && (
        <CreateInvoicePanel key={buatFaktur.id} token={token} gr={buatFaktur} onClose={() => setBuatFaktur(null)}
          onCreated={() => { setBuatFaktur(null); load(); }} />
      )}
      {bayar && <PayInvoiceModal token={token} inv={bayar} onClose={() => setBayar(null)} onPaid={() => load()} />}
    </PageLayout>
  );
}
