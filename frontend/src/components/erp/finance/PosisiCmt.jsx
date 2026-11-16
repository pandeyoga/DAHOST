/**
 * Posisi per CMT — Keuangan › Hutang, tampilan "Posisi per CMT" (16 Nov 2026, owner: "berapa pencairannya").
 *
 * Per CMT dan per PO: nilai PO (komitmen = qty × upah CMT), sudah setor lolos QC (= hutang nyata), sudah dibayar,
 * ditahan (selisih tagihan), dan BOLEH DIBAYAR. Komitmen tidak dijurnal; hutang tetap lahir saat setoran lolos QC.
 * Sumber: GET /api/dewi/maklon/finance/cmt-posisi (core.posisi_cmt — satu hitungan dengan jadwal hutang CMT & gerbang
 * tombol Bayar). Rincian per PO dan bukti bayar dibuka di bawah barisnya (RowDetail).
 *
 * "Bayar" = satu pembayaran ke SATU CMT untuk beberapa tagihannya: pembagian terlama dulu, bisa diubah; tombol
 * mengikuti centang Keuangan › Pembayaran & Pencairan Uang › Setujui (sama dengan Bayar satu tagihan).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { FileDown, HandCoins, RefreshCw, Search, Users } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { MoneyInput } from '@/components/ui/money-input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import PageLayout, { RowDetail, RowToggle } from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import CashAccountSelect, { usePaymentCashAccounts } from '../SdmCashAccountSelect';
import { apiDownload, apiGet, apiPost } from '../../../lib/api';
import { CENTANG_BAYAR } from '../../../lib/financeRoles';
import { punyaCentang } from '../../../lib/rbac';
import { CV_ALL, normalizeCv, ownerLabel, useCvOr } from '@/lib/entitas';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { TOLERANSI, alokasiTerlama, jumlahAlokasi, kirimAlokasi, lewatBatas } from './alokasiGabungan';

const fmt = formatRupiah;
const JENIS_BARIS = { jadwal: 'Jadwal PO maklon', perkiraan: 'Perkiraan PO DA', tagihan: 'Tagihan' };

const unduhBukti = (b) => apiDownload(`/api/dewi/maklon/finance/cmt-bayar-gabungan/${b.id}/pdf`, `Bukti_${b.bukti_number}.pdf`)
  .catch((e) => toast.error(e.message));

// ─── Formulir bayar gabungan ───────────────────────────────────────────────────
export function BayarCmtGabungan({ token, vendor, onClose, onDone }) {
  const { accounts, loaded } = usePaymentCashAccounts(token);
  const { accounts: rekSukma, loaded: rekSukmaLoaded } = usePaymentCashAccounts(token, 'SMU');
  const [accountId, setAccountId] = useState('');
  const [counterId, setCounterId] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [ref, setRef] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const akun = accounts.find((a) => a.id === accountId);
  const cvRek = akun ? normalizeCv(akun.entity, 'DA') : null;
  // tagihan yang boleh dibayar dari rekening terpilih (CV rekening = CV tagihan); sebelum memilih rekening: semua
  const layak = useMemo(() => (vendor.tagihan || [])
    .filter((t) => Number(t.boleh_dibayar) > 0.005 && (!cvRek || t.entity === cvRek)), [vendor, cvRek]);
  const batas = useMemo(() => Object.fromEntries(layak.map((t) => [t.id, Number(t.boleh_dibayar)])), [layak]);
  const maks = layak.reduce((s, t) => s + Number(t.boleh_dibayar || 0), 0);
  const [amount, setAmount] = useState(() => String(Math.round(maks)));
  const [alokasi, setAlokasi] = useState(() => alokasiTerlama(Math.round(maks), layak.map((t) => ({
    id: t.id, batas: t.boleh_dibayar, urut: t.tanggal, nomor: t.nomor }))).alokasi);
  const bagiUlang = useCallback((jml) => {
    setAlokasi(alokasiTerlama(Number(jml || 0), layak.map((t) => ({
      id: t.id, batas: t.boleh_dibayar, urut: t.tanggal, nomor: t.nomor }))).alokasi);
  }, [layak]);
  // rekening berganti CV → daftar tagihan berubah → jumlah = boleh dibayar di CV itu, dibagi ulang
  useEffect(() => {
    if (!cvRek) return;
    setAmount(String(Math.round(maks)));
    bagiUlang(Math.round(maks));
  }, [cvRek]); // eslint-disable-line react-hooks/exhaustive-deps

  const cash = Number(amount || 0);
  const dibagi = jumlahAlokasi(alokasi);
  const lewat = lewatBatas(alokasi, batas);
  const perluRekSukma = layak.some((t) => t.antar_cv && Number(alokasi[t.id] || 0) > 0);
  const lainCv = cvRek ? (vendor.tagihan || []).filter((t) => Number(t.boleh_dibayar) > 0.005 && t.entity !== cvRek) : [];
  const problem = !accountId ? 'Pilih rekening pembayaran.'
    : !layak.length ? `Tidak ada tagihan ${vendor.vendor_name} di ${ownerLabel(cvRek)} yang boleh dibayar.`
      : !(cash > 0) ? 'Jumlah dibayar harus lebih dari 0.'
        : cash > maks + TOLERANSI ? `Melebihi yang boleh dibayar (${fmt(maks)}).`
          : lewat.length ? 'Ada pembagian yang melebihi "boleh dibayar" tagihannya.'
            : Math.abs(dibagi - cash) > TOLERANSI ? `Pembagian ${fmt(dibagi)} belum sama dengan jumlah dibayar ${fmt(cash)}.`
              : perluRekSukma && !counterId ? 'Pilih rekening CV Sukma yang menerima (tagihan antar CV).' : '';

  const simpan = async () => {
    if (problem) { setErr(problem); return; }
    setErr('');
    setSaving(true);
    try {
      const out = await apiPost('/api/dewi/maklon/finance/cmt-bayar-gabungan', {
        vendor_id: vendor.vendor_id, amount: cash, cash_account_id: accountId, payment_date: date,
        reference_no: ref || undefined, notes: notes || undefined, alokasi: kirimAlokasi(alokasi),
        ...(perluRekSukma ? { counter_cash_account_id: counterId } : {}),
      });
      const gagalJurnal = (out?.jurnal_gagal || []).length;
      const pesan = `Pembayaran ${fmt(cash)} ke ${vendor.vendor_name} tercatat · ${out?.bukti_number}`;
      if (gagalJurnal) toast.warning(`${pesan}, tetapi ${gagalJurnal} jurnal pembayaran gagal — periksa di Jurnal.`, { duration: 10000 });
      else toast.success(pesan, { duration: 10000, action: { label: 'Unduh bukti', onClick: () => unduhBukti(out) } });
      onDone?.(out);
      onClose();
    } catch (e) {
      setErr(e.message);
      toast.error(e.message);
    } finally { setSaving(false); }
  };

  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="cmt-bayar-gabungan"
      judul={`Bayar ${vendor.vendor_name}`}
      keterangan="Satu pembayaran untuk beberapa tagihan CMT ini. Pembagian terlama dulu; boleh diubah sebelum disimpan."
      onSimpan={simpan} menyimpan={saving} bisaSimpan={!problem} labelSimpan="Bayar & catat ke buku besar"
      adaIsian={cash > 0 && !!accountId} galat={err || (accountId ? problem : '') || undefined}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Bayar dari rekening" wajib>
          <CashAccountSelect accounts={accounts} loaded={loaded} value={accountId} onChange={setAccountId} testId="cmt-bayar-gabungan-rekening" />
        </Isian>
        <Isian label="Jumlah dibayar" wajib htmlFor="cmt-bayar-gabungan-jumlah" petunjuk={`Boleh dibayar ${fmt(maks)}`}>
          <MoneyInput id="cmt-bayar-gabungan-jumlah" value={amount} data-testid="cmt-bayar-gabungan-jumlah"
            onChange={(e) => { setAmount(e.target.value); bagiUlang(e.target.value); }} />
        </Isian>
        <Isian label="Tanggal">
          <DatePicker value={date} onChange={(v) => setDate(v || todayWIB())} bolehKosong={false} testId="cmt-bayar-gabungan-tanggal" />
        </Isian>
        <Isian label="No. referensi" htmlFor="cmt-bayar-gabungan-ref">
          <Input id="cmt-bayar-gabungan-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Mis. nomor transfer" />
        </Isian>
      </div>
      {perluRekSukma && (
        <Isian label="Diterima di rekening CV Sukma" wajib petunjuk="Tagihan tim jahit CV Sukma = hutang antar CV; penerimaan di buku CV Sukma dibuat otomatis.">
          <CashAccountSelect accounts={rekSukma} loaded={rekSukmaLoaded} value={counterId} onChange={setCounterId} testId="cmt-bayar-gabungan-rekening-sukma" />
        </Isian>
      )}
      {lainCv.length > 0 && (
        <Notice tone="info" testId="cmt-bayar-gabungan-cv-lain">
          {lainCv.length} tagihan dibukukan di CV lain ({fmt(lainCv.reduce((s, t) => s + Number(t.boleh_dibayar || 0), 0))}) —
          bayar dari rekening CV itu secara terpisah.
        </Notice>
      )}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Pembagian ke tagihan</p>
          <Button type="button" variant="outline" size="sm" onClick={() => bagiUlang(amount)} data-testid="cmt-bayar-gabungan-bagi-ulang">
            Bagi ulang terlama dulu
          </Button>
        </div>
        <GlassCard className="p-0 overflow-x-auto">
          <Table data-testid="cmt-bayar-gabungan-tabel">
            <TableHeader>
              <TableRow>
                <TableHead>Tagihan</TableHead>
                <TableHead>PO</TableHead>
                <TableHead>Tanggal</TableHead>
                <TableHead className="text-right">Boleh dibayar</TableHead>
                <TableHead className="text-right w-44">Dibayar sekarang</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {layak.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={5} className="p-0 [&>div]:py-6">
                    <EmptyState icon={HandCoins} title="Belum ada tagihan yang boleh dibayar"
                      description="Tagihan lahir saat setoran CMT lolos QC; bagian yang tertahan selisih diselesaikan di Tagihan CMT." />
                  </TableCell>
                </TableRow>
              )}
              {layak.map((t) => {
                const lebih = Number(alokasi[t.id] || 0) > Number(t.boleh_dibayar) + 0.01;
                return (
                  <TableRow key={t.id} data-testid={`cmt-bayar-gabungan-baris-${t.id}`}>
                    <TableCell className="font-medium">
                      {t.nomor}
                      {t.antar_cv && <StatusBadge status="antar-cv" label="Antar CV" tone="info" />}
                    </TableCell>
                    <TableCell>{t.po_number || '—'}</TableCell>
                    <TableCell className="whitespace-nowrap">{t.tanggal ? formatDateID(t.tanggal) : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums whitespace-nowrap">
                      {fmt(t.boleh_dibayar)}
                      {Number(t.ditahan) > 0 && <span className="block text-xs text-muted-foreground">tertahan {fmt(t.ditahan)}</span>}
                    </TableCell>
                    <TableCell className="text-right">
                      <MoneyInput value={alokasi[t.id] ?? ''} aria-label={`Dibayar untuk ${t.nomor}`}
                        className={lebih ? 'border-[hsl(var(--destructive))]' : ''}
                        data-testid={`cmt-bayar-gabungan-isi-${t.id}`}
                        onChange={(e) => setAlokasi((a) => ({ ...a, [t.id]: e.target.value }))} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </GlassCard>
        <p className="text-sm text-muted-foreground" data-testid="cmt-bayar-gabungan-ringkas">
          Dibagi <b className="text-foreground tabular-nums">{fmt(dibagi)}</b> dari <b className="text-foreground tabular-nums">{fmt(cash)}</b>
          {Math.abs(dibagi - cash) > TOLERANSI && <> · selisih <b className="text-[hsl(var(--danger-text))] tabular-nums">{fmt(cash - dibagi)}</b></>}
        </p>
      </div>
      <Isian label="Catatan" htmlFor="cmt-bayar-gabungan-catatan">
        <Input id="cmt-bayar-gabungan-catatan" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Opsional" />
      </Isian>
    </FormPopup>
  );
}

// ─── Rincian satu CMT (di bawah barisnya) ─────────────────────────────────────
function RincianCmt({ v, gabungan, bukti }) {
  return (
    <div className="space-y-3" data-testid={`posisi-cmt-rincian-${v.vendor_id || 'tanpa'}`}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>PO</TableHead>
            <TableHead className="text-right">Nilai PO (komitmen)</TableHead>
            <TableHead className="text-right">Belum disetor</TableHead>
            <TableHead className="text-right">Setor lolos QC</TableHead>
            <TableHead className="text-right">Sudah dibayar</TableHead>
            <TableHead className="text-right">Ditahan</TableHead>
            <TableHead className="text-right">Boleh dibayar</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {v.pos.map((r) => (
            <TableRow key={`${r.po_id}-${r.vendor_id}`}>
              <TableCell>
                <span className="font-medium">{r.po_number || 'Tanpa PO'}</span>
                <span className="block text-xs text-muted-foreground">
                  {[JENIS_BARIS[r.jenis] || r.jenis, gabungan ? ownerLabel(r.entity) : null,
                    r.qty_komitmen ? `${Number(r.qty_komitmen).toLocaleString('id-ID')} pcs` : null].filter(Boolean).join(' · ')}
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.komitmen)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.belum_setor)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {fmt(r.setor_qc)}
                {r.pcs_setor > 0 && <span className="block text-xs text-muted-foreground">{Number(r.pcs_setor).toLocaleString('id-ID')} pcs</span>}
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.dibayar)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.ditahan)}</TableCell>
              <TableCell className="text-right tabular-nums font-semibold">{fmt(r.boleh_dibayar)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">Bukti bayar gabungan</p>
        {bukti === undefined ? <Skeleton className="h-9 rounded-lg" />
          : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nomor</TableHead>
                    <TableHead>Tanggal</TableHead>
                    <TableHead>Rekening</TableHead>
                    <TableHead className="text-right">Jumlah</TableHead>
                    <TableHead className="text-right">Tagihan</TableHead>
                    <TableHead className="text-right">Aksi</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bukti.length === 0 && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={6} className="p-0 [&>div]:py-4">
                        <EmptyState icon={HandCoins} title="Belum ada bukti bayar gabungan"
                          description="Tekan Bayar di baris CMT ini untuk membayar beberapa tagihan sekaligus." />
                      </TableCell>
                    </TableRow>
                  )}
                  {bukti.map((b) => (
                    <TableRow key={b.id}>
                      <TableCell className="font-medium">{b.bukti_number}</TableCell>
                      <TableCell className="whitespace-nowrap">{formatDateID(b.tanggal)}</TableCell>
                      <TableCell>{b.cash_account_name || '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(b.amount)}</TableCell>
                      <TableCell className="text-right tabular-nums">{(b.alokasi || []).length}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="icon-sm" title="Unduh bukti (PDF)" aria-label="Unduh bukti (PDF)"
                          data-cv-allow="" onClick={() => unduhBukti(b)}><FileDown className="w-4 h-4" /></Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
      </div>
    </div>
  );
}

// ─── Layar ─────────────────────────────────────────────────────────────────────
export default function PosisiCmt({ token, hasPerm, toggle, cariAwal = '' }) {
  const cv = useCvOr();
  const gabungan = cv === CV_ALL;
  const bolehBayar = punyaCentang(hasPerm, CENTANG_BAYAR);
  const [data, setData] = useState({ vendors: [], totals: {} });
  const [loading, setLoading] = useState(true);
  const [gagal, setGagal] = useState('');
  const [cari, setCari] = useState(cariAwal);
  const [saring, setSaring] = useState(cariAwal ? 'semua' : 'bisa');
  const [buka, setBuka] = useState({});
  const [bukti, setBukti] = useState({});
  const [bayar, setBayar] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiGet('/api/dewi/maklon/finance/cmt-posisi'));
      setGagal('');
    } catch (e) {
      setGagal(e.message);
      toast.error(`Posisi CMT gagal dimuat: ${e.message}`);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load, cv]);

  const muatBukti = useCallback(async (vid) => {
    try {
      const d = await apiGet(`/api/dewi/maklon/finance/cmt-bayar-gabungan?vendor_id=${encodeURIComponent(vid)}`);
      setBukti((b) => ({ ...b, [vid]: d?.items || [] }));
    } catch (e) { setBukti((b) => ({ ...b, [vid]: [] })); toast.error(e.message); }
  }, []);
  const toggleBuka = (v) => {
    const key = v.vendor_id || 'tanpa';
    setBuka((o) => ({ ...o, [key]: !o[key] }));
    if (!buka[key] && v.vendor_id && bukti[v.vendor_id] === undefined) muatBukti(v.vendor_id);
  };

  const semua = useMemo(() => data.vendors || [], [data]);
  const dasar = useMemo(() => {
    const s = cari.trim().toLowerCase();
    return semua.filter((v) => !s || [v.vendor_name, ...(v.pos || []).map((r) => r.po_number)]
      .some((x) => String(x || '').toLowerCase().includes(s)));
  }, [semua, cari]);
  const rows = saring === 'bisa' ? dasar.filter((v) => v.boleh_dibayar > 0.5) : dasar;
  const tot = useMemo(() => ['komitmen', 'setor_qc', 'dibayar', 'ditahan', 'boleh_dibayar', 'belum_setor']
    .reduce((o, k) => ({ ...o, [k]: dasar.reduce((t, v) => t + Number(v[k] || 0), 0) }), {}), [dasar]);
  const kolom = 8;

  return (
    <PageLayout
      testId="fin-hutang-posisi-cmt"
      title="Hutang"
      subtitle="Posisi per CMT: nilai PO sebagai komitmen, yang sudah disetor lolos QC, dan yang boleh dibayar sekarang."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari nama CMT atau no. PO" value={cari}
            onChange={(e) => setCari(e.target.value)} data-testid="posisi-cmt-cari" />
        </div>
        <FilterChips value={saring} onChange={setSaring} testId="posisi-cmt-saring" ariaLabel="Penyaring CMT" hideWhenEmpty={false}
          options={[{ key: 'bisa', label: 'Ada yang boleh dibayar', count: dasar.filter((v) => v.boleh_dibayar > 0.5).length },
            { key: 'semua', label: 'Semua CMT', count: dasar.length }]} />
      </>}
      tools={<>
        {toggle}
        <TombolUnduh namaBerkas={`posisi-cmt-${todayWIB()}`} namaLembar="Posisi CMT" testId="posisi-cmt-unduh"
          baris={rows.flatMap((v) => v.pos.map((r) => ({ ...r, cmt: v.vendor_name })))}
          kolom={[
            { label: 'CMT', nilai: (r) => r.cmt }, { label: 'PO', nilai: (r) => r.po_number || '' },
            { label: 'Jenis', nilai: (r) => JENIS_BARIS[r.jenis] || r.jenis }, { label: 'CV', nilai: (r) => ownerLabel(r.entity) },
            { label: 'Nilai PO (komitmen)', nilai: (r) => r.komitmen }, { label: 'Belum disetor', nilai: (r) => r.belum_setor },
            { label: 'Setor lolos QC', nilai: (r) => r.setor_qc }, { label: 'Sudah dibayar', nilai: (r) => r.dibayar },
            { label: 'Ditahan', nilai: (r) => r.ditahan }, { label: 'Boleh dibayar', nilai: (r) => r.boleh_dibayar },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="posisi-cmt-muat-ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {gagal && <Notice tone="danger" title="Posisi CMT gagal dimuat">{gagal}</Notice>}
        {dasar.length > 0 && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="posisi-cmt-ringkasan">
            <StatTile label="Nilai PO (komitmen)" value={fmt(tot.komitmen)} testId="posisi-cmt-komitmen"
              hint="Qty pesan × upah CMT. Belum menjadi hutang dan tidak dijurnal." sub={`belum disetor ${fmt(tot.belum_setor)}`} />
            <StatTile label="Sudah setor lolos QC" value={fmt(tot.setor_qc)} testId="posisi-cmt-setor"
              hint="Hutang nyata: lahir saat setoran CMT lolos QC (sudah dijurnal)." />
            <StatTile label="Sudah dibayar" value={fmt(tot.dibayar)} testId="posisi-cmt-dibayar"
              hint="Pembayaran tagihan CMT yang sudah dicatat." sub={tot.ditahan > 0.5 ? `ditahan ${fmt(tot.ditahan)}` : undefined} />
            <StatTile label="Boleh dibayar sekarang" value={fmt(tot.boleh_dibayar)} accent="primary" testId="posisi-cmt-boleh"
              hint="Setor lolos QC − sudah dibayar − bagian yang ditahan selisih tagihan." />
          </div>
        )}
      </>}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !semua.length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : (
          <Table data-testid="posisi-cmt-tabel" className="md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead>CMT</TableHead>
                <TableHead className="text-right">Nilai PO (komitmen)</TableHead>
                <TableHead className="text-right">Setor lolos QC</TableHead>
                <TableHead className="text-right">Sudah dibayar</TableHead>
                <TableHead className="text-right">Ditahan</TableHead>
                <TableHead className="text-right">Boleh dibayar</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={kolom} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Users} testId="posisi-cmt-kosong"
                      title={dasar.length ? 'Tidak ada CMT yang boleh dibayar sekarang' : 'Belum ada hutang CMT'}
                      description={dasar.length ? 'Pilih "Semua CMT" untuk melihat komitmen yang belum disetor.'
                        : 'Posisi muncul setelah PO dikirim ke CMT; hutang lahir saat setoran lolos QC.'} />
                  </TableCell>
                </TableRow>
              )}
              {rows.map((v) => {
                const key = v.vendor_id || 'tanpa';
                const open = !!buka[key];
                return [
                  <TableRow key={key} data-testid={`posisi-cmt-baris-${key}`}>
                    <TableCell><RowToggle open={open} onClick={() => toggleBuka(v)} label="Lihat per PO" testId={`posisi-cmt-buka-${key}`} /></TableCell>
                    <TableCell>
                      <span className="font-medium">{v.vendor_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {[`${v.pos.length} PO`, v.tagihan.length ? `${v.tagihan.length} tagihan terbuka` : null,
                          gabungan ? v.cv.map(ownerLabel).join(' · ') : null].filter(Boolean).join(' · ')}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(v.komitmen)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(v.setor_qc)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(v.dibayar)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(v.ditahan)}</TableCell>
                    <TableCell className="text-right tabular-nums font-semibold" data-testid={`posisi-cmt-boleh-${key}`}>{fmt(v.boleh_dibayar)}</TableCell>
                    <TableCell className="text-right">
                      {bolehBayar && v.vendor_id && v.boleh_dibayar > 0.5 && (
                        <Button size="sm" variant="success" onClick={() => setBayar(v)} data-testid={`posisi-cmt-bayar-${key}`}>Bayar</Button>
                      )}
                    </TableCell>
                  </TableRow>,
                  open && (
                    <RowDetail key={`${key}-rincian`} colSpan={kolom}>
                      <RincianCmt v={v} gabungan={gabungan} bukti={v.vendor_id ? bukti[v.vendor_id] : []} />
                    </RowDetail>
                  ),
                ];
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {bayar && (
        <BayarCmtGabungan token={token} vendor={bayar} onClose={() => setBayar(null)}
          onDone={() => { const vid = bayar.vendor_id; load(); if (vid) muatBukti(vid); }} />
      )}
    </PageLayout>
  );
}
