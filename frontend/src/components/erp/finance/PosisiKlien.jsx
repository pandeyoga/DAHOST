/**
 * Posisi per klien maklon — Keuangan › Piutang, tampilan "Posisi per klien maklon" (16 Nov 2026, owner).
 *
 * Klien memesan beberapa PO sekaligus, barang dikirim penuh/sebagian, dan klien MEMBAYAR GABUNGAN. Per klien dan per
 * PO: nilai PO (komitmen), sudah dikirim (= pendapatan yang sudah dijurnal), sudah ditagih, sudah dibayar, BOLEH
 * DITAGIH (dikirim − ditagih), sisa piutang, uang muka. Sumber: GET /api/dewi/maklon/finance/klien-posisi
 * (core.tagihan_klien — angka piutang PO sama dengan daftar Piutang).
 *
 *   • Buat tagihan  — pilih kiriman (boleh lintas PO satu klien) → satu tagihan bernomor + PDF. Dokumen saja, tanpa jurnal.
 *   • Terima pembayaran — satu penerimaan dibagi ke PO terlama dulu (bisa diubah); batas per PO = dikirim − dibayar;
 *     kelebihan = uang muka klien (dipakai otomatis saat PO-nya mengirim barang).
 * Tombol mengikuti centang Tambah pada Keuangan › Piutang atau Maklon › Piutang Klien (sama dengan catat pembayaran
 * klien per PO). Rincian per PO, tagihan, dan bukti terima dibuka di bawah barisnya (RowDetail).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Banknote, FileDown, FileText, RefreshCw, Search, XCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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
import { punyaCentang } from '../../../lib/rbac';
import { CV_DA, useCvOr } from '@/lib/entitas';
import { formatDateID, formatRupiah } from '@/lib/format';
import { todayWIB } from '@/lib/waktu';
import { TOLERANSI, alokasiTerlama, jumlahAlokasi, kirimAlokasi, lewatBatas, urutkan } from './alokasiGabungan';

const fmt = formatRupiah;
/** Kunci centang endpoint tagihan & terima pembayaran klien (server: dewi_maklon_billing._PAY_PERMS['create']). */
export const CENTANG_PIUTANG_KLIEN = ['mod.mak_billing.create', 'mod.fin_ar.create'];
export const STATUS_TAGIHAN = {
  belum_dibayar: { label: 'Belum dibayar', tone: 'warning' },
  sebagian: { label: 'Dibayar sebagian', tone: 'warning' },
  lunas: { label: 'Lunas', tone: 'success' },
  dibatalkan: { label: 'Dibatalkan', tone: 'muted' },
};

const unduhTagihan = (t) => apiDownload(`/api/dewi/maklon/finance/tagihan-klien/${t.id}/pdf`, `Tagihan_${t.bill_number}.pdf`)
  .catch((e) => toast.error(e.message));
const unduhBukti = (b) => apiDownload(`/api/dewi/maklon/finance/klien-terima-gabungan/${b.id}/pdf`, `Bukti_${b.bukti_number}.pdf`)
  .catch((e) => toast.error(e.message));

// ─── Buat tagihan ──────────────────────────────────────────────────────────────
export function BuatTagihanKlien({ klien, onClose, onDone }) {
  const kiriman = klien.kiriman || [];
  const [pilih, setPilih] = useState(() => Object.fromEntries(kiriman.map((k) => [k.key, true])));
  const [tanggal, setTanggal] = useState(todayWIB());
  const [catatan, setCatatan] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const dipilih = kiriman.filter((k) => pilih[k.key]);
  const total = dipilih.reduce((s, k) => s + Number(k.boleh_ditagih || 0), 0);
  const semua = dipilih.length === kiriman.length && kiriman.length > 0;
  const problem = !kiriman.length ? 'Tidak ada kiriman yang belum ditagih.' : !dipilih.length ? 'Pilih minimal satu kiriman.' : '';
  const simpan = async () => {
    if (problem) { setErr(problem); return; }
    setSaving(true);
    setErr('');
    try {
      const out = await apiPost('/api/dewi/maklon/finance/tagihan-klien', {
        client_id: klien.client_id, keys: dipilih.map((k) => k.key), bill_date: tanggal, notes: catatan || undefined,
      });
      toast.success(`Tagihan ${out?.bill_number} untuk ${klien.client_name} dibuat · ${fmt(out?.total)}`,
        { duration: 10000, action: { label: 'Unduh PDF', onClick: () => unduhTagihan(out) } });
      onDone?.(out);
      onClose();
    } catch (e) { setErr(e.message); toast.error(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="tagihan-klien-buat" judul={`Buat tagihan ${klien.client_name}`}
      keterangan="Pilih kiriman yang ditagih — boleh dari beberapa PO klien ini. Tagihan hanya dokumen; pendapatan sudah dicatat saat barang dikirim."
      onSimpan={simpan} menyimpan={saving} bisaSimpan={!problem} labelSimpan="Buat tagihan" galat={err || undefined}
      adaIsian={dipilih.length > 0 && !semua}>
      <GlassCard className="p-0 overflow-x-auto">
        <Table data-testid="tagihan-klien-buat-tabel">
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox checked={semua ? true : dipilih.length ? 'indeterminate' : false} aria-label="Pilih semua kiriman"
                  onCheckedChange={(v) => setPilih(Object.fromEntries(kiriman.map((k) => [k.key, !!v])))} />
              </TableHead>
              <TableHead>PO</TableHead>
              <TableHead>Surat jalan</TableHead>
              <TableHead>Tanggal kirim</TableHead>
              <TableHead className="text-right">Nilai kiriman</TableHead>
              <TableHead className="text-right">Sudah ditagih</TableHead>
              <TableHead className="text-right">Ditagih sekarang</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {kiriman.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={7} className="p-0 [&>div]:py-6">
                  <EmptyState icon={FileText} title="Semua kiriman sudah ditagih"
                    description="Yang boleh ditagih hanya barang yang sudah dikirim ke klien." />
                </TableCell>
              </TableRow>
            )}
            {kiriman.map((k) => (
              <TableRow key={k.key} data-testid={`tagihan-klien-kiriman-${k.key}`}>
                <TableCell>
                  <Checkbox checked={!!pilih[k.key]} aria-label={`Tagih kiriman ${k.shipment_number} PO ${k.po_number}`}
                    onCheckedChange={(v) => setPilih((p) => ({ ...p, [k.key]: !!v }))} />
                </TableCell>
                <TableCell className="font-medium">{k.po_number}</TableCell>
                <TableCell>{k.shipment_number || '—'}<span className="block text-xs text-muted-foreground">kirim ke-{k.dispatch_seq}</span></TableCell>
                <TableCell className="whitespace-nowrap">{k.tanggal ? formatDateID(k.tanggal) : '—'}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(k.total)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(k.sudah_ditagih)}</TableCell>
                <TableCell className="text-right tabular-nums font-semibold">{fmt(k.boleh_ditagih)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </GlassCard>
      <p className="text-sm text-muted-foreground" data-testid="tagihan-klien-buat-total">
        {dipilih.length} kiriman · total tagihan <b className="text-foreground tabular-nums">{fmt(total)}</b>
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Tanggal tagihan">
          <DatePicker value={tanggal} onChange={(v) => setTanggal(v || todayWIB())} bolehKosong={false} testId="tagihan-klien-buat-tanggal" />
        </Isian>
        <Isian label="Catatan" htmlFor="tagihan-klien-buat-catatan">
          <Input id="tagihan-klien-buat-catatan" value={catatan} onChange={(e) => setCatatan(e.target.value)} placeholder="Opsional, tercetak di tagihan" />
        </Isian>
      </div>
    </FormPopup>
  );
}

// ─── Batal tagihan ─────────────────────────────────────────────────────────────
function BatalTagihan({ tagihan, onClose, onDone }) {
  const [alasan, setAlasan] = useState('');
  const [saving, setSaving] = useState(false);
  const simpan = async () => {
    setSaving(true);
    try {
      await apiPost(`/api/dewi/maklon/finance/tagihan-klien/${tagihan.id}/batal`, { reason: alasan.trim() });
      toast.success(`Tagihan ${tagihan.bill_number} dibatalkan; kirimannya bisa ditagih ulang.`);
      onDone?.();
      onClose();
    } catch (e) { toast.error(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="tagihan-klien-batal" judul={`Batalkan tagihan ${tagihan.bill_number}`}
      keterangan="Hanya tagihan yang belum ada pembayarannya. Tidak ada jurnal yang berubah."
      onSimpan={simpan} menyimpan={saving} bisaSimpan={alasan.trim().length >= 3} labelSimpan="Batalkan tagihan"
      warnaSimpan="destructive" adaIsian={alasan.trim().length > 0}>
      <Isian label="Alasan" wajib htmlFor="tagihan-klien-batal-alasan">
        <Textarea id="tagihan-klien-batal-alasan" rows={3} value={alasan} onChange={(e) => setAlasan(e.target.value)}
          placeholder="Mis. salah pilih kiriman" data-testid="tagihan-klien-batal-alasan" />
      </Isian>
    </FormPopup>
  );
}

// ─── Terima pembayaran gabungan ────────────────────────────────────────────────
export function TerimaKlienGabungan({ token, klien, onClose, onDone }) {
  // uang klien maklon masuk rekening CV Sukma (buku piutang maklon)
  const { accounts, loaded } = usePaymentCashAccounts(token, 'SMU');
  const pos = useMemo(() => urutkan((klien.pos || []).map((r) => ({ ...r, id: r.ar_id, nomor: r.po_number }))), [klien]);
  const terbuka = useMemo(() => pos.filter((r) => Number(r.sisa_piutang) > 0.005), [pos]);
  const batas = useMemo(() => Object.fromEntries(terbuka.map((r) => [r.ar_id, Number(r.sisa_piutang)])), [terbuka]);
  const sisaPiutang = terbuka.reduce((s, r) => s + Number(r.sisa_piutang || 0), 0);
  const tagihanPo = useMemo(() => {
    const out = {};
    (klien.tagihan || []).filter((t) => ['belum_dibayar', 'sebagian'].includes(t.status_bayar)).forEach((t) => {
      (t.lines || []).forEach((ln) => { (out[ln.ar_id] = out[ln.ar_id] || new Set()).add(t.bill_number); });
    });
    return out;
  }, [klien]);
  const usul = (jml) => alokasiTerlama(Number(jml || 0), terbuka.map((r) => ({ id: r.ar_id, batas: r.sisa_piutang, urut: r.urut, nomor: r.po_number }))).alokasi;
  const [amount, setAmount] = useState(() => String(Math.round(sisaPiutang)));
  const [alokasi, setAlokasi] = useState(() => usul(Math.round(sisaPiutang)));
  const [accountId, setAccountId] = useState('');
  const [date, setDate] = useState(todayWIB());
  const [ref, setRef] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const cash = Number(amount || 0);
  const dibagi = jumlahAlokasi(alokasi);
  const kelebihan = Math.max(0, cash - dibagi);
  // ruang uang muka = sisa nilai PO yang masih menunggu kiriman (jalur uang muka yang sama dengan server)
  const ruangUangMuka = pos.filter((r) => Number(r.belum_dikirim) > 0.5)
    .reduce((s, r) => s + Math.max(0, Number(r.batas_terima || 0) - Number(alokasi[r.ar_id] || 0)), 0);
  const lewat = lewatBatas(alokasi, batas);
  const problem = !accountId ? 'Pilih rekening penerima.'
    : !(cash > 0) ? 'Jumlah diterima harus lebih dari 0.'
      : lewat.length ? 'Ada pembagian yang melebihi sisa piutang PO-nya (sudah dikirim − sudah dibayar).'
        : dibagi > cash + TOLERANSI ? `Pembagian ${fmt(dibagi)} melebihi jumlah diterima ${fmt(cash)}.`
          : kelebihan > ruangUangMuka + TOLERANSI
            ? `Kelebihan ${fmt(kelebihan - ruangUangMuka)} tidak bisa jadi uang muka: tidak ada PO yang masih menunggu kiriman dengan sisa nilai cukup.`
            : '';
  const simpan = async () => {
    if (problem) { setErr(problem); return; }
    setErr('');
    setSaving(true);
    try {
      const out = await apiPost('/api/dewi/maklon/finance/klien-terima-gabungan', {
        client_id: klien.client_id, amount: cash, cash_account_id: accountId, payment_date: date,
        reference_no: ref || undefined, notes: notes || undefined, alokasi: kirimAlokasi(alokasi),
      });
      toast.success(`Penerimaan ${fmt(cash)} dari ${klien.client_name} tercatat · ${out?.bukti_number}`
        + (Number(out?.ke_uang_muka) > 0.5 ? ` (uang muka ${fmt(out.ke_uang_muka)})` : ''),
      { duration: 10000, action: { label: 'Unduh bukti', onClick: () => unduhBukti(out) } });
      onDone?.(out);
      onClose();
    } catch (e) { setErr(e.message); toast.error(e.message); } finally { setSaving(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" testId="klien-terima-gabungan" judul={`Terima pembayaran ${klien.client_name}`}
      keterangan="Satu penerimaan untuk beberapa PO. Dibagi ke yang terlama dulu; boleh diubah. Kelebihan dicatat sebagai uang muka klien."
      onSimpan={simpan} menyimpan={saving} bisaSimpan={!problem} labelSimpan="Simpan penerimaan"
      adaIsian={cash > 0 && !!accountId} galat={err || (accountId ? problem : '') || undefined}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Isian label="Masuk ke rekening" wajib petunjuk="Rekening CV Sukma (buku piutang maklon).">
          <CashAccountSelect accounts={accounts} loaded={loaded} value={accountId} onChange={setAccountId} testId="klien-terima-gabungan-rekening" />
        </Isian>
        <Isian label="Jumlah diterima" wajib htmlFor="klien-terima-gabungan-jumlah" petunjuk={`Sisa piutang dari kiriman ${fmt(sisaPiutang)}`}>
          <MoneyInput id="klien-terima-gabungan-jumlah" value={amount} data-testid="klien-terima-gabungan-jumlah"
            onChange={(e) => { setAmount(e.target.value); setAlokasi(usul(e.target.value)); }} />
        </Isian>
        <Isian label="Tanggal">
          <DatePicker value={date} onChange={(v) => setDate(v || todayWIB())} bolehKosong={false} testId="klien-terima-gabungan-tanggal" />
        </Isian>
        <Isian label="No. referensi" htmlFor="klien-terima-gabungan-ref">
          <Input id="klien-terima-gabungan-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Mis. nomor transfer" />
        </Isian>
      </div>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-foreground">Pembagian ke PO</p>
          <Button type="button" variant="outline" size="sm" onClick={() => setAlokasi(usul(amount))} data-testid="klien-terima-gabungan-bagi-ulang">
            Bagi ulang terlama dulu
          </Button>
        </div>
        <GlassCard className="p-0 overflow-x-auto">
          <Table data-testid="klien-terima-gabungan-tabel">
            <TableHeader>
              <TableRow>
                <TableHead>PO</TableHead>
                <TableHead>Tagihan</TableHead>
                <TableHead className="text-right">Sisa piutang</TableHead>
                <TableHead className="text-right w-44">Diterima untuk PO ini</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {terbuka.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="p-0 [&>div]:py-6">
                    <EmptyState icon={Banknote} title="Belum ada piutang dari kiriman"
                      description="Seluruh penerimaan akan dicatat sebagai uang muka klien untuk PO yang masih menunggu kiriman." />
                  </TableCell>
                </TableRow>
              )}
              {terbuka.map((r) => {
                const lebih = Number(alokasi[r.ar_id] || 0) > Number(r.sisa_piutang) + 0.01;
                return (
                  <TableRow key={r.ar_id} data-testid={`klien-terima-gabungan-baris-${r.ar_id}`}>
                    <TableCell className="font-medium">{r.po_number}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{[...(tagihanPo[r.ar_id] || [])].join(', ') || 'belum ditagih'}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(r.sisa_piutang)}</TableCell>
                    <TableCell className="text-right">
                      <MoneyInput value={alokasi[r.ar_id] ?? ''} aria-label={`Diterima untuk PO ${r.po_number}`}
                        className={lebih ? 'border-[hsl(var(--destructive))]' : ''} data-testid={`klien-terima-gabungan-isi-${r.ar_id}`}
                        onChange={(e) => setAlokasi((a) => ({ ...a, [r.ar_id]: e.target.value }))} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </GlassCard>
        <p className="text-sm text-muted-foreground" data-testid="klien-terima-gabungan-ringkas">
          Ke piutang <b className="text-foreground tabular-nums">{fmt(Math.min(dibagi, cash))}</b>
          {kelebihan > TOLERANSI && <> · uang muka klien <b className="text-foreground tabular-nums">{fmt(kelebihan)}</b> (dipakai otomatis saat PO-nya mengirim barang)</>}
        </p>
      </div>
      <Isian label="Catatan" htmlFor="klien-terima-gabungan-catatan">
        <Input id="klien-terima-gabungan-catatan" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Opsional" />
      </Isian>
    </FormPopup>
  );
}

// ─── Rincian satu klien (di bawah barisnya) ───────────────────────────────────
function RincianKlien({ c, bolehCatat, bukti, onBatal }) {
  return (
    <div className="space-y-3" data-testid={`posisi-klien-rincian-${c.client_id}`}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>PO</TableHead>
            <TableHead className="text-right">Nilai PO (komitmen)</TableHead>
            <TableHead className="text-right">Sudah dikirim</TableHead>
            <TableHead className="text-right">Sudah ditagih</TableHead>
            <TableHead className="text-right">Sudah dibayar</TableHead>
            <TableHead className="text-right">Boleh ditagih</TableHead>
            <TableHead className="text-right">Sisa piutang</TableHead>
            <TableHead className="text-right">Uang muka</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {c.pos.length === 0 && (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={8} className="p-0 [&>div]:py-4">
                <EmptyState icon={Banknote} title="Semua PO klien ini sudah selesai"
                  description="Tidak ada kiriman yang belum ditagih maupun piutang yang belum dibayar." />
              </TableCell>
            </TableRow>
          )}
          {c.pos.map((r) => (
            <TableRow key={r.ar_id}>
              <TableCell>
                <span className="font-medium">{r.po_number}</span>
                <span className="block text-xs text-muted-foreground">
                  {[r.invoice_number, r.belum_dikirim > 0.5 ? `belum dikirim ${fmt(r.belum_dikirim)}` : null].filter(Boolean).join(' · ')}
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.komitmen)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.dikirim)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.ditagih)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.dibayar)}</TableCell>
              <TableCell className="text-right tabular-nums font-semibold">{fmt(r.boleh_ditagih)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.sisa_piutang)}</TableCell>
              <TableCell className="text-right tabular-nums">{fmt(r.uang_muka)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">Tagihan gabungan</p>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nomor</TableHead>
              <TableHead>Tanggal</TableHead>
              <TableHead>Jatuh tempo</TableHead>
              <TableHead>PO</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Sisa</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Aksi</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {c.tagihan.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={8} className="p-0 [&>div]:py-4">
                  <EmptyState icon={FileText} title="Belum ada tagihan gabungan"
                    description="Tekan Buat tagihan di baris klien ini untuk menagih kiriman yang sudah dikirim." />
                </TableCell>
              </TableRow>
            )}
            {c.tagihan.map((t) => (
              <TableRow key={t.id} data-testid={`posisi-klien-tagihan-${t.id}`}>
                <TableCell className="font-medium">{t.bill_number}</TableCell>
                <TableCell className="whitespace-nowrap">{formatDateID(t.bill_date)}</TableCell>
                <TableCell className="whitespace-nowrap">{t.due_date ? formatDateID(t.due_date) : '—'}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{(t.po_numbers || []).join(', ')}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(t.total)}</TableCell>
                <TableCell className="text-right tabular-nums">{fmt(t.sisa)}</TableCell>
                <TableCell><StatusBadge status={t.status_bayar} label={STATUS_TAGIHAN[t.status_bayar]?.label} tone={STATUS_TAGIHAN[t.status_bayar]?.tone} /></TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  <div className="flex items-center justify-end gap-1">
                    <Button variant="ghost" size="icon-sm" title="Unduh tagihan (PDF)" aria-label="Unduh tagihan (PDF)" data-cv-allow=""
                      onClick={() => unduhTagihan(t)}><FileDown className="w-4 h-4" /></Button>
                    {bolehCatat && t.status === 'aktif' && Number(t.dibayar) <= 0.5 && (
                      <Button variant="ghost" size="icon-sm" title="Batalkan tagihan" aria-label="Batalkan tagihan"
                        data-testid={`posisi-klien-batal-${t.id}`} onClick={() => onBatal(t)}><XCircle className="w-4 h-4" /></Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">Bukti terima gabungan</p>
        {bukti === undefined ? <Skeleton className="h-9 rounded-lg" /> : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nomor</TableHead>
                  <TableHead>Tanggal</TableHead>
                  <TableHead className="text-right">Jumlah</TableHead>
                  <TableHead className="text-right">Ke piutang</TableHead>
                  <TableHead className="text-right">Uang muka</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bukti.length === 0 && (
                  <TableRow className="hover:bg-transparent">
                    <TableCell colSpan={6} className="p-0 [&>div]:py-4">
                      <EmptyState icon={Banknote} title="Belum ada bukti terima gabungan"
                        description="Tekan Terima pembayaran di baris klien ini untuk satu penerimaan beberapa PO." />
                    </TableCell>
                  </TableRow>
                )}
                {bukti.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="font-medium">{b.bukti_number}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDateID(b.tanggal)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(b.amount)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(b.ke_piutang)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(b.ke_uang_muka)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="icon-sm" title="Unduh bukti (PDF)" aria-label="Unduh bukti (PDF)" data-cv-allow=""
                        onClick={() => unduhBukti(b)}><FileDown className="w-4 h-4" /></Button>
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
export default function PosisiKlien({ token, hasPerm, toggle }) {
  const cv = useCvOr();
  const bolehCatat = punyaCentang(hasPerm, CENTANG_PIUTANG_KLIEN);
  const [data, setData] = useState({ clients: [], totals: {} });
  const [loading, setLoading] = useState(true);
  const [gagal, setGagal] = useState('');
  const [cari, setCari] = useState('');
  const [saring, setSaring] = useState('terbuka');
  const [buka, setBuka] = useState({});
  const [bukti, setBukti] = useState({});
  const [tagih, setTagih] = useState(null);
  const [terima, setTerima] = useState(null);
  const [batal, setBatal] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiGet('/api/dewi/maklon/finance/klien-posisi'));
      setGagal('');
    } catch (e) {
      setGagal(e.message);
      toast.error(`Posisi klien gagal dimuat: ${e.message}`);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load, cv]);
  const muatBukti = useCallback(async (cid) => {
    try {
      const d = await apiGet(`/api/dewi/maklon/finance/klien-terima-gabungan?client_id=${encodeURIComponent(cid)}`);
      setBukti((b) => ({ ...b, [cid]: d?.items || [] }));
    } catch (e) { setBukti((b) => ({ ...b, [cid]: [] })); toast.error(e.message); }
  }, []);
  const toggleBuka = (cid) => {
    setBuka((o) => ({ ...o, [cid]: !o[cid] }));
    if (!buka[cid] && bukti[cid] === undefined) muatBukti(cid);
  };
  const segarkan = (cid) => { load(); if (cid) muatBukti(cid); };

  const semua = useMemo(() => data.clients || [], [data]);
  const dasar = useMemo(() => {
    const s = cari.trim().toLowerCase();
    return semua.filter((c) => !s || [c.client_name, c.client_code, ...(c.pos || []).map((r) => r.po_number)]
      .some((x) => String(x || '').toLowerCase().includes(s)));
  }, [semua, cari]);
  const adaTerbuka = (c) => c.boleh_ditagih > 0.5 || c.sisa_piutang > 0.5;
  const rows = saring === 'terbuka' ? dasar.filter(adaTerbuka) : dasar;
  const tot = useMemo(() => ['komitmen', 'dikirim', 'ditagih', 'dibayar', 'boleh_ditagih', 'sisa_piutang', 'uang_muka', 'belum_dikirim']
    .reduce((o, k) => ({ ...o, [k]: dasar.reduce((t, c) => t + Number(c[k] || 0), 0) }), {}), [dasar]);
  const kolom = 9;

  return (
    <PageLayout
      testId="fin-piutang-posisi-klien"
      title="Piutang"
      subtitle="Posisi per klien maklon: nilai PO sebagai komitmen, yang sudah dikirim, ditagih, dibayar, dan boleh ditagih."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="Cari klien atau no. PO" value={cari}
            onChange={(e) => setCari(e.target.value)} data-testid="posisi-klien-cari" />
        </div>
        <FilterChips value={saring} onChange={setSaring} testId="posisi-klien-saring" ariaLabel="Penyaring klien" hideWhenEmpty={false}
          options={[{ key: 'terbuka', label: 'Ada yang ditagih / dibayar', count: dasar.filter(adaTerbuka).length },
            { key: 'semua', label: 'Semua klien', count: dasar.length }]} />
      </>}
      tools={<>
        {toggle}
        <TombolUnduh namaBerkas={`posisi-klien-${todayWIB()}`} namaLembar="Posisi klien" testId="posisi-klien-unduh"
          baris={rows.flatMap((c) => c.pos.map((r) => ({ ...r, klien: c.client_name })))}
          kolom={[
            { label: 'Klien', nilai: (r) => r.klien }, { label: 'PO', nilai: (r) => r.po_number },
            { label: 'Nilai PO (komitmen)', nilai: (r) => r.komitmen }, { label: 'Sudah dikirim', nilai: (r) => r.dikirim },
            { label: 'Sudah ditagih', nilai: (r) => r.ditagih }, { label: 'Sudah dibayar', nilai: (r) => r.dibayar },
            { label: 'Boleh ditagih', nilai: (r) => r.boleh_ditagih }, { label: 'Sisa piutang', nilai: (r) => r.sisa_piutang },
            { label: 'Uang muka', nilai: (r) => r.uang_muka }, { label: 'Belum dikirim', nilai: (r) => r.belum_dikirim },
          ]} />
        <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="posisi-klien-muat-ulang">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </>}
      summary={<>
        {gagal && <Notice tone="danger" title="Posisi klien gagal dimuat">{gagal}</Notice>}
        {cv === CV_DA && (
          <Notice tone="info" testId="posisi-klien-cv-da">Piutang klien maklon dibukukan di CV Sukma — pilih CV Sukma atau Gabungan di bagian atas.</Notice>
        )}
        {dasar.length > 0 && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="posisi-klien-ringkasan">
            <StatTile label="Nilai PO (komitmen)" value={fmt(tot.komitmen)} testId="posisi-klien-komitmen"
              hint="Nilai PO maklon yang masih berjalan. Bukan piutang dan tidak dijurnal." sub={`belum dikirim ${fmt(tot.belum_dikirim)}`} />
            <StatTile label="Sudah dikirim" value={fmt(tot.dikirim)} testId="posisi-klien-dikirim"
              hint="Pendapatan yang sudah dijurnal saat barang dikirim ke klien." sub={`sudah ditagih ${fmt(tot.ditagih)}`} />
            <StatTile label="Boleh ditagih" value={fmt(tot.boleh_ditagih)} accent="primary" testId="posisi-klien-boleh"
              hint="Sudah dikirim − sudah ditagih. Kiriman yang sudah lunas sebelum ditagih tidak perlu ditagih." />
            <StatTile label="Sisa piutang" value={fmt(tot.sisa_piutang)} testId="posisi-klien-sisa"
              hint="Sudah dikirim − sudah dibayar − denda." sub={tot.uang_muka > 0.5 ? `uang muka ${fmt(tot.uang_muka)}` : undefined} />
          </div>
        )}
      </>}
    >
      <GlassCard className="p-0 overflow-x-auto">
        {loading && !semua.length ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-11 rounded-lg" />)}</div>
        ) : (
          <Table data-testid="posisi-klien-tabel" className="md:min-w-0">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead>Klien</TableHead>
                <TableHead className="text-right">Nilai PO (komitmen)</TableHead>
                <TableHead className="text-right">Sudah dikirim</TableHead>
                <TableHead className="text-right">Sudah ditagih</TableHead>
                <TableHead className="text-right">Sudah dibayar</TableHead>
                <TableHead className="text-right">Boleh ditagih</TableHead>
                <TableHead className="text-right">Sisa piutang</TableHead>
                <TableHead className="text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={kolom} className="p-0 [&>div]:py-8">
                    <EmptyState icon={Banknote} testId="posisi-klien-kosong"
                      title={dasar.length ? 'Tidak ada yang perlu ditagih atau dibayar' : 'Belum ada piutang klien maklon'}
                      description={dasar.length ? 'Pilih "Semua klien" untuk melihat PO yang masih menunggu kiriman.'
                        : 'Posisi muncul setelah PO maklon dikonfirmasi; yang boleh ditagih lahir saat barang dikirim.'} />
                  </TableCell>
                </TableRow>
              )}
              {rows.map((c) => {
                const open = !!buka[c.client_id];
                return [
                  <TableRow key={c.client_id} data-testid={`posisi-klien-baris-${c.client_id}`}>
                    <TableCell><RowToggle open={open} onClick={() => toggleBuka(c.client_id)} label="Lihat per PO" testId={`posisi-klien-buka-${c.client_id}`} /></TableCell>
                    <TableCell>
                      <span className="font-medium">{c.client_name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {[c.client_code, `${c.pos.length} PO berjalan`,
                          c.tagihan_terbuka > 0.5 ? `tagihan terbuka ${fmt(c.tagihan_terbuka)}` : null,
                          c.uang_muka > 0.5 ? `uang muka ${fmt(c.uang_muka)}` : null].filter(Boolean).join(' · ')}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(c.komitmen)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(c.dikirim)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(c.ditagih)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(c.dibayar)}</TableCell>
                    <TableCell className="text-right tabular-nums font-semibold" data-testid={`posisi-klien-boleh-${c.client_id}`}>{fmt(c.boleh_ditagih)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(c.sisa_piutang)}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      {bolehCatat && (
                        <div className="flex items-center justify-end gap-1">
                          {c.boleh_ditagih > 0.5 && (
                            <Button size="sm" variant="outline" onClick={() => setTagih(c)} data-testid={`posisi-klien-tagih-${c.client_id}`}>Buat tagihan</Button>
                          )}
                          {(c.sisa_piutang > 0.5 || c.belum_dikirim > 0.5) && (
                            <Button size="sm" variant="success" onClick={() => setTerima(c)} data-testid={`posisi-klien-terima-${c.client_id}`}>Terima pembayaran</Button>
                          )}
                        </div>
                      )}
                    </TableCell>
                  </TableRow>,
                  open && (
                    <RowDetail key={`${c.client_id}-rincian`} colSpan={kolom}>
                      <RincianKlien c={c} bolehCatat={bolehCatat} bukti={bukti[c.client_id]} onBatal={setBatal} />
                    </RowDetail>
                  ),
                ];
              })}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      {tagih && <BuatTagihanKlien klien={tagih} onClose={() => setTagih(null)} onDone={() => segarkan(tagih.client_id)} />}
      {terima && <TerimaKlienGabungan token={token} klien={terima} onClose={() => setTerima(null)} onDone={() => segarkan(terima.client_id)} />}
      {batal && <BatalTagihan tagihan={batal} onClose={() => setBatal(null)} onDone={() => segarkan(batal.client_id)} />}
    </PageLayout>
  );
}
