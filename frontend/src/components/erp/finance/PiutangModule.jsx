/**
 * Piutang — Portal Keuangan › Piutang (11 Nov 2026, owner).
 *
 * Owner: "piutang juga sama masuk menu ya langsung piutang kenapa malah faktur … jangan malah tab lebih baik filter saja
 * … nama menunya hutang piutang saja". Dulu menu "Piutang Reseller" membuka tab "Faktur" (lalu Umur piutang, Hapus
 * buku); piutang maklon terjadwal tampil Rp0 dan piutang marketplace tidak ada. Kini SATU daftar semua piutang:
 *   • faktur reseller / grosir, nota aksesoris CMT, antar CV (/api/rahaza/ar-invoices, kecuali piutang PO maklon);
 *   • piutang klien maklon per PO (/api/dewi/maklon/receivables) — sumber dan angka SAMA dengan Portal Maklon ›
 *     Piutang klien; terjadwal tampil dengan sisa nilai PO (bukan Rp0), umur sejak kirim ke CMT;
 *   • saldo toko marketplace yang belum ditarik ke bank (/api/marketing/settlements/platform-balance; CV Dewi Aditya).
 * Penyaring: status (Belum lunas bawaan · Terjadwal · Belum dibayar · Dibayar sebagian · Lewat jatuh tempo · Lunas ·
 * Semua), jenis, nama klien/pelanggan, cari; CV = pilihan CV Portal Keuangan di atas (Gabungan → kolom CV).
 * Rincian = popup. "Rekening koran" = tombol halaman. Hapus buku piutang macet = tombol di baris yang lewat jatuh tempo.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, AlertTriangle, Banknote, History, MoreHorizontal, RefreshCw, Search, ShieldAlert, Users } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { MoneyInput } from '@/components/ui/money-input';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PageLayout, { DetailPanel } from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { PaymentHistoryList } from '../PaymentHistoryModal';
import CashAccountSelect, { usePaymentCashAccounts } from '../SdmCashAccountSelect';
import { PaymentForm as BayarMaklon, ReceivableDetail } from '../MaklonBillingModule';
import RekeningKoranPelanggan from './RekeningKoranPelanggan';
import { apiGet, apiPost } from '../../../lib/api';
import { CV_ALL, CV_DA, ownerLabel, useCvOr } from '@/lib/entitas';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { ambilPetunjukTab } from '../hubs/petunjukTab';
import { KELOMPOK_KIRIM, UmurJatuhTempo, UmurKirim, hariTerlambat, jumlahPerKelompokKirim, teksJatuhTempo } from './umurTagihan';

const fmt = formatRupiah;

export const STATUS_PIUTANG = {
  terjadwal: { label: 'Terjadwal', tone: 'info' },
  draf: { label: 'Draf · belum terbit', tone: 'muted' },
  belum_dibayar: { label: 'Belum dibayar', tone: 'warning' },
  sebagian: { label: 'Dibayar sebagian', tone: 'warning' },
  lunas: { label: 'Lunas', tone: 'success' },
  batal: { label: 'Dibatalkan', tone: 'muted' },
  hapus_buku: { label: 'Dihapusbukukan', tone: 'danger' },
};
const TERBUKA = new Set(['terjadwal', 'draf', 'belum_dibayar', 'sebagian']);
const TAGIHAN_TERBUKA = new Set(['belum_dibayar', 'sebagian']);
export const JENIS_PIUTANG = { reseller: 'Reseller & grosir', maklon: 'Maklon', marketplace: 'Marketplace', lainnya: 'Lainnya' };

// ─── Baris daftar ─────────────────────────────────────────────────────────────
/** Nota aksesoris CMT dan dokumen antar CV = "Lainnya"; dokumen alur maklon (server `maklon`) = Maklon. */
export function jenisFaktur(inv) {
  const sm = String(inv.source_module || '');
  if (sm === 'cmt_accessory' || inv.intercompany || sm.startsWith('ic_')) return 'lainnya';
  if (inv.maklon) return 'maklon';
  return 'reseller';
}

/** Batas bayar satu faktur (piutang maklon terjadwal v2 boleh uang muka sampai sisa nilai PO — core.maklon_ledger). */
export function arPayCap(inv) {
  if (inv?.schedule_mode === 'v2') {
    const out = inv.outstanding_total;
    if (out !== undefined && out !== null) return Math.max(0, Number(out) || 0);
    return Math.max(0, Math.max(Number(inv.scheduled_total || 0), Number(inv.billed_total || 0)) - Number(inv.amount_paid ?? inv.paid_amount ?? 0));
  }
  return Math.max(0, Number(inv?.balance || 0));
}

export function barisFakturPiutang(inv, hariIni = todayWIB()) {
  const st = String(inv.status || '').toLowerCase();
  const total = Number(inv.total || 0);
  const dibayar = Number(inv.paid_amount || 0);
  const sisa = Math.max(Number(inv.balance ?? total - dibayar) || 0, 0);
  const status = st === 'draft' ? 'draf' : st === 'scheduled' ? 'terjadwal' : st === 'paid' ? 'lunas'
    : ['cancelled', 'void'].includes(st) ? 'batal' : st === 'written_off' ? 'hapus_buku'
      : st === 'partial_paid' ? 'sebagian' : sisa <= 0.5 ? 'lunas' : 'belum_dibayar';
  const sm = String(inv.source_module || '');
  const po = (n) => (n ? (/^PO/i.test(n) ? n : `PO ${n}`) : '');
  const ref = sm === 'cmt_accessory'
    ? [inv.permintaan_nomor ? `Permintaan ${inv.permintaan_nomor}` : inv.shipment_number, po(inv.po_number)].filter(Boolean).join(' · ')
    : [inv.shipment_number, po(inv.linked_maklon_po_number)].filter(Boolean).join(' · ');
  return {
    key: `ar-${inv.id}`, src: 'ar', jenis: jenisFaktur(inv), status, nomor: inv.invoice_number,
    pihak: inv.customer_name || '(tanpa nama)', pihakId: inv.customer_id, ref, tanggal: inv.issue_date, jatuhTempo: inv.due_date,
    total, dibayar, sisa: TERBUKA.has(status) ? sisa : 0, terjadwalSisa: 0, tertagih: TAGIHAN_TERBUKA.has(status) ? sisa : 0,
    entity: inv.entity || 'DA', antarCv: !!inv.intercompany, notaAksesoris: sm === 'cmt_accessory',
    terlambat: TAGIHAN_TERBUKA.has(status) ? hariTerlambat(inv.due_date, hariIni) : null,
    raw: inv,
  };
}

/** Satu baris /api/dewi/maklon/receivables (angka sama dengan Portal Maklon › Piutang klien). */
export function barisPiutangMaklon(r, hariIni = todayWIB()) {
  const st = String(r.status || '').toLowerCase();
  const sisa = Math.max(Number(r.outstanding_total || 0), 0);
  const tertagih = Math.max(Number(r.amount_due || 0), 0);
  const status = st === 'scheduled' ? 'terjadwal' : st === 'paid' ? 'lunas' : st === 'cancelled' ? 'batal'
    : st === 'draft' ? 'draf' : st === 'partial_paid' ? 'sebagian' : sisa <= 0.5 ? 'lunas' : 'belum_dibayar';
  return {
    key: `maklon-${r.id}`, src: 'maklon', jenis: 'maklon', status, nomor: r.po_number || r.invoice_number,
    nomorKedua: r.invoice_number, pihak: r.client_name || '(tanpa nama)', pihakId: r.client_id,
    ref: r.mode === 'lama' ? 'faktur lama' : '', tanggal: r.kirim_pertama || r.issue_date, jatuhTempo: r.due_date,
    total: Math.max(Number(r.scheduled_total || 0), Number(r.billed_total || 0)), dibayar: Number(r.paid_total || 0),
    sisa: TERBUKA.has(status) ? sisa : 0, terjadwalSisa: Math.max(Number(r.scheduled_remaining || 0), 0),
    tertagih, uangMuka: Math.max(Number(r.advance_balance || 0), 0), entity: r.entity || 'SMU',
    umurKirim: { hari: r.umur_kirim_hari ?? null, kelompok: r.umur_kirim || null },
    terlambat: tertagih > 0.005 ? hariTerlambat(r.due_date, hariIni) : null,
    jurnalTertunda: !!r.post_error, raw: r,
  };
}

/** Saldo toko marketplace yang belum ditarik ke bank (piutang platform 1-1303, buku CV Dewi Aditya). */
export function barisMarketplace(b) {
  const sisa = Math.max(Number(b.balance || 0), 0);
  return {
    key: `mp-${b.account_id}`, src: 'marketplace', jenis: 'marketplace', status: 'belum_dibayar',
    nomor: b.account_code || b.account_name, pihak: b.account_name || b.account_code || '(toko)', ref: b.platform || '',
    tanggal: null, jatuhTempo: null, total: Number(b.released_total || 0), dibayar: Number(b.withdrawn_total || 0),
    sisa, terjadwalSisa: 0, tertagih: sisa, entity: CV_DA, terlambat: null, raw: b,
  };
}

export function susunPiutang({ faktur = [], maklon = [], marketplace = [] }, hariIni = todayWIB()) {
  return [
    // piutang PO maklon diambil dari sumber Portal Maklon (satu angka) — tidak dihitung dua kali dari daftar faktur
    ...faktur.filter((i) => i.source_module !== 'maklon_po').map((i) => barisFakturPiutang(i, hariIni)),
    ...maklon.map((r) => barisPiutangMaklon(r, hariIni)),
    ...marketplace.filter((b) => Number(b.balance || 0) > 0.5).map(barisMarketplace),
  ];
}

export function urutkanPiutang(rows) {
  const acuan = (r) => String(r.jatuhTempo || r.tanggal || '9999');
  return [...rows].sort((a, b) => {
    const ta = TERBUKA.has(a.status) ? 0 : 1;
    const tb = TERBUKA.has(b.status) ? 0 : 1;
    if (ta !== tb) return ta - tb;
    return ta === 0 ? acuan(a).localeCompare(acuan(b)) : String(b.tanggal || '').localeCompare(String(a.tanggal || ''));
  });
}

export function cocokStatusPiutang(r, status) {
  if (!status || status === 'terbuka') return TERBUKA.has(r.status);
  if (status === 'semua') return true;
  if (status === 'lewat') return Number(r.terlambat) > 0 && r.tertagih > 0.005;
  if (status === 'belum_dibayar') return r.status === 'belum_dibayar';
  return r.status === status;
}

/** Ringkasan; terjadwal / tertagih / uang muka dijumlah dari semua baris yang tidak batal — rumus yang SAMA dengan
 *  ringkasan Portal Maklon › Piutang klien (server `list_receivables.summary`, baris `live`). */
export function ringkasPiutang(rows) {
  const jumlah = (f, nilai = (r) => r.sisa) => rows.filter(f).reduce((t, r) => t + Number(nilai(r) || 0), 0);
  const hidup = (r) => r.status !== 'batal' && r.status !== 'hapus_buku';
  return {
    terjadwal: jumlah(hidup, (r) => r.terjadwalSisa),
    tertagih: jumlah(hidup, (r) => r.tertagih),
    lewat: jumlah((r) => hidup(r) && Number(r.terlambat) > 0, (r) => r.tertagih),
    uangMuka: jumlah(hidup, (r) => r.uangMuka),
    draf: jumlah((r) => r.status === 'draf'),
    totalTerbuka: jumlah((r) => TERBUKA.has(r.status)),
    perCv: { DA: jumlah((r) => TERBUKA.has(r.status) && r.entity === 'DA'), SMU: jumlah((r) => TERBUKA.has(r.status) && r.entity === 'SMU') },
    kirim: jumlahPerKelompokKirim(rows.filter((r) => hidup(r) && r.terjadwalSisa > 0), (r) => r.terjadwalSisa),
  };
}


/** Petunjuk dari tautan lama (makeRedirect `fin-ar-hub` + tab / Beranda Keuangan) → pil status awal. */
const PETUNJUK_TAB = {
  aging: 'belum_dibayar', invoices: 'terbuka', writeoff: 'lewat', lewat: 'lewat', belum_dibayar: 'belum_dibayar',
  terjadwal: 'terjadwal',
};

// ─── Popup ─────────────────────────────────────────────────────────────────────
function BayarFaktur({ invoice, onClose, onDone }) {
  const { accounts, loaded } = usePaymentCashAccounts(null);
  const due = Number(invoice.balance || 0);
  const batas = arPayCap(invoice);
  const isSchedule = invoice.schedule_mode === 'v2';
  const [amount, setAmount] = useState(isSchedule ? (due > 0 ? due : batas) : batas);
  const [accountId, setAccount] = useState('');
  const [date, setDate] = useState(todayWIB);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  // antar CV — rekening CV lain yang MEMBAYAR ikut dipilih; pasangannya dibuat otomatis
  const isIc = !!invoice.intercompany;
  const otherCv = invoice.entity === 'SMU' ? 'DA' : 'SMU';
  const { accounts: counterAccounts, loaded: counterLoaded } = usePaymentCashAccounts(null, otherCv);
  const [counterId, setCounter] = useState('');
  const problem = !accountId ? 'Pilih rekening penerima.'
    : isIc && !counterId ? `Pilih rekening ${otherCv === 'SMU' ? 'CV Sukma' : 'CV Dewi Aditya'} yang membayar.`
      : !(Number(amount) > 0) ? 'Jumlah harus lebih dari 0.'
        : Number(amount) > batas + 0.5 ? `Jumlah melebihi ${isSchedule ? 'sisa nilai PO' : 'sisa tagihan'} (${fmt(batas)}).` : '';
  const simpan = async () => {
    setSaving(true);
    try {
      const d = await apiPost(`/api/rahaza/ar-invoices/${invoice.id}/payment`,
        { amount, account_id: accountId, date, notes, ...(isIc ? { counter_cash_account_id: counterId } : {}) });
      if (d?._posting_result && !d._posting_result.ok) toast.error(`Pembayaran tercatat, tetapi jurnal GAGAL: ${d._posting_result.error}`);
      else toast.success(`Pembayaran dicatat${d?._posting_result?.je_number ? ` · ${d._posting_result.je_number}` : ''}.`);
      onDone();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="piutang-bayar" judul="Catat pembayaran"
      keterangan={`${invoice.invoice_number} · ${invoice.customer_name}`} onSimpan={simpan} menyimpan={saving}
      bisaSimpan={!problem} galat={problem && accountId ? problem : undefined}>
      <p className="text-sm text-muted-foreground">Sisa tagihan: {fmt(batas)}</p>
      <Isian label="Jumlah diterima" wajib htmlFor="piutang-bayar-jumlah">
        <MoneyInput glass id="piutang-bayar-jumlah" value={amount} onChange={(e) => setAmount(Number(e.target.value))} data-testid="piutang-bayar-jumlah" />
      </Isian>
      <Isian label="Masuk ke rekening" wajib>
        <CashAccountSelect accounts={accounts} loaded={loaded} value={accountId} onChange={setAccount} testId="piutang-bayar-rekening" />
      </Isian>
      {isIc && (
        <Isian label={`Dibayar dari rekening ${otherCv === 'SMU' ? 'CV Sukma' : 'CV Dewi Aditya'}`} wajib petunjuk="Antar CV — pembayaran pasangannya dibuat otomatis.">
          <CashAccountSelect accounts={counterAccounts} loaded={counterLoaded} value={counterId} onChange={setCounter} testId="piutang-bayar-rekening-cv-lain" />
        </Isian>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Tanggal">
          <DatePicker value={date} onChange={(v) => setDate(v || todayWIB())} bolehKosong={false} testId="piutang-bayar-tanggal" />
        </Isian>
        <Isian label="Catatan" htmlFor="piutang-bayar-catatan">
          <GlassInput id="piutang-bayar-catatan" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="mis. no. referensi transfer" />
        </Isian>
      </div>
    </FormPopup>
  );
}

function HapusBuku({ row, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [date, setDate] = useState('');
  const [saving, setSaving] = useState(false);
  const simpan = async () => {
    setSaving(true);
    try {
      await apiPost(`/api/rahaza/ar-invoices/${row.raw.id}/write-off-bad-debt`, { reason, write_off_date: date || todayWIB() });
      toast.success(`Faktur ${row.nomor} dihapusbukukan`);
      onDone();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="piutang-hapus-buku" judul="Hapus buku piutang macet"
      keterangan="Jurnal beban piutang tak tertagih dicatat otomatis." onSimpan={simpan} menyimpan={saving}
      labelSimpan="Hapus buku" warnaSimpan="destructive" bisaSimpan={reason.trim().length >= 10}>
      <Notice tone="danger" icon={AlertTriangle} title="Piutang faktur ini dihapus dari buku.">
        <dl className="space-y-1 mt-2 text-foreground">
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Faktur</dt><dd className="font-semibold">{row.nomor}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Terlambat</dt><dd className="font-semibold tabular-nums">{row.terlambat} hari</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Jumlah</dt><dd className="font-semibold tabular-nums">{fmt(row.sisa)}</dd></div>
        </dl>
      </Notice>
      <Isian label="Tanggal hapus buku" petunjuk="Kosong = hari ini.">
        <DatePicker value={date} placeholder="Hari ini" onChange={setDate} testId="piutang-hapus-buku-tanggal" />
      </Isian>
      <Isian label="Alasan" wajib htmlFor="piutang-hapus-buku-alasan" petunjuk={`Minimal 10 karakter untuk jejak audit. Saat ini: ${reason.length} karakter.`}>
        <Textarea id="piutang-hapus-buku-alasan" rows={4} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="Contoh: pelanggan bangkrut, tidak tertagih setelah 6 bulan penagihan" data-testid="piutang-hapus-buku-alasan" />
      </Isian>
    </FormPopup>
  );
}

function RincianFaktur({ row, token, onClose, onPay }) {
  const inv = row.raw;
  return (
    <DetailPanel testId="piutang-rincian-faktur" onClose={onClose} title={`Faktur ${inv.invoice_number}`}
      description={`${row.pihak} · ${JENIS_PIUTANG[row.jenis]} · ${ownerLabel(row.entity)}`}
      actions={onPay && <Button variant="success" onClick={() => onPay(row)} data-testid="piutang-rincian-bayar">Bayar</Button>}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div><div className="text-xs text-muted-foreground">Terbit</div><div>{row.tanggal ? formatDateID(row.tanggal) : '—'}</div></div>
        <div><div className="text-xs text-muted-foreground">Jatuh tempo</div><div>{row.jatuhTempo ? formatDateID(row.jatuhTempo) : '—'}</div></div>
        <div><div className="text-xs text-muted-foreground">Total</div><div className="tabular-nums">{fmt(row.total)}</div></div>
        <div><div className="text-xs text-muted-foreground">Sisa</div><div className="font-semibold tabular-nums">{fmt(row.sisa)}</div></div>
      </div>
      {row.ref && <p className="text-sm text-muted-foreground">Referensi: {row.ref}</p>}
      {row.notaAksesoris && Number(inv.jumlah_dipotong) > 0 && (
        <p className="text-sm text-muted-foreground">Dipotong dari tagihan jahit {fmt(inv.jumlah_dipotong)}.</p>
      )}
      {inv.status !== 'draft' && (
        <div className="space-y-2 pt-2 border-t border-[var(--glass-border)]">
          <p className="text-sm font-medium text-foreground">Riwayat pembayaran · dibayar {fmt(row.dibayar)}</p>
          <PaymentHistoryList token={token} kind="ar" invoiceId={inv.id} />
        </div>
      )}
    </DetailPanel>
  );
}

// ─── Layar ─────────────────────────────────────────────────────────────────────
export default function PiutangModule({ token, initialStatus, onNavigate }) {
  const cv = useCvOr();
  const gabungan = cv === CV_ALL;
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [data, setData] = useState({ faktur: [], maklon: [], marketplace: [], pelanggan: [] });
  const [loading, setLoading] = useState(true);
  const [gagal, setGagal] = useState([]);
  const [status, setStatus] = useState(() => initialStatus || PETUNJUK_TAB[ambilPetunjukTab('fin-ar-hub')] || 'terbuka');
  const [jenis, setJenis] = useState('');
  const [pihak, setPihak] = useState('');
  const [cari, setCari] = useState('');
  const [rincian, setRincian] = useState(null);
  const [bayar, setBayar] = useState(null);
  const [hapusBuku, setHapusBuku] = useState(null);
  const [rekeningKoran, setRekeningKoran] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    const sumber = [
      ['faktur', 'faktur piutang', '/api/rahaza/ar-invoices?limit=5000', (d) => (Array.isArray(d) ? d : [])],
      ['maklon', 'piutang klien maklon', '/api/dewi/maklon/receivables', (d) => d?.items || []],
      // marketplace = buku CV Dewi Aditya (pendapatan toko lewat pencairan)
      ...(cv === 'SMU' ? [] : [['marketplace', 'saldo marketplace', '/api/marketing/settlements/platform-balance', (d) => d?.data || []]]),
      ['pelanggan', 'pelanggan', '/api/rahaza/customers', (d) => (Array.isArray(d) ? d : [])],
    ];
    const hasil = await Promise.all(sumber.map(async ([key, label, url, ambil]) => {
      try { return [key, ambil(await apiGet(url)), null]; } catch (e) { return [key, [], `${label}: ${e?.message || e}`]; }
    }));
    setData({ faktur: [], maklon: [], marketplace: [], pelanggan: [], ...Object.fromEntries(hasil.map(([k, v]) => [k, v])) });
    const err = hasil.filter(([k]) => k !== 'pelanggan').map(([, , e]) => e).filter(Boolean);
    setGagal(err);
    if (err.length) toast.error(`Sebagian data piutang gagal dimuat: ${err.join('; ')}`);
    setLoading(false);
  }, [cv]);
  useEffect(() => { load(); }, [load]);

  const semua = useMemo(() => urutkanPiutang(susunPiutang(data)), [data]);
  const dasar = useMemo(() => {
    const s = cari.trim().toLowerCase();
    return semua.filter((r) => (!jenis || r.jenis === jenis) && (!pihak || r.pihak === pihak)
      && (!s || [r.nomor, r.nomorKedua, r.pihak, r.ref].filter(Boolean).some((v) => String(v).toLowerCase().includes(s))));
  }, [semua, jenis, pihak, cari]);
  const rows = useMemo(() => dasar.filter((r) => cocokStatusPiutang(r, status)), [dasar, status]);
  const hitung = (st) => dasar.filter((r) => cocokStatusPiutang(r, st)).length;
  const ringkas = useMemo(() => ringkasPiutang(dasar), [dasar]);
  const daftarPihak = useMemo(() => [...new Set(semua.filter((r) => !jenis || r.jenis === jenis).map((r) => r.pihak))]
    .sort((a, b) => a.localeCompare(b, 'id')), [semua, jenis]);
  const { page, setPage, totalPages, paged, pageSize } = useClientPagination(rows, 25);
  useEffect(() => { setPage(1); }, [status, jenis, pihak, cari, setPage]);

  const pilStatus = [
    { key: 'terbuka', label: 'Belum lunas' }, { key: 'terjadwal', label: 'Terjadwal' }, { key: 'draf', label: 'Draf' },
    { key: 'belum_dibayar', label: 'Belum dibayar' }, { key: 'sebagian', label: 'Dibayar sebagian' },
    { key: 'lewat', label: 'Lewat jatuh tempo' }, { key: 'lunas', label: 'Lunas' }, { key: 'semua', label: 'Semua' },
  ].map((o) => ({ ...o, count: hitung(o.key) })).filter((o) => o.key !== 'draf' || o.count > 0 || status === 'draf');

  const terbitkan = async (row) => {
    try {
      const d = await apiPost(`/api/rahaza/ar-invoices/${row.raw.id}/send`, {});
      if (d?._posting_result && !d._posting_result.ok) toast.warning(`Faktur terbit, tetapi pencatatan jurnal gagal: ${d._posting_result.error}`);
      else toast.success(`Faktur ${row.nomor} terbit`);
      load();
    } catch (e) { toast.error(e.message); }
  };
  const tandaiLewat = async (row) => {
    try { await apiPost(`/api/rahaza/ar-invoices/${row.raw.id}/status`, { status: 'overdue' }); load(); } catch (e) { toast.error(e.message); }
  };
  const bisaBayar = (r) => (r.src === 'maklon'
    ? r.raw.mode === 'terjadwal' && r.status !== 'batal' && r.sisa > 0.005
    : r.src === 'ar' && !['draf', 'batal', 'hapus_buku'].includes(r.status) && (r.status !== 'lunas' || r.raw.schedule_mode === 'v2') && arPayCap(r.raw) > 0);
  const bisaHapusBuku = (r) => r.src === 'ar' && r.jenis === 'reseller' && TAGIHAN_TERBUKA.has(r.status) && Number(r.terlambat) > 0 && r.sisa > 0;
  const bisaTandaiLewat = (r) => r.src === 'ar' && r.jenis === 'reseller' && ['sent', 'issued'].includes(r.raw.status) && Number(r.terlambat) > 0;
  const bukaBayar = (r) => { setRincian(null); setBayar(r); };
  const kolom = 8;

  return (
    <PageLayout
      testId="fin-piutang"
      title="Piutang"
      subtitle="Semua piutang dalam satu daftar: reseller & grosir, klien maklon, saldo marketplace, dan lainnya."
      actions={<Button variant="outline" onClick={() => setRekeningKoran({})} data-testid="piutang-buka-rekening-koran"><Users className="w-4 h-4" />Rekening koran</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari nama, no. PO, no. faktur" value={cari}
            onChange={(e) => setCari(e.target.value)} data-testid="piutang-cari" />
        </div>
        <SmartNativeSelect value={jenis} onChange={(e) => { setJenis(e.target.value); setPihak(''); }} searchable={false}
          className="h-9 w-44" aria-label="Jenis piutang" data-testid="piutang-jenis">
          <option value="">Semua jenis</option>
          {Object.entries(JENIS_PIUTANG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </SmartNativeSelect>
        <SmartNativeSelect value={pihak} onChange={(e) => setPihak(e.target.value)} className="h-9 w-full sm:w-56"
          aria-label="Nama klien atau pelanggan" data-testid="piutang-pihak">
          <option value="">Semua klien & pelanggan</option>
          {daftarPihak.map((n) => <option key={n} value={n}>{n}</option>)}
        </SmartNativeSelect>
        <FilterChips value={status} onChange={setStatus} testId="piutang-status" ariaLabel="Status piutang"
          hideWhenEmpty={false} options={pilStatus} />
      </>}
      tools={<>
        <TombolUnduh namaBerkas={`piutang-${todayWIB()}`} namaLembar="Piutang" baris={rows} testId="piutang-unduh"
          kolom={[
            { label: 'Nomor', nilai: (r) => r.nomor || '' }, { label: 'Jenis', nilai: (r) => JENIS_PIUTANG[r.jenis] },
            { label: 'Klien / pelanggan', nilai: (r) => r.pihak }, { label: 'Referensi', nilai: (r) => r.ref || '' },
            { label: 'CV', nilai: (r) => ownerLabel(r.entity) },
            { label: 'Tanggal', nilai: (r) => (r.tanggal ? formatDateID(r.tanggal) : '') },
            { label: 'Jatuh tempo', nilai: (r) => (r.jatuhTempo ? formatDateID(r.jatuhTempo) : '') },
            { label: 'Umur', nilai: (r) => (r.status === 'terjadwal' && r.umurKirim?.hari != null ? `${r.umurKirim.hari} hari sejak kirim ke CMT` : teksJatuhTempo(r.terlambat)) },
            { label: 'Total', nilai: (r) => r.total }, { label: 'Dibayar', nilai: (r) => r.dibayar },
            { label: 'Terjadwal', nilai: (r) => r.terjadwalSisa }, { label: 'Tertagih belum dibayar', nilai: (r) => r.tertagih },
            { label: 'Sisa', nilai: (r) => r.sisa }, { label: 'Status', nilai: (r) => STATUS_PIUTANG[r.status]?.label || r.status },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="piutang-muat-ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {gagal.length > 0 && <Notice tone="danger" icon={AlertCircle} title="Sebagian data gagal dimuat">{gagal.join(' · ')}</Notice>}
        {!(loading && !semua.length) && <div className="space-y-1.5 text-sm text-muted-foreground" data-testid="piutang-ringkasan">
          <p>
            Terjadwal <b className="text-foreground tabular-nums" data-testid="piutang-terjadwal">{fmt(ringkas.terjadwal)}</b>
            {' · '}tertagih belum dibayar <b className="text-foreground tabular-nums">{fmt(ringkas.tertagih)}</b>
            {ringkas.lewat > 0 && <> (lewat jatuh tempo <b className="text-[hsl(var(--danger-text))] tabular-nums">{fmt(ringkas.lewat)}</b>)</>}
            {ringkas.uangMuka > 0.5 && <>{' · '}uang muka klien maklon <b className="text-foreground tabular-nums">{fmt(ringkas.uangMuka)}</b></>}
            {ringkas.draf > 0 && <>{' · '}faktur draf <b className="text-foreground tabular-nums">{fmt(ringkas.draf)}</b></>}
            {' · '}total belum lunas <b className="text-foreground tabular-nums" data-testid="piutang-total">{fmt(ringkas.totalTerbuka)}</b>
            {gabungan && <> (CV Dewi Aditya {fmt(ringkas.perCv.DA)} · CV Sukma {fmt(ringkas.perCv.SMU)})</>}
          </p>
          {ringkas.terjadwal > 0 && (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="piutang-umur-kirim">
              <span>Terjadwal menurut lama di CMT:</span>
              {Object.entries(KELOMPOK_KIRIM).map(([k, m]) => (
                <span key={k} className="inline-flex items-center gap-1.5 whitespace-nowrap">
                  <StatusBadge status={k} label={m.label} tone={m.tone} />
                  <b className="text-foreground tabular-nums">{fmt(ringkas.kirim[k])}</b>
                </span>
              ))}
            </p>
          )}
          <p className="text-xs">Terjadwal = nilai PO maklon yang barangnya belum dikirim ke klien. Angka maklon sama dengan Portal Maklon › Piutang klien.</p>
        </div>}
      </>}
      detail={rincian && (rincian.src === 'maklon'
        ? <ReceivableDetail key={rincian.raw.id} arId={rincian.raw.id} headers={headers} token={token} onClose={() => setRincian(null)} onChanged={load} />
        : <RincianFaktur row={rincian} token={token} onClose={() => setRincian(null)} onPay={bisaBayar(rincian) ? bukaBayar : null} />)}
      footer={rows.length > pageSize && (
        <PaginationLite page={page} totalPages={totalPages} total={rows.length} pageSize={pageSize} onPageChange={setPage} />
      )}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !semua.length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : (
          <Table data-testid="piutang-tabel" className="md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead>Nomor</TableHead>
                <TableHead>Klien / pelanggan</TableHead>
                <TableHead>Tanggal</TableHead>
                <TableHead>Umur</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Sisa</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={kolom} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Banknote} testId="piutang-kosong"
                      title={semua.length ? 'Tidak ada piutang yang cocok' : 'Belum ada piutang'}
                      description={semua.length ? 'Ubah pencarian atau penyaring.'
                        : 'Piutang muncul dari Nota Penjualan, PO maklon yang dikonfirmasi, nota aksesoris CMT, dan saldo toko marketplace.'} />
                  </TableCell>
                </TableRow>
              )}
              {paged.map((r) => (
                <TableRow key={r.key} data-testid={`piutang-baris-${r.key}`}>
                  <TableCell className="min-w-[10rem]">
                    {r.src === 'marketplace'
                      ? <span className="font-semibold">{r.nomor}</span>
                      : <Button variant="link" size="sm" className="h-auto p-0 font-semibold" onClick={() => setRincian(r)}
                          data-testid={`piutang-buka-${r.key}`}>{r.nomor || '—'}</Button>}
                    <span className="block text-xs text-muted-foreground">
                      {[JENIS_PIUTANG[r.jenis], r.nomorKedua, r.ref].filter(Boolean).join(' · ')}
                    </span>
                    <div className="flex flex-wrap gap-1">
                      {r.antarCv && <StatusBadge status="antar-cv" label="Antar CV" tone="info" />}
                      {r.notaAksesoris && <StatusBadge status="nota-aksesoris" label="Nota aksesoris CMT" tone="info" />}
                      {r.jurnalTertunda && <StatusBadge status="jurnal-tertunda" label="Jurnal tertunda" tone="danger" />}
                    </div>
                  </TableCell>
                  <TableCell>
                    {r.src === 'ar' && r.jenis === 'reseller' && r.pihakId
                      ? <Button variant="link" size="sm" className="h-auto p-0 text-left whitespace-normal" title="Lihat rekening koran"
                          onClick={() => setRekeningKoran({ customerId: r.pihakId })}>{r.pihak}</Button>
                      : r.pihak}
                    {gabungan && <span className="block text-xs text-muted-foreground">{ownerLabel(r.entity)}</span>}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">{r.tanggal ? formatDateID(r.tanggal) : '—'}</TableCell>
                  <TableCell>
                    {r.status === 'terjadwal' && r.umurKirim
                      ? <UmurKirim hari={r.umurKirim.hari} kelompok={r.umurKirim.kelompok} testId={`piutang-umur-${r.key}`} />
                      : <UmurJatuhTempo hari={r.terlambat} testId={`piutang-umur-${r.key}`} />}
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{fmt(r.total)}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    <span className="font-medium" data-testid={`piutang-sisa-${r.key}`}>{fmt(r.sisa)}</span>
                    {Number(r.dibayar) > 0.5 && (
                      <span className="block text-xs text-muted-foreground">{r.src === 'marketplace' ? 'ditarik' : 'dibayar'} {fmt(r.dibayar)}</span>
                    )}
                    {r.src === 'maklon' && r.terjadwalSisa > 0 && r.tertagih > 0 && (
                      <span className="block text-xs text-muted-foreground">tertagih {fmt(r.tertagih)}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={r.status} tone={STATUS_PIUTANG[r.status]?.tone}
                      label={r.src === 'marketplace' ? 'Belum ditarik' : STATUS_PIUTANG[r.status]?.label} />
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-1">
                      {r.src === 'ar' && r.status === 'draf' && (
                        <Button variant="outline" size="sm" onClick={() => terbitkan(r)} data-testid={`piutang-terbitkan-${r.key}`}
                          title="Terbitkan faktur dan catat ke buku besar">Terbitkan</Button>
                      )}
                      {bisaBayar(r) && (
                        <Button variant="success" size="sm" onClick={() => bukaBayar(r)} data-testid={`piutang-bayar-${r.key}`}>Bayar</Button>
                      )}
                      {r.src === 'marketplace' && onNavigate && (
                        <Button variant="outline" size="sm" onClick={() => onNavigate('fin-marketplace-settlement')}>Buka Marketplace</Button>
                      )}
                      {r.src === 'ar' && (Number(r.dibayar) > 0 || bisaHapusBuku(r) || bisaTandaiLewat(r)) && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" title="Lainnya" aria-label="Lainnya" data-testid={`piutang-lainnya-${r.key}`}><MoreHorizontal className="w-4 h-4" /></Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {Number(r.dibayar) > 0 && (
                              <DropdownMenuItem onClick={() => setRincian(r)}><History className="w-4 h-4 mr-2" />Riwayat pembayaran</DropdownMenuItem>
                            )}
                            {bisaTandaiLewat(r) && (
                              <DropdownMenuItem onClick={() => tandaiLewat(r)}>Tandai lewat jatuh tempo</DropdownMenuItem>
                            )}
                            {bisaHapusBuku(r) && (
                              <DropdownMenuItem onClick={() => setHapusBuku(r)} data-testid={`piutang-hapus-buku-${r.key}`}>
                                <ShieldAlert className="w-4 h-4 mr-2" />Hapus buku piutang macet
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>

      {bayar && bayar.src === 'maklon' && (
        <BayarMaklon receivable={bayar.raw} headers={headers} token={token} onClose={() => setBayar(null)}
          onDone={() => { setBayar(null); load(); }} />
      )}
      {bayar && bayar.src === 'ar' && (
        <BayarFaktur invoice={bayar.raw} onClose={() => setBayar(null)} onDone={() => { setBayar(null); load(); }} />
      )}
      {hapusBuku && <HapusBuku row={hapusBuku} onClose={() => setHapusBuku(null)} onDone={() => { setHapusBuku(null); load(); }} />}
      {rekeningKoran && (
        <RekeningKoranPelanggan token={token} customers={data.pelanggan} customerId={rekeningKoran.customerId}
          onClose={() => setRekeningKoran(null)} />
      )}
    </PageLayout>
  );
}
