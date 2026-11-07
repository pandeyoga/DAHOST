import { useState, useEffect, useCallback, useMemo } from 'react';
import { Wand2, RefreshCw, CheckCircle2, Link2, Info } from 'lucide-react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { toast } from '../ui/sonner';
import PageLayout from './layout/PageLayout';
import { Notice, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

/** Nilai khusus dropdown: buat ukuran baru di master (bukan memilih yang ada). */
const NEW_SIZE = '__new__';

async function readErr(res, fallback) {
  try { const d = await res.json(); return d?.detail || fallback; } catch { return fallback; }
}

const sumberTeks = (it) => [it.from_size_list && 'Daftar ukuran style', it.from_variants && 'Varian'].filter(Boolean).join(', ');
const styleTeks = (it, maks = 99) => {
  const kode = (it.styles || []).map(s => s.style_code || s.style_id.slice(0, 6));
  return kode.length > maks ? `${kode.slice(0, maks).join(', ')} +${kode.length - maks} lagi` : kode.join(', ');
};

/**
 * Padankan Ukuran — memetakan ukuran R&D yang masih "belum dipadankan" ke master
 * produksi (`rahaza_sizes`).
 *
 * Kenapa layar ini ada: ukuran R&D sengaja BEBAS (kebijakan B1), tapi PO produksi
 * internal MEWAJIBKAN `size_id` yang sah. Selain memblokir PO, ukuran yang belum
 * dipadankan juga membuat promosi style ke produksi menambah ukuran master BARU —
 * sehingga master bisa punya `ALLSIZE` dan `ALL SIZE` sekaligus dan SKU FG pecah.
 * Satu klik di sini menutup keduanya.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout, kartu angka StatTile (dengan keterangan), tabel ui/table tanpa judul
 * kolom huruf besar, daftar "sudah terhubung" dari pil lipat menjadi tabel yang selalu tampil, unduh Excel/CSV.
 */
export default function RnDSizeMappingModule({ token }) {
  const hdr = useMemo(
    () => ({ 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }),
    [token],
  );

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [createMissing, setCreateMissing] = useState(true);
  const [choice, setChoice] = useState({});      // label → size_id | NEW_SIZE
  const [newCode, setNewCode] = useState({});    // label → kode master usulan
  const [picked, setPicked] = useState({});      // label → boolean (batch)

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/size-mapping`, { headers: hdr });
      if (!res.ok) { toast.error(await readErr(res, 'Gagal memuat pemadanan ukuran')); return; }
      const d = await res.json();
      setData(d);
      // Pilihan awal = saran sistem bila ada, kalau tidak → buat baru di master.
      const c = {}, n = {};
      (d.items || []).forEach(it => {
        c[it.label] = it.suggestion ? it.suggestion.size_id : NEW_SIZE;
        n[it.label] = it.proposed_new_code || '';
      });
      setChoice(c); setNewCode(n); setPicked({});
    } catch { toast.error('Gagal memuat pemadanan ukuran'); }
    finally { setLoading(false); }
  }, [hdr]);

  useEffect(() => { load(); }, [load]);

  const applyMappings = async (mappings, label) => {
    if (!mappings.length) { toast.error('Belum ada ukuran yang dipilih.'); return; }
    setBusy(label);
    try {
      const res = await fetch(`${API}/api/dewi/rnd/size-mapping/apply`, {
        method: 'POST', headers: hdr, body: JSON.stringify({ mappings }),
      });
      if (!res.ok) { toast.error(await readErr(res, 'Gagal memadankan ukuran')); return; }
      const out = await res.json();
      toast.success(
        `${out.applied} ukuran dipadankan · ${out.styles_updated} style & ` +
        `${out.variants_affected} varian ikut diperbarui` +
        (out.unmatched_after === 0 ? ' — tidak ada lagi yang tertahan' : ''),
      );
      await load();
    } catch { toast.error('Gagal memadankan ukuran'); }
    finally { setBusy(''); }
  };

  const rowMapping = (it) => {
    const sel = choice[it.label];
    if (sel === NEW_SIZE || !sel) {
      return { label: it.label, create_new: true, code: (newCode[it.label] || '').trim() };
    }
    return { label: it.label, size_id: sel };
  };

  const applyRow = (it) => applyMappings([rowMapping(it)], it.label);

  const applySelected = () => {
    const rows = (data?.items || []).filter(it => picked[it.label]);
    applyMappings(rows.map(rowMapping), '__selected__');
  };

  const autoAll = async () => {
    setBusy('__auto__');
    try {
      const res = await fetch(`${API}/api/dewi/rnd/size-mapping/auto`, {
        method: 'POST', headers: hdr, body: JSON.stringify({ create_missing: createMissing }),
      });
      if (!res.ok) { toast.error(await readErr(res, 'Gagal memadankan otomatis')); return; }
      const out = await res.json();
      if (out.applied === 0 && (out.skipped || []).length) {
        toast.warning(
          `${out.skipped.length} ukuran tidak punya padanan di master: ${out.skipped.join(', ')}. ` +
          `Aktifkan "boleh membuat ukuran baru di master" atau pilih padanannya satu per satu.`,
        );
      } else {
        toast.success(
          `${out.applied} ukuran dipadankan (${out.unmatched_before} → ${out.unmatched_after} tertahan) · ` +
          `${out.styles_updated} style, ${out.variants_affected} varian`,
        );
      }
      await load();
    } catch { toast.error('Gagal memadankan otomatis'); }
    finally { setBusy(''); }
  };

  const items = data?.items || [];
  const matched = data?.matched || [];
  const pickedCount = items.filter(it => picked[it.label]).length;
  const allClear = !loading && data && items.length === 0;
  const masterNama = (id) => {
    const m = (data?.master_sizes || []).find(x => x.size_id === id);
    return m ? `${m.code}${m.name && m.name !== m.code ? ` — ${m.name}` : ''}` : '';
  };
  const angka = (k) => (data ? (data[k] ?? '—') : '—');

  return (
    <PageLayout testId="rnd-size-mapping-module" title="Padankan ukuran"
      subtitle="Hubungkan ukuran RnD yang ditulis bebas ke master ukuran produksi supaya style tidak tertahan saat masuk PO."
      actions={(
        <Button onClick={autoAll} disabled={loading || !!busy || items.length === 0} data-testid="rnd-size-mapping-auto-btn"
          title={items.length === 0 ? 'Tidak ada ukuran yang perlu dipadankan' : 'Padankan semua ukuran sekaligus'}>
          <Wand2 />{busy === '__auto__' ? 'Memadankan…' : 'Padankan semua'}
        </Button>
      )}
      tools={(
        <Button variant="outline" size="icon" onClick={load} disabled={loading || !!busy} title="Muat ulang" aria-label="Muat ulang"
          data-testid="rnd-size-mapping-refresh">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      )}
      summary={(
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile testId="rnd-size-stat-unmatched_labels" label="Belum dipadankan" value={angka('unmatched_labels')}
            accent={items.length > 0 ? 'warning' : 'default'}
            sub="Label ukuran RnD yang belum terhubung ke master" />
          <StatTile testId="rnd-size-stat-blocked_styles" label="Style tertahan" value={angka('blocked_styles')}
            accent={data?.blocked_styles > 0 ? 'danger' : 'default'}
            sub="Style yang tertahan saat masuk PO karena ukurannya" />
          <StatTile testId="rnd-size-stat-matched_labels" label="Sudah dipadankan" value={angka('matched_labels')}
            sub="Label ukuran yang sudah terhubung ke master" />
          <StatTile testId="rnd-size-stat-variants_scanned" label="Varian diperiksa" value={angka('variants_scanned')}
            sub="Semua varian RnD yang dibaca ukurannya" />
        </div>
      )}>
      {loading && !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pemadanan ukuran…</p>
      ) : allClear ? (
        <Notice tone="success" icon={CheckCircle2} testId="rnd-size-mapping-allclear"
          title="Semua ukuran sudah dipadankan ke master produksi">
          Tidak ada style yang tertahan karena ukuran.
        </Notice>
      ) : (
        <div className="space-y-3">
          <Notice tone="info" icon={Info}>
            Ukuran RnD boleh ditulis bebas (mis. All Size, 28/30), tetapi PO produksi hanya menerima ukuran yang ada di
            master. Selama belum dipadankan, style yang memakainya tertahan saat masuk PO, dan saat dipromosikan sistem
            menambah ukuran master baru sehingga master bisa punya dua ukuran yang sebenarnya sama.
          </Notice>

          {/* ── Aksi massal ── */}
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm text-foreground" htmlFor="rnd-size-create-missing">
              <Checkbox id="rnd-size-create-missing" checked={createMissing}
                onCheckedChange={(v) => setCreateMissing(v === true)}
                data-testid="rnd-size-mapping-create-missing" />
              Boleh membuat ukuran baru di master bila tidak ada padanannya
            </label>
            <TombolUnduh namaBerkas="ukuran-belum-dipadankan" namaLembar="Belum dipadankan" baris={items}
              testId="rnd-size-unmatched-unduh"
              kolom={[
                { label: 'Ukuran RnD', nilai: (it) => it.label },
                { label: 'Dipakai oleh (style)', nilai: (it) => styleTeks(it) },
                { label: 'Terbaca dari', nilai: (it) => sumberTeks(it) },
                { label: 'Padankan ke', nilai: (it) => {
                  const sel = choice[it.label];
                  return (!sel || sel === NEW_SIZE) ? `Ukuran baru: ${(newCode[it.label] || it.proposed_new_code || '').trim()}` : masterNama(sel);
                } },
              ]} />
            <Button variant="outline" onClick={applySelected} disabled={pickedCount === 0 || !!busy}
              data-testid="rnd-size-mapping-apply-selected">
              <Link2 />{busy === '__selected__' ? 'Memadankan…' : `Padankan terpilih (${pickedCount})`}
            </Button>
          </div>

          {/* ── Tabel label belum dipadankan ── */}
          <div className="rounded-lg border border-[var(--glass-border)]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox aria-label="Pilih semua"
                      checked={pickedCount > 0 && pickedCount === items.length}
                      onCheckedChange={(v) => {
                        const all = {};
                        if (v === true) items.forEach(it => { all[it.label] = true; });
                        setPicked(all);
                      }}
                      data-testid="rnd-size-mapping-pick-all" />
                  </TableHead>
                  <TableHead>Ukuran RnD</TableHead>
                  <TableHead>Dipakai oleh</TableHead>
                  <TableHead>Terbaca dari</TableHead>
                  <TableHead>Padankan ke</TableHead>
                  <TableHead className="text-right">Aksi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map(it => {
                  const sel = choice[it.label];
                  const isNew = sel === NEW_SIZE || !sel;
                  return (
                    <TableRow key={it.label} className="align-top" data-testid={`rnd-size-row-${it.label}`}>
                      <TableCell>
                        <Checkbox aria-label={`Pilih ${it.label}`} checked={!!picked[it.label]}
                          onCheckedChange={(v) => setPicked(p => ({ ...p, [it.label]: v === true }))}
                          data-testid={`rnd-size-pick-${it.label}`} />
                      </TableCell>
                      <TableCell><span className="text-sm font-semibold">{it.label}</span></TableCell>
                      <TableCell>
                        {it.styles.length === 0 ? (
                          <span className="text-muted-foreground">—</span>
                        ) : (
                          <span className="block max-w-[15rem] whitespace-normal text-sm" title={it.styles.map(s => s.style_name).join(', ')}>
                            {styleTeks(it, 3)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {it.from_size_list && <StatusBadge status="size_list" label="Daftar ukuran" tone="info" />}
                          {it.from_variants && <StatusBadge status="variants" label="Varian" tone="primary" />}
                        </div>
                      </TableCell>
                      <TableCell className="min-w-[16rem]">
                        <SmartNativeSelect
                          value={sel || NEW_SIZE}
                          onChange={e => setChoice(c => ({ ...c, [it.label]: e.target.value }))}
                          className="w-full" aria-label={`Padankan ${it.label} ke`}
                          data-testid={`rnd-size-target-${it.label}`}>
                          <option value={NEW_SIZE}>+ Buat ukuran baru di master…</option>
                          {(data?.master_sizes || []).map(m => (
                            <option key={m.size_id} value={m.size_id}>
                              {m.code}{m.name && m.name !== m.code ? ` — ${m.name}` : ''}
                            </option>
                          ))}
                        </SmartNativeSelect>

                        {isNew ? (
                          <div className="mt-2 flex items-center gap-2">
                            <span className="whitespace-nowrap text-xs text-muted-foreground">Kode master</span>
                            <Input value={newCode[it.label] ?? ''}
                              onChange={e => setNewCode(n => ({ ...n, [it.label]: e.target.value }))}
                              className="h-8 text-sm" aria-label="Kode master baru"
                              placeholder={it.proposed_new_code || 'Kode'}
                              data-testid={`rnd-size-newcode-${it.label}`} />
                          </div>
                        ) : it.suggestion && it.suggestion.size_id === sel ? (
                          <p className="mt-1.5 flex items-center gap-1 text-xs text-[hsl(var(--success-text))]">
                            <CheckCircle2 className="h-3 w-3" /> Saran sistem: {it.suggestion.reason}
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="outline" disabled={!!busy} onClick={() => applyRow(it)}
                          data-testid={`rnd-size-apply-${it.label}`}>
                          <Link2 />{busy === it.label ? 'Memadankan…' : 'Padankan'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* ── Yang sudah dipadankan (transparansi) — dulu pil lipat, kini tabel ── */}
      {!loading && matched.length > 0 && (
        <section className="space-y-2" data-testid="rnd-size-mapping-matched-panel">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-base font-semibold text-foreground">Sudah terhubung ke master ({matched.length})</p>
            <TombolUnduh namaBerkas="ukuran-sudah-dipadankan" namaLembar="Sudah dipadankan" baris={matched}
              testId="rnd-size-matched-unduh"
              kolom={[
                { label: 'Ukuran RnD', nilai: (m) => m.label },
                { label: 'Kode master', nilai: (m) => m.code || '' },
                { label: 'Nama master', nilai: (m) => m.name || '' },
                { label: 'Jumlah style', nilai: (m) => Number(m.used_by_count ?? (m.styles || []).length) || 0 },
                { label: 'Style', nilai: (m) => styleTeks(m) },
              ]} />
          </div>
          <TabelData baris={matched} kunci={(m) => m.label} testId="rnd-size-mapping-matched"
            kolom={[
              { kunci: 'label', label: 'Ukuran RnD', hp: 'judul', isi: (m) => <span className="font-semibold">{m.label}</span> },
              { kunci: 'master', label: 'Ukuran master', isi: (m) => (
                <span><span className="tabular-nums">{m.code}</span>{m.name && m.name !== m.code ? ` — ${m.name}` : ''}</span>) },
              { kunci: 'jumlah', label: 'Dipakai style', rata: 'kanan', isi: (m) => (
                <span className="tabular-nums">{m.used_by_count ?? (m.styles || []).length}</span>) },
              { kunci: 'style', label: 'Contoh style', hp: 'keterangan', isi: (m) => (
                <span className="block max-w-[24rem] truncate text-sm text-muted-foreground" title={styleTeks(m)}>{styleTeks(m, 5)}</span>) },
            ]} />
        </section>
      )}
    </PageLayout>
  );
}
