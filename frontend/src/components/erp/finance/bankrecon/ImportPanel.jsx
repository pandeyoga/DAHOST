import { useState } from 'react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import FilterChips from '@/components/ui/filter-chips';
import { GlassInput } from '@/components/ui/glass';
import { Textarea } from '@/components/ui/textarea';
import DatePicker from '@/components/ui/date-picker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Loader2, Upload } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { MoneyInput } from '@/components/ui/money-input';

const API = process.env.REACT_APP_BACKEND_URL;

const MODES = [
  { key: 'file', label: 'Unggah CSV' },
  { key: 'paste', label: 'Tempel teks' },
  { key: 'manual', label: 'Isi manual' },
];

// Impor mutasi rekening koran: file CSV, tempel teks, atau isi manual satu baris.
// 2026-11-05 (PANDUAN_UI G4/G5/G6): bagian polos di dalam DetailPanel (dulu kotak abu di dalam kartu);
// deret tombol buatan sendiri → FilterChips; <select>/<input> polos → SmartNativeSelect/GlassInput.
export function ImportPanel({ sessionId, headers, onDone }) {
  const { toast } = useToast();
  const [tab, setTab] = useState('file');
  const [busy, setBusy] = useState(false);
  const [bulkText, setBulkText] = useState('');
  const [form, setForm] = useState({ txn_date: '', description: '', reference: '', amount: '', direction: 'in' });
  const base = `${API}/api/finance/bank-recon/sessions/${sessionId}`;
  const fail = (e) => toast({ title: 'Gagal', description: e?.response?.data?.detail || e.message, variant: 'destructive' });

  const uploadCsv = async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData(); fd.append('file', file);
      const { data } = await axios.post(`${base}/import-csv`, fd, { headers: { ...headers, 'Content-Type': 'multipart/form-data' } });
      toast({ title: 'Impor CSV', description: data.message }); onDone();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const importBulk = async () => {
    const transactions = bulkText.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
      const p = l.split(',').map(x => x.trim());
      return { txn_date: p[0], description: p[1] || '', amount: parseFloat(p[2]) || 0,
        direction: (p[3] || 'in').toLowerCase().startsWith('k') || (p[3] || '').toLowerCase() === 'out' ? 'out' : 'in', reference: p[4] || '' };
    });
    if (!transactions.length) return;
    setBusy(true);
    try {
      const { data } = await axios.post(`${base}/import-bulk`, { transactions }, { headers });
      toast({ title: 'Impor', description: data.message }); setBulkText(''); onDone();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const addOne = async () => {
    setBusy(true);
    try {
      await axios.post(`${base}/transactions`, { ...form, amount: parseFloat(form.amount) || 0 }, { headers });
      toast({ title: 'Mutasi ditambahkan' }); setForm({ txn_date: '', description: '', reference: '', amount: '', direction: 'in' }); onDone();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  return (
    <section className="space-y-3 border-y border-[var(--glass-border)] py-3" data-testid="recon-import-panel" aria-label="Impor mutasi">
      <FilterChips value={tab} onChange={setTab} options={MODES} testId="recon-import-tab" ariaLabel="Cara impor" hideWhenEmpty={false} />
      {tab === 'file' && (
        <label className="flex flex-col items-center justify-center gap-1 border-2 border-dashed border-[var(--glass-border)] rounded-[var(--radius-md)] px-4 py-5 cursor-pointer hover:border-[hsl(var(--primary)/0.45)]">
          <Upload className="w-6 h-6 text-muted-foreground" />
          <span className="text-xs text-muted-foreground text-center">Kolom: Tanggal · Keterangan · Debit/Kredit (atau Nominal ±) · Referensi. Debit/Keluar = uang keluar.</span>
          <input type="file" accept=".csv,text/csv" className="hidden" data-testid="recon-csv-input" onChange={e => uploadCsv(e.target.files?.[0])} />
          {busy && <Loader2 className="w-4 h-4 animate-spin mt-1" />}
        </label>
      )}
      {tab === 'paste' && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">Per baris: tanggal, keterangan, nominal, masuk/keluar, referensi</p>
          <Textarea data-testid="recon-bulk-text" rows={4} aria-label="Mutasi per baris" className="tabular-nums"
            value={bulkText} onChange={e => setBulkText(e.target.value)}
            placeholder={'2026-09-01, Pencairan Shopee, 5000000, masuk, TRF001\n2026-09-03, Biaya admin, 6500, keluar'} />
          <Button size="sm" data-testid="recon-bulk-submit" onClick={importBulk} disabled={busy}>Impor</Button>
        </div>
      )}
      {tab === 'manual' && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
          <DatePicker testId="recon-txn-date" placeholder="Tanggal" value={form.txn_date} onChange={(v) => setForm(f => ({ ...f, txn_date: v }))} />
          <GlassInput data-testid="recon-txn-desc" className="h-9" placeholder="Keterangan" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          <MoneyInput glass decimals={2} data-testid="recon-txn-amount" className="h-9" placeholder="Nominal" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} />
          <SmartNativeSelect data-testid="recon-txn-direction" searchable={false} className="h-9" aria-label="Arah mutasi" value={form.direction} onChange={e => setForm(f => ({ ...f, direction: e.target.value }))}>
            <option value="in">Masuk (kredit rekening)</option>
            <option value="out">Keluar (debit rekening)</option>
          </SmartNativeSelect>
          <Button size="sm" data-testid="recon-txn-submit" onClick={addOne} disabled={busy || !form.txn_date || !form.amount}>Tambah</Button>
        </div>
      )}
    </section>
  );
}
