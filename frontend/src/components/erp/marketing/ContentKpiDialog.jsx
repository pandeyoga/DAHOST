/**
 * ContentKpiDialog — INPUT KPI SATU KONTEN (manual, sesi #35).
 *
 * Kenapa baru ada sekarang: endpoint `POST /content-calendar/{id}/kpi` sudah lama
 * ada, tetapi TIDAK ADA satu layar pun yang memanggilnya — jadi seluruh angka
 * views/engagement/GMV konten hanya bisa lahir dari penyemai demo. Pemilik memilih
 * pengisian MANUAL oleh staf marketing (impor menyusul bila berkasnya dikirim).
 *
 * Dua aturan yang kelihatan di form ini:
 *   · Angka turunan (engagement, eng. rate, CVR, GMV/view, AOV) TIDAK bisa diketik —
 *     ditampilkan sebagai hitungan hidup, yang tersimpan adalah hitungan SERVER.
 *   · Tanpa LINK TERBIT, KPI tidak boleh disimpan (backend menolak 400): angka yang
 *     tidak bisa dicek ulang ke platform tidak layak masuk laporan.
 *
 * Standar UI/UX v2 (8 Nov 2026): FormPopup panjang (isian di `Isian`, galat di kaki form), label Indonesia.
 */
import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Calculator } from 'lucide-react';
import { Input } from '@/components/ui/input';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { formatDateID } from '@/lib/format';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

const FIELDS = [
  ['views', 'Tayangan'],
  ['likes', 'Suka'],
  ['comments', 'Komentar'],
  ['shares', 'Dibagikan'],
  ['saves', 'Disimpan'],
  ['watch_time_avg_sec', 'Rata-rata ditonton (detik)'],
  ['ctr', 'Rasio klik / CTR (%)'],
  ['orders', 'Pesanan dari konten'],
  ['gmv', 'GMV (Rp)'],
];

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const fmtNum = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const rp = (n) => `Rp ${Number(n || 0).toLocaleString('id-ID')}`;
const pct = (n, d) => `${Number(n || 0).toFixed(d).replace('.', ',')}%`;

export default function ContentKpiDialog({ open, onClose, onSaved, token, content }) {
  const authH = useMemo(
    () => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` }), [token]);
  const [form, setForm] = useState({});
  const [url, setUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [galat, setGalat] = useState('');

  useEffect(() => {
    if (!open || !content) return;
    const k = content.kpi || {};
    setForm(Object.fromEntries(FIELDS.map(([f]) => [f, k[f] ?? ''])));
    setUrl(content.published_url || '');
    setGalat('');
  }, [open, content]);

  const set = (f, v) => setForm((p) => ({ ...p, [f]: v }));

  const derived = useMemo(() => {
    const views = num(form.views);
    const eng = num(form.likes) + num(form.comments) + num(form.shares);
    const orders = num(form.orders);
    const gmv = num(form.gmv);
    return {
      engagement: eng,
      engagement_rate: views > 0 ? (eng / views) * 100 : 0,
      cvr: views > 0 ? (orders / views) * 100 : 0,
      gmv_per_view: views > 0 ? gmv / views : 0,
      aov: orders > 0 ? gmv / orders : 0,
    };
  }, [form]);

  const save = async () => {
    if (!url.trim()) {
      setGalat('Tautan terbit wajib diisi — KPI tanpa tautan tidak bisa dicek ulang ke platform.');
      return;
    }
    setGalat('');
    setSaving(true);
    try {
      // Field yang dikosongkan dikirim `null` — server akan MEMPERTAHANKAN nilai
      // lamanya. Mengirim 0 untuk kolom yang tidak diisi akan menghapus angka yang
      // sudah benar (mis. GMV) tanpa pemakai sadar.
      const payload = Object.fromEntries(FIELDS.map(([f]) => {
        const raw = form[f];
        return [f, raw === '' || raw === null || raw === undefined ? null : num(raw)];
      }));
      await axios.post(`${API}/api/marketing/content-calendar/${content.id}/kpi`,
        { ...payload, published_url: url.trim(), source: 'manual' }, { headers: authH });
      toast.success('KPI konten tersimpan.');
      onSaved?.();
      onClose?.();
    } catch (e) {
      setGalat(e?.response?.data?.detail || 'Gagal menyimpan KPI konten.');
    } finally { setSaving(false); }
  };

  if (!content) return null;
  const ket = [content.date ? formatDateID(content.date) : '', content.content_type_label, content.account_name, content.creator_name]
    .filter(Boolean).join(' · ');
  return (
    <FormPopup open={open} onClose={onClose} ukuran="panjang" judul={`Isi KPI: ${content.title}`} keterangan={ket}
      onSimpan={save} menyimpan={saving} galat={galat} labelSimpan="Simpan KPI" testId="content-kpi-dialog">
      <Isian label="Tautan terbit" wajib htmlFor="kpi-url" petunjuk="Tautan unggahan di platform, untuk cek ulang angka.">
        <Input id="kpi-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" data-testid="kpi-published-url" />
      </Isian>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {FIELDS.map(([f, label]) => (
          <Isian key={f} label={label} htmlFor={`kpi-${f}`}>
            <Input id={`kpi-${f}`} type="number" min="0" step="any" value={form[f] ?? ''}
              onChange={(e) => set(f, e.target.value)} data-testid={`kpi-input-${f}`} />
          </Isian>
        ))}
      </div>
      <div className="border-t border-[var(--glass-border)] pt-3" data-testid="kpi-derived">
        <p className="mb-2 flex items-center gap-1 text-sm font-medium text-foreground">
          <Calculator className="h-4 w-4" /> Dihitung sistem (tidak bisa diketik)
        </p>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          <div><dt className="text-xs text-muted-foreground">Interaksi</dt><dd className="tabular-nums">{fmtNum(derived.engagement)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Tingkat interaksi</dt><dd className="tabular-nums">{pct(derived.engagement_rate, 2)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Konversi</dt><dd className="tabular-nums">{pct(derived.cvr, 4)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">GMV per tayangan</dt><dd className="tabular-nums">{rp(derived.gmv_per_view.toFixed(0))}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Rata-rata per pesanan</dt><dd className="tabular-nums">{rp(derived.aov.toFixed(0))}</dd></div>
        </dl>
      </div>
    </FormPopup>
  );
}
