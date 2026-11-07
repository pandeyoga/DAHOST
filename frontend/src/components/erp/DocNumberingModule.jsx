/**
 * DocNumberingModule — Penomoran Dokumen & SKU.
 * Owner mengatur format nomor tiap jenis dokumen. Modul ini TIDAK membuat
 * nomor sendiri: format disimpan lalu dibaca generator resmi di backend
 * (`utils/counters.gen_prefixed_number`), jadi tidak ada dua sumber kebenaran.
 *
 * Standar UI/UX v2 (8 Nov 2026): 49 jenis dokumen = satu tabel (dulu 49 kartu berisi form) dengan penyaring
 * kelompok + unduh Excel/CSV; mengubah format/mode = FormPopup dengan pratinjau; setel nomor urut = FormPopup
 * pendek (tombolnya pindah ke popup Atur); kode internal jenis dokumen (`wh_fabric_rolls.roll_no`) tidak ditampilkan.
 * Jalur simpan tidak berubah.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ListOrdered, Pencil, RefreshCw, RotateCcw, Search } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';
const BASE = `${API}/api/admin/doc-numbering`;

const TOKEN_HELP = [
  ['{YYYY}', 'tahun 4 digit — 2026'],
  ['{YY}', 'tahun 2 digit — 26'],
  ['{MM}', 'bulan — 07'],
  ['{DD}', 'tanggal — 27'],
  ['{SEQ:4}', 'nomor urut 4 digit — 0001 (wajib di akhir)'],
];

const labelMode = (item) => (!item.policy_enforced
  ? { label: item.auto_only ? 'Selalu otomatis' : 'Otomatis saja', tone: 'muted' }
  : item.mode === 'manual' ? { label: 'Manual', tone: 'warning' } : { label: 'Otomatis', tone: 'primary' });

export default function DocNumberingModule({ token }) {
  const [items, setItems] = useState([]);
  const [groups, setGroups] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [previews, setPreviews] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [filter, setFilter] = useState('');
  const [kelompok, setKelompok] = useState('');
  const [editKey, setEditKey] = useState(null);
  const [counterFor, setCounterFor] = useState(null);
  const [counterVal, setCounterVal] = useState('');

  const h = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(BASE, { headers: h });
      if (!r.ok) throw new Error((await r.json()).detail || `Kode ${r.status}`);
      const d = await r.json();
      setItems(d.items || []);
      setGroups(d.groups || []);
      setDrafts({});
      setPreviews({});
    } catch (e) { toast.error(e.message); } finally { setLoading(false); }
  }, [h]);

  useEffect(() => { load(); }, [load]);

  const preview = async (key, format) => {
    try {
      const r = await fetch(`${BASE}/preview`, { method: 'POST', headers: h, body: JSON.stringify({ key, format }) });
      const d = await r.json();
      setPreviews(p => ({ ...p, [key]: d }));
    } catch (e) { /* pratinjau bersifat bantu, abaikan gangguan sesaat */ }
  };

  const onDraft = (key, format) => {
    setDrafts(d => ({ ...d, [key]: format }));
    preview(key, format);
  };

  const save = async (item) => {
    const format = drafts[item.key];
    setBusy(item.key);
    try {
      const r = await fetch(BASE, { method: 'PUT', headers: h, body: JSON.stringify({ key: item.key, format, active: true }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Kode ${r.status}`);
      toast.success(`Format ${item.label} disimpan — contoh: ${d.contoh}`);
      setEditKey(null);
      await load();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  // FASE G (2026-08-16) — pindah mode OTOMATIS ⇄ MANUAL.
  // Otomatis: nomor dibuat sistem, kolom nomor di form dokumen dikunci.
  // Manual: nomor diketik, TETAPI wajib mengikuti pola format di sebelah —
  // itulah yang menghentikan nomor bebas seperti `PO-MKL-GAB-A` masuk arsip.
  const setMode = async (item, mode) => {
    if (mode === item.mode) return;
    setBusy(item.key);
    try {
      const r = await fetch(BASE, {
        method: 'PUT', headers: h,
        body: JSON.stringify({ key: item.key, mode, active: true }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Kode ${r.status}`);
      toast.success(mode === 'auto'
        ? `${item.label}: nomor dibuat otomatis oleh sistem`
        : `${item.label}: nomor diketik, wajib mengikuti pola ${d.format}`);
      await load();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const reset = async (item) => {
    if (!(await confirmDialog({
      title: `Kembalikan format ${item.label} ke bawaan?`, body: `Format bawaan: ${item.default_format || '—'}. Hanya berlaku untuk dokumen baru.`,
      confirmLabel: 'Kembalikan',
    }))) return;
    setBusy(item.key);
    try {
      const r = await fetch(`${BASE}/${item.key}`, { method: 'DELETE', headers: h });
      if (!r.ok) throw new Error((await r.json()).detail || `Kode ${r.status}`);
      toast.success(`${item.label} kembali ke format bawaan`);
      setEditKey(null);
      await load();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const saveCounter = async () => {
    setBusy(counterFor.key);
    try {
      const r = await fetch(`${BASE}/counter`, {
        method: 'POST', headers: h,
        body: JSON.stringify({ key: counterFor.key, start_from: Number(counterVal) }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `Kode ${r.status}`);
      toast.success(`Nomor berikutnya: ${d.nomor_berikutnya}`);
      setCounterFor(null); setCounterVal('');
      await load();
    } catch (e) { toast.error(e.message); } finally { setBusy(''); }
  };

  const visible = items.filter(i => {
    const q = filter.trim().toLowerCase();
    return (!kelompok || i.group === kelompok)
      && (!q || i.label.toLowerCase().includes(q) || i.key.toLowerCase().includes(q) || i.group.toLowerCase().includes(q));
  });
  const customCount = items.filter(i => i.is_custom).length;
  const item = items.find((i) => i.key === editKey) || null;
  const draft = item ? drafts[item.key] : undefined;
  const changed = draft !== undefined && item && draft !== item.format;
  const pv = item ? previews[item.key] : null;
  const bukaSetelUrut = (it) => { setCounterFor(it); setCounterVal(String(it.nomor_terakhir || 0)); };

  const kolom = [
    { kunci: 'label', label: 'Jenis dokumen', hp: 'judul', isi: (i) => (
      <div className="min-w-0 md:max-w-[16rem]" data-testid={`docnum-row-${i.key}`}>
        <p className="font-medium text-foreground">{i.label}</p>
        <p className="text-xs text-muted-foreground">{i.group}</p>
      </div>) },
    { kunci: 'format', label: 'Format', hp: 'keterangan', isi: (i) => (
      <span className="break-all font-mono text-sm">{i.format}{i.is_custom && <StatusBadge status="khusus" label="Khusus" tone="primary" className="ml-1.5 font-sans" />}</span>) },
    { kunci: 'contoh', label: 'Contoh', isi: (i) => <span className="break-all font-mono text-sm" data-testid={`docnum-sample-${i.key}`}>{i.contoh || '—'}</span> },
    { kunci: 'mode', label: 'Mode', isi: (i) => <StatusBadge status={i.mode} label={labelMode(i).label} tone={labelMode(i).tone} /> },
    { kunci: 'terakhir', label: 'Nomor terakhir', rata: 'kanan', isi: (i) => <span className="tabular-nums">{i.nomor_terakhir ?? '—'}</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (i) => (
      <Button size="sm" variant="outline" onClick={() => setEditKey(i.key)} data-testid={`docnum-edit-${i.key}`}><Pencil />Atur</Button>) },
  ];

  return (
    <PageLayout testId="doc-numbering-module" headerTestId="docnum-header" title="Penomoran dokumen"
      subtitle="Format nomor tiap jenis dokumen dan SKU. Perubahan hanya berlaku untuk dokumen baru."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Cari jenis dokumen" value={filter} onChange={e => setFilter(e.target.value)} className="pl-8"
            data-testid="docnum-search" />
        </div>
        <SmartNativeSelect value={kelompok} onChange={(e) => setKelompok(e.target.value)} className="w-full"
          wrapperClassName="w-full sm:w-52" aria-label="Kelompok" data-testid="docnum-group-filter">
          <option value="">Semua kelompok</option>
          {groups.map((g) => <option key={g} value={g}>{g}</option>)}
        </SmartNativeSelect>
      </>}
      tools={<>
        <TombolUnduh namaBerkas="penomoran-dokumen" namaLembar="Penomoran" baris={visible} testId="docnum-unduh" kolom={[
          { label: 'Jenis dokumen', nilai: (i) => i.label }, { label: 'Kelompok', nilai: (i) => i.group },
          { label: 'Format', nilai: (i) => i.format }, { label: 'Format bawaan', nilai: (i) => i.default_format || '' },
          { label: 'Contoh', nilai: (i) => i.contoh || '' }, { label: 'Mode', nilai: (i) => labelMode(i).label },
          { label: 'Nomor terakhir', nilai: (i) => i.nomor_terakhir ?? '' },
        ]} />
        <Button variant="outline" size="icon" onClick={load} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="docnum-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={!loading && (
        <p className="text-sm text-muted-foreground" data-testid="docnum-summary">
          {items.length} jenis dokumen · {customCount} memakai format khusus
          {visible.length !== items.length && ` · ${visible.length} tampil`}.
        </p>
      )}>
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground" data-testid="docnum-loading">Memuat penomoran…</p>
      ) : (
        <TabelData kolom={kolom} baris={visible} kunci={(i) => i.key} onKlikBaris={(i) => setEditKey(i.key)} testId="docnum-table"
          kosong={<EmptyState title="Tidak ada jenis dokumen yang cocok" description="Ubah kata pencarian atau kelompok." />} />
      )}

      {/* Atur format & mode satu jenis dokumen */}
      <FormPopup open={!!item} onClose={() => { if (item) setDrafts((d) => { const n = { ...d }; delete n[item.key]; return n; }); setEditKey(null); }}
        ukuran="panjang" testId="docnum-form" judul={item ? `Format nomor ${item.label}` : ''}
        keterangan={item ? `${item.group} · perubahan hanya berlaku untuk dokumen baru.` : undefined}
        onSimpan={() => item && save(item)} menyimpan={!!item && busy === item.key}
        bisaSimpan={!!changed && !(pv && !pv.ok)} labelSimpan="Simpan format"
        aksiKiri={item && (<>
          {item.sequenced !== false && (
            <Button type="button" variant="outline" size="sm" onClick={() => bukaSetelUrut(item)} data-testid={`docnum-counter-${item.key}`}>
              <ListOrdered />Setel nomor urut
            </Button>
          )}
          {item.is_custom && (
            <Button type="button" variant="outline" size="sm" onClick={() => reset(item)} disabled={busy === item.key}
              data-testid={`docnum-reset-${item.key}`}>
              <RotateCcw />Kembalikan bawaan
            </Button>
          )}
        </>)}>
        {item && (<>
          <Isian label="Format" htmlFor="docnum-format" petunjuk={item.default_format ? `Bawaan: ${item.default_format}` : undefined}>
            <Input id="docnum-format" value={draft !== undefined ? draft : item.format}
              onChange={e => onDraft(item.key, e.target.value)} className="font-mono" data-testid={`docnum-input-${item.key}`} />
          </Isian>
          <p className="text-sm">
            {pv && !pv.ok
              ? <span className="text-[hsl(var(--danger-text))]" data-testid="docnum-error">{pv.error}</span>
              : <span className="text-muted-foreground">Contoh: <span className="font-mono text-foreground">{pv?.contoh || item.contoh || '—'}</span></span>}
          </p>
          {item.nomor_terakhir != null && (
            <p className="text-sm text-muted-foreground">Nomor urut terakhir terpakai: <b className="text-foreground">{item.nomor_terakhir}</b></p>
          )}
          <Notice tone="info" title="Token yang bisa dipakai">
            <ul className="mt-1 grid gap-1 sm:grid-cols-2">
              {TOKEN_HELP.map(([t, d]) => (
                <li key={t} className="text-xs"><code className="font-mono text-foreground">{t}</code> — {d}</li>
              ))}
              {(item.tokens || []).map((t) => (
                <li key={t} className="text-xs"><code className="font-mono text-foreground">{'{' + t + '}'}</code> — token khusus dokumen ini</li>
              ))}
            </ul>
          </Notice>
          {item.catatan && <p className="text-sm text-muted-foreground">{item.catatan}</p>}

          {/* FASE G — mode penomoran per jenis dokumen.
              SESI #18 — KEJUJURAN: mode hanya bisa dipindah untuk jenis dokumen
              yang JALUR TULISNYA sudah menegakkan kebijakan (`policy_enforced`).
              Jenis yang belum ditegakkan mengatakannya terang-terangan. */}
          <Isian label="Mode penomoran" petunjuk={item.policy_enforced ? 'Pilihan mode langsung tersimpan saat diklik.' : undefined}>
            {item.policy_enforced ? (
              <div className="space-y-1">
                <div className="inline-flex overflow-hidden rounded-lg border border-[var(--glass-border)]" role="group" aria-label="Mode penomoran">
                  {[['auto', 'Otomatis'], ['manual', 'Manual']].map(([m, lbl]) => (
                    <button key={m} type="button" onClick={() => setMode(item, m)} disabled={busy === item.key}
                      data-testid={`docnum-mode-${item.key}-${m}`} aria-pressed={item.mode === m}
                      className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                        item.mode === m
                          ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]'
                          : 'bg-[var(--card-surface)] text-muted-foreground hover:text-foreground'}`}>
                      {lbl}
                    </button>
                  ))}
                </div>
                <p className="text-sm text-muted-foreground" data-testid={`docnum-mode-hint-${item.key}`}>
                  {item.mode === 'manual'
                    ? 'Nomor diketik petugas — yang tidak sesuai pola ditolak.'
                    : 'Nomor dibuat sistem — kolom nomor di form dikunci.'}
                  {item.mode_is_custom && item.mode !== item.mode_default && (
                    <span className="text-primary"> (bawaan: {item.mode_default === 'auto' ? 'otomatis' : 'manual'})</span>
                  )}
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                <StatusBadge status="auto" label={item.auto_only ? 'Selalu otomatis' : 'Otomatis saja'} tone="muted"
                  testId={`docnum-mode-locked-${item.key}`} />
                <p className="text-sm text-muted-foreground" data-testid={`docnum-mode-hint-${item.key}`}>
                  {item.auto_only ? (
                    <>{item.alasan_otomatis || 'Dokumen ini dibuat sistem, bukan diketik.'}{' '}Formatnya tetap bisa diubah di sini.</>
                  ) : (
                    <>Jalur dokumen ini <b>belum menegakkan</b> mode manual, jadi pilihannya belum ditampilkan agar setelan
                      tidak berbohong. Formatnya tetap berlaku.</>
                  )}
                </p>
              </div>
            )}
          </Isian>
        </>)}
      </FormPopup>

      {/* Setel nomor urut */}
      <FormPopup open={!!counterFor} onClose={() => setCounterFor(null)} ukuran="pendek" testId="docnum-counter-dialog"
        judul={counterFor ? `Setel nomor urut ${counterFor.label}` : ''}
        keterangan="Nomor dokumen berikutnya = angka ini + 1. Menurunkan angka ditolak bila sudah ada dokumen memakai awalan yang sama (mencegah nomor ganda)."
        onSimpan={saveCounter} menyimpan={!!counterFor && busy === counterFor.key} bisaSimpan={counterVal !== ''}>
        <Isian label="Nomor urut terakhir" htmlFor="docnum-counter-input">
          <Input id="docnum-counter-input" type="number" min={0} value={counterVal} onChange={e => setCounterVal(e.target.value)}
            className="w-40 tabular-nums" data-testid="docnum-counter-input" />
        </Isian>
        {counterFor && Number(counterVal) - (counterFor.nomor_terakhir || 0) > 100 && (
          <Notice tone="warning" testId="docnum-counter-warning">
            Lompatan besar: dari {counterFor.nomor_terakhir || 0} ke {counterVal}. Nomor di antaranya tidak akan pernah
            terpakai. Pastikan ini memang disengaja.
          </Notice>
        )}
      </FormPopup>
    </PageLayout>
  );
}
