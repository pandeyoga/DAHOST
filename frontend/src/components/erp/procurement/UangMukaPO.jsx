/**
 * UangMukaPO — bayar di muka (CBD) / DP di detail PO (owner 27 Nov 2026: "bagaimana jika pembayarannya CBD?").
 *
 * Uang muka dicatat Keuangan SEBELUM barang datang (Dr Uang Muka Pembelian / Cr rekening). Saat barang diterima, tagihan
 * otomatis langsung dipotong uang muka PO ini. Sisa yang tidak terpakai bisa dikembalikan; salah catat bisa dibatalkan
 * selama belum terpakai. Aturan & jurnal: backend `core/uang_muka_pemasok.py`.
 */
import { useCallback, useEffect, useState } from 'react';
import { RotateCcw, Undo2, Wallet } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { MoneyInput } from '@/components/ui/money-input';
import DatePicker from '@/components/ui/date-picker';
import { Textarea } from '@/components/ui/textarea';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiFetch, ApiError } from '@/lib/apiFetch';
import { todayWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import { Notice, StatusBadge } from '../moduleAtoms';

const rp = (v) => `Rp ${Math.round(Number(v) || 0).toLocaleString('id-ID')}`;
const STATUS = { aktif: { label: 'Aktif', tone: 'info' }, habis: { label: 'Terpakai habis', tone: 'success' },
  batal: { label: 'Dibatalkan', tone: 'muted' } };
const BOLEH_BAYAR = ['approved', 'partially_received'];
const galat = (e, cadangan) => (e instanceof ApiError && typeof e.detail === 'string' ? e.detail : cadangan);

export default function UangMukaPO({ po, onChanged }) {
  const [data, setData] = useState({ items: [], total: 0, sisa: 0 });
  const [rekening, setRekening] = useState([]);
  const [form, setForm] = useState(null);   // {mode:'bayar'|'kembali', adv?, amount, cash_account_id, date, notes}
  const [simpan, setSimpan] = useState(false);

  const muat = useCallback(async () => {
    if (!po?.id) return;
    try {
      setData(await apiFetch(`/rahaza/purchase-orders/${po.id}/uang-muka`));
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) toast.error('Gagal memuat uang muka PO');
    }
  }, [po?.id]);
  useEffect(() => { muat(); }, [muat]);

  const bukaForm = async (mode, adv) => {
    if (!rekening.length) {
      try {
        const r = await apiFetch('/rahaza/cash-accounts');
        setRekening((Array.isArray(r) ? r : []).filter((a) => a.active !== false));
      } catch { /* daftar kosong — pengguna tetap melihat formnya */ }
    }
    const nilaiPo = Number(po.grand_total ?? po.total_value ?? 0);
    setForm({ mode, adv, cash_account_id: '', date: todayWIB(), notes: '',
      amount: mode === 'bayar' ? Math.max(0, Math.round(nilaiPo - Number(data.total || 0))) : Math.round(adv?.sisa || 0) });
  };

  const kirim = async () => {
    setSimpan(true);
    try {
      const body = { amount: Number(form.amount) || 0, cash_account_id: form.cash_account_id, date: form.date, notes: form.notes };
      const url = form.mode === 'bayar' ? `/rahaza/purchase-orders/${po.id}/uang-muka`
        : `/rahaza/purchase-orders/${po.id}/uang-muka/${form.adv.id}/kembalikan`;
      await apiFetch(url, { method: 'POST', body });
      toast.success(form.mode === 'bayar' ? 'Uang muka tercatat' : 'Pengembalian uang muka tercatat');
      setForm(null);
      await muat();
      onChanged?.();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) toast.error(galat(e, 'Gagal menyimpan'));
    } finally {
      setSimpan(false);
    }
  };

  const batal = async (adv) => {
    const alasan = await confirmDialog({
      title: `Batalkan uang muka ${adv.nomor}?`,
      body: 'Jurnalnya dibatalkan dan mutasi kasnya dihapus. Hanya untuk salah catat — uang muka yang sudah memotong tagihan tidak bisa dibatalkan.',
      input: { label: 'Alasan (wajib, minimal 10 huruf)', minLength: 10, placeholder: 'Mis. salah nominal, transfer belum jadi' },
      confirmLabel: 'Batalkan uang muka', cancelLabel: 'Kembali', danger: true,
    });
    if (!alasan) return;
    try {
      await apiFetch(`/rahaza/purchase-orders/${po.id}/uang-muka/${adv.id}/batal`, { method: 'POST', body: { alasan } });
      toast.success('Uang muka dibatalkan');
      await muat();
      onChanged?.();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) toast.error(galat(e, 'Gagal membatalkan uang muka'));
    }
  };

  const items = data.items || [];
  const bolehBayar = BOLEH_BAYAR.includes(po.status);
  const cbdBelumBayar = po.payment_terms === 'cbd' && bolehBayar && !(Number(data.total) > 0);
  if (!items.length && !bolehBayar) return null;

  return (
    <div className="space-y-2" data-testid="po-uang-muka">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-foreground">Uang muka ke pemasok</p>
          <p className="text-xs text-muted-foreground">
            Dibayar sebelum barang datang. Saat barang diterima, tagihannya otomatis dipotong uang muka ini.
            {Number(data.sisa) > 0 && ` Sisa belum terpakai ${rp(data.sisa)}.`}
          </p>
        </div>
        {bolehBayar && (
          <Button size="sm" variant="outline" onClick={() => bukaForm('bayar')} data-testid="po-uang-muka-bayar">
            <Wallet />Bayar di muka
          </Button>
        )}
      </div>
      {cbdBelumBayar && (
        <Notice tone="warning" title="Termin PO ini Bayar di muka">
          Catat uang mukanya di sini setelah uang dikirim ke pemasok, supaya tagihannya terpotong saat barang diterima.
        </Notice>
      )}
      {items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Uang muka</TableHead>
              <TableHead className="text-right">Nilai</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Terpakai</TableHead>
              <TableHead className="text-right">Sisa</TableHead>
              <TableHead className="hidden sm:table-cell">Status</TableHead>
              <TableHead className="text-right"><span className="sr-only">Aksi</span></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((a) => (
              <TableRow key={a.id} data-testid={`po-uang-muka-${a.nomor}`}>
                <TableCell>
                  <span className="font-medium">{a.nomor}</span>
                  <span className="block text-xs text-muted-foreground">{formatDateID(a.date)} · {a.cash_account_name}</span>
                </TableCell>
                <TableCell className="whitespace-nowrap text-right tabular-nums">{rp(a.amount)}</TableCell>
                <TableCell className="hidden whitespace-nowrap text-right tabular-nums sm:table-cell">
                  {rp(a.terpakai)}{Number(a.dikembalikan) > 0 && <span className="block text-xs text-muted-foreground">dikembalikan {rp(a.dikembalikan)}</span>}
                </TableCell>
                <TableCell className="whitespace-nowrap text-right tabular-nums">{rp(a.sisa)}</TableCell>
                <TableCell className="hidden sm:table-cell">
                  <StatusBadge status={a.status} label={STATUS[a.status]?.label || a.status} tone={STATUS[a.status]?.tone} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-right">
                  {a.status === 'aktif' && Number(a.sisa) > 0 && (
                    <Button size="sm" variant="link" onClick={() => bukaForm('kembali', a)}><RotateCcw />Kembalikan</Button>
                  )}
                  {a.status === 'aktif' && !(Number(a.terpakai) > 0) && !(Number(a.dikembalikan) > 0) && (
                    <Button size="sm" variant="link" onClick={() => batal(a)}><Undo2 />Batalkan</Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <FormPopup open={!!form} onClose={() => setForm(null)} onSimpan={kirim} menyimpan={simpan}
        judul={form?.mode === 'bayar' ? `Bayar di muka · PO ${po.po_number}` : `Kembalikan uang muka ${form?.adv?.nomor || ''}`}
        keterangan={form?.mode === 'bayar'
          ? 'Uang yang dikirim ke pemasok sebelum barang datang. Nanti otomatis memotong tagihan PO ini.'
          : 'Pemasok mengembalikan sisa uang muka yang tidak terpakai.'}
        labelSimpan={form?.mode === 'bayar' ? 'Catat uang muka' : 'Catat pengembalian'}
        bisaSimpan={!!form && Number(form.amount) > 0 && !!form.cash_account_id} testId="po-uang-muka-form">
        {form && (<>
          <Isian label="Nilai (Rp)" wajib htmlFor="um-nilai"
            petunjuk={form.mode === 'bayar' ? `Nilai PO ${rp(po.grand_total ?? po.total_value)}, sudah dibayar di muka ${rp(data.total)}.` : `Sisa uang muka ${rp(form.adv?.sisa)}.`}>
            <MoneyInput id="um-nilai" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })}
              className="text-right" data-testid="um-nilai" />
          </Isian>
          <Isian label={form.mode === 'bayar' ? 'Dibayar dari rekening' : 'Diterima di rekening'} wajib htmlFor="um-rekening">
            <SmartNativeSelect id="um-rekening" value={form.cash_account_id}
              onChange={(e) => setForm({ ...form, cash_account_id: e.target.value })} data-testid="um-rekening">
              <option value="">Pilih rekening</option>
              {rekening.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </SmartNativeSelect>
          </Isian>
          <Isian label="Tanggal">
            <DatePicker value={form.date} onChange={(v) => setForm({ ...form, date: v })} bolehKosong={false} testId="um-tanggal" />
          </Isian>
          <Isian label="Catatan" htmlFor="um-catatan">
            <Textarea id="um-catatan" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Mis. nomor transfer" />
          </Isian>
        </>)}
      </FormPopup>
    </div>
  );
}
