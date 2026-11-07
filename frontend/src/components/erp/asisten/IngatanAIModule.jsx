/**
 * Ingatan AI — Portal Management (Asisten AI Tahap D, D1, 8 Nov 2026; menu `asisten-ai-ingatan`).
 *
 * Hal yang diingat Asisten AI tentang cara pengguna bekerja (keputusan owner 13): preferensi ("target minimal tumbuh
 * 8%"), fakta usaha, dan gaya jawaban. Setiap pengguna hanya melihat ingatannya sendiri; tidak ada tampilan admin
 * untuk ingatan orang lain. Ingatan bisa ditambah manual, diubah (popup form pendek), dinonaktifkan sementara (saklar
 * "Dipakai": disimpan tetapi tidak dipakai AI), dan dihapus permanen (dialog konfirmasi). Asal ingatan dari
 * percakapan bisa dibuka ("Buka percakapan").
 *
 *   GET    /api/asisten-ai/ingatan          PATCH  /api/asisten-ai/ingatan/{id} {isi?, kategori?, aktif?}
 *   POST   /api/asisten-ai/ingatan          DELETE /api/asisten-ai/ingatan/{id}
 * Bentuk jawaban dibaca di `adapterTahapCD.js` (A1, A2, A8). PATCH hanya membawa yang berubah (backend menolak PATCH
 * tanpa perubahan); POST dengan isi yang sama mengembalikan ingatan lama (`sudah_ada`).
 *
 * Standar UI/UX v2: PageLayout (pil kategori + cari di `filters`, unduh + muat ulang di `tools`, 1 tombol utama di
 * `actions`, kalimat ringkas di `summary`), tabel ui/table, form = popup pendek bergaya FormPopup (kepala · isi · kaki
 * Batal/Simpan hijau; testid lama dipertahankan untuk uji), hapus lewat confirmDialog.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Brain, Loader2, MessageSquare, Pencil, Plus, Power, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Isian } from '@/components/ui/form-popup';
import FilterChips from '@/components/ui/filter-chips';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { cn } from '@/lib/utils';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { KUNCI_SESI_AKTIF, asistenApi } from './asistenApi';
import {
  BATAS_INGATAN_AKTIF, BATAS_ISI_INGATAN, KATEGORI_INGATAN, bacaDaftarIngatan, bacaIngatan, hitungKategori,
  ingatanAktifDariStatus, jumlahAktif, periksaIngatan, ubahanIngatan,
} from './adapterTahapCD';

const waktu = (v) => formatDateTimeID(parseServerTime(v));
const KOSONG = { items: [], batas: BATAS_INGATAN_AKTIF, maksIsi: BATAS_ISI_INGATAN, ingatanAktif: null };

/** Dialog pendek tambah/ubah ingatan (isi ≤ maks huruf + kategori). */
function DialogIngatan({ buka, awal, maksIsi, onTutup, onSimpan }) {
  const ubah = !!awal?.id;
  const [isi, setIsi] = useState('');
  const [kategori, setKategori] = useState('preferensi');
  const [galat, setGalat] = useState('');
  const [simpan, setSimpan] = useState(false);

  useEffect(() => {
    if (!buka) return;
    setIsi(awal?.isi || '');
    setKategori(KATEGORI_INGATAN.some((k) => k.kunci === awal?.kategori) ? awal.kategori : 'preferensi');
    setGalat('');
    setSimpan(false);
  }, [buka, awal]);

  const contoh = KATEGORI_INGATAN.find((k) => k.kunci === kategori)?.contoh;
  const panjang = isi.replace(/\s+/g, ' ').trim().length;

  const kirim = async () => {
    if (simpan) return;
    const r = periksaIngatan({ isi, kategori }, maksIsi);
    if (!r.ok) { setGalat(r.galat); return; }
    setSimpan(true);
    setGalat('');
    try {
      await onSimpan(r.nilai);
    } catch (e) {
      setGalat(e?.message || 'Ingatan gagal disimpan. Coba lagi.');
      setSimpan(false);
    }
  };

  // Tata letak = FormPopup ukuran "pendek" (kepala · isi bergulir · kaki galat/Batal/Simpan hijau; HP penuh layar).
  // Ditulis di sini karena uji lama memakai testid `ingatan-dialog` / `ingatan-simpan` / `ingatan-batal`.
  const kirimForm = (e) => { e.preventDefault(); kirim(); };
  return (
    <Dialog open={buka} onOpenChange={(v) => { if (!v && !simpan) onTutup(); }}>
      <DialogContent data-testid="ingatan-dialog"
        className={cn('flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-lg',
          'max-sm:left-0 max-sm:top-0 max-sm:h-[100dvh] max-sm:max-h-none max-sm:max-w-none',
          'max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none')}>
        <form onSubmit={kirimForm} className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-[var(--glass-border)] px-5 py-4 pr-12">
            <DialogTitle className="text-base font-semibold">{ubah ? 'Ubah ingatan' : 'Tambah ingatan'}</DialogTitle>
            <DialogDescription className="mt-1 text-sm text-muted-foreground">
              Satu hal yang perlu selalu diingat Asisten AI. Jangan tulis kata sandi, gaji, atau data pribadi orang lain.
            </DialogDescription>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
            <Isian label="Isi ingatan" wajib htmlFor="ingatan-isi">
              <Textarea id="ingatan-isi" rows={3} value={isi} maxLength={maksIsi + 20}
                onChange={(e) => setIsi(e.target.value)} placeholder="Mis. target omzet minimal tumbuh 8% per bulan"
                aria-invalid={panjang > maksIsi ? true : undefined} data-testid="ingatan-isi" />
              <p className={cn('text-right text-xs tabular-nums', panjang > maksIsi ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground')}
                data-testid="ingatan-panjang">
                {panjang}/{maksIsi}
              </p>
            </Isian>
            <Isian label="Kategori" htmlFor="ingatan-kategori" petunjuk={contoh}>
              <SmartNativeSelect id="ingatan-kategori" value={kategori} onChange={(e) => setKategori(e.target.value)}
                searchable={false} className="h-9 w-full" aria-label="Kategori ingatan" data-testid="ingatan-kategori">
                {KATEGORI_INGATAN.map((k) => <option key={k.kunci} value={k.kunci}>{k.label}</option>)}
              </SmartNativeSelect>
            </Isian>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-[var(--glass-border)] px-5 py-3">
            <div className="min-w-0 flex-1 text-sm text-[hsl(var(--danger-text))]" role="alert">
              {galat ? <span data-testid="ingatan-dialog-galat">{galat}</span> : null}
            </div>
            <Button type="button" variant="outline" onClick={onTutup} disabled={simpan} data-testid="ingatan-batal">Batal</Button>
            <Button type="submit" variant="success" disabled={simpan} data-testid="ingatan-simpan">
              {simpan && <Loader2 className="animate-spin" />} {simpan ? 'Menyimpan…' : 'Simpan'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Sumber({ sumber, onBuka, testId = 'ingatan-buka-sesi' }) {
  if (sumber?.jenis === 'percakapan') {
    return (
      <Button variant="link" size="sm" className="h-auto px-0" onClick={() => onBuka(sumber.sesi_id)}
        title="Buka percakapan tempat ingatan ini disimpan" data-testid={testId}>
        <MessageSquare className="h-4 w-4" /> Buka percakapan
      </Button>
    );
  }
  return <span className="text-sm text-muted-foreground">Ditambah manual</span>;
}

export default function IngatanAIModule({ onNavigate, deepLinkParams }) {
  const [data, setData] = useState(KOSONG);
  const [memuat, setMemuat] = useState(true);
  const [galat, setGalat] = useState('');
  const [kategori, setKategori] = useState('');
  const [cari, setCari] = useState('');
  const [dialog, setDialog] = useState(null); // null | {} (tambah) | ingatan (ubah)
  const [sibuk, setSibuk] = useState(null); // id baris yang sedang dihapus / diubah saklarnya
  const [aktifStatus, setAktifStatus] = useState(true);
  const urut = useRef(0);
  const sorot = /^[\w-]{1,80}$/.test(String(deepLinkParams?.ingatan || '')) ? String(deepLinkParams.ingatan) : null;
  const sudahGulir = useRef(false);

  const muat = useCallback(async (diam = false) => {
    const n = (urut.current += 1);
    if (!diam) setMemuat(true);
    setGalat('');
    try {
      const d = await asistenApi.daftarIngatan();
      if (n === urut.current) setData(bacaDaftarIngatan(d));
    } catch (e) {
      if (n === urut.current) setGalat(e?.message || 'Ingatan gagal dimuat.');
    } finally {
      if (n === urut.current) setMemuat(false);
    }
  }, []);

  useEffect(() => {
    muat();
    asistenApi.status().then((st) => setAktifStatus(ingatanAktifDariStatus(st))).catch(() => { /* tetap tampil */ });
  }, [muat]);

  // dari chip "Diingat: …" di chat → sorot baris itu sekali
  useEffect(() => {
    if (!sorot || sudahGulir.current || !data.items.some((x) => x.id === sorot)) return;
    sudahGulir.current = true;
    requestAnimationFrame(() => {
      document.querySelector(`[data-testid="ingatan-baris-${sorot}"]`)?.scrollIntoView?.({ block: 'center' });
    });
  }, [sorot, data.items]);

  const ganti = (baru) => setData((d) => ({ ...d, items: d.items.map((x) => (x.id === baru.id ? baru : x)) }));
  const jumlah = useMemo(() => hitungKategori(data.items), [data.items]);
  const aktif = jumlahAktif(data.items);
  const tampil = useMemo(() => {
    const q = cari.trim().toLowerCase();
    return data.items.filter((x) => (!kategori || x.kategori === kategori) && (!q || x.isi.toLowerCase().includes(q)));
  }, [data.items, kategori, cari]);
  const penuh = aktif >= data.batas;
  const ingatanMenyala = data.ingatanAktif === null ? aktifStatus : data.ingatanAktif;

  const simpan = async (nilai) => {
    const lama = dialog?.id ? dialog : null;
    if (lama) {
      const ubahan = ubahanIngatan(lama, nilai);
      if (!ubahan) { setDialog(null); return; } // tidak ada yang berubah → tanpa permintaan
      const baru = bacaIngatan(await asistenApi.ubahIngatan(lama.id, ubahan));
      if (baru) ganti(baru);
      setDialog(null);
      toast.success('Ingatan diubah.');
    } else {
      const baru = bacaIngatan(await asistenApi.tambahIngatan(nilai));
      if (baru) setData((d) => ({ ...d, items: [baru, ...d.items.filter((x) => x.id !== baru.id)] }));
      setDialog(null);
      if (baru?.sudahAda) toast.info('Ingatan yang sama sudah ada, jadi tidak disimpan dua kali.');
      else toast.success('Ingatan ditambahkan. Asisten AI memakainya mulai pertanyaan berikutnya.');
    }
    muat(true);
  };

  const gantiAktif = async (row, nyala) => {
    if (sibuk) return;
    setSibuk(row.id);
    try {
      const baru = bacaIngatan(await asistenApi.ubahIngatan(row.id, { aktif: nyala }));
      ganti(baru || { ...row, aktif: nyala });
      toast.success(nyala ? 'Ingatan dipakai lagi oleh Asisten AI.' : 'Ingatan disimpan, tetapi tidak dipakai Asisten AI.');
    } catch (e) {
      toast.error(e?.message || 'Ingatan gagal diubah.');
      if (e?.status === 404) muat(true);
    } finally {
      setSibuk(null);
    }
  };

  const hapus = async (row) => {
    if (sibuk) return;
    const ok = await confirmDialog({
      title: 'Hapus ingatan ini?',
      body: `"${row.isi}" dihapus permanen dan tidak dipakai lagi oleh Asisten AI. Untuk berhenti memakainya sementara, matikan saklar "Dipakai".`,
      confirmLabel: 'Hapus',
      danger: true,
    });
    if (!ok) return;
    setSibuk(row.id);
    try {
      await asistenApi.hapusIngatan(row.id);
      setData((d) => ({ ...d, items: d.items.filter((x) => x.id !== row.id) }));
      toast.success('Ingatan dihapus.');
    } catch (e) {
      toast.error(e?.message || 'Ingatan gagal dihapus.');
      if (e?.status === 404) muat(true);
    } finally {
      setSibuk(null);
    }
  };

  const bukaSesi = (sesiId) => {
    try { window.sessionStorage.setItem(KUNCI_SESI_AKTIF, sesiId); } catch { /* diblokir */ }
    onNavigate?.('asisten-ai', { sesi: sesiId });
  };

  const opsiKategori = [
    { key: '', label: 'Semua', count: data.items.length },
    ...KATEGORI_INGATAN.map((k) => ({ key: k.kunci, label: k.label, count: jumlah[k.kunci] })),
  ];
  const disaring = !!kategori || !!cari.trim();
  const nonaktif = data.items.length - aktif;

  return (
    <PageLayout
      testId="ingatan-ai-page"
      title="Ingatan AI"
      subtitle="Hal yang diingat Asisten AI tentang cara kerja Anda. Ubah atau hapus kapan saja."
      actions={(
        <Button onClick={() => setDialog({})} disabled={penuh}
          title={penuh ? `Batas ${data.batas} ingatan aktif tercapai` : undefined} data-testid="ingatan-tambah">
          <Plus className="h-4 w-4" /> Tambah ingatan
        </Button>
      )}
      filters={data.items.length > 0 ? (
        <>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari ingatan" aria-label="Cari ingatan"
              className="h-9 pl-8" data-testid="ingatan-cari" />
          </div>
          <FilterChips options={opsiKategori} value={kategori} onChange={setKategori} ariaLabel="Penyaring kategori"
            testId="ingatan-kategori-pil" />
        </>
      ) : null}
      tools={(
        <>
          <TombolUnduh namaBerkas="ingatan-ai" namaLembar="Ingatan AI" baris={tampil} testId="ingatan-unduh"
            kolom={[
              { label: 'Isi', nilai: (r) => r.isi },
              { label: 'Kategori', nilai: (r) => r.kategoriLabel },
              { label: 'Sumber', nilai: (r) => (r.sumber?.jenis === 'percakapan' ? 'Dari percakapan' : 'Ditambah manual') },
              { label: 'Dipakai Asisten AI', nilai: (r) => (r.aktif ? 'Ya' : 'Tidak') },
              { label: 'Diperbarui', nilai: (r) => waktu(r.diperbarui) },
            ]} />
          <Button variant="outline" size="icon" onClick={() => muat()} title="Muat ulang" aria-label="Muat ulang" data-testid="ingatan-muat-ulang">
            <RefreshCw className={memuat ? 'animate-spin' : ''} />
          </Button>
        </>
      )}
      summary={(
        <>
          {galat && <Notice tone="danger" icon={AlertCircle} testId="ingatan-galat">{galat}</Notice>}
          {!ingatanMenyala && (
            <Notice tone="warning" icon={Power} testId="ingatan-mati">
              Ingatan AI sedang dimatikan admin: Asisten AI tidak memakai dan tidak menambah ingatan. Daftar di bawah tetap bisa diubah atau dihapus.
            </Notice>
          )}
          {penuh && (
            <Notice tone="warning" icon={AlertCircle} testId="ingatan-penuh">
              Batas {data.batas} ingatan aktif tercapai. Hapus atau matikan ingatan yang sudah tidak berlaku sebelum menambah yang baru.
            </Notice>
          )}
          {data.items.length > 0 && !penuh && (
            <p className="text-sm text-muted-foreground" data-testid="ingatan-ringkas">
              {aktif} dari {data.batas} ingatan aktif terpakai{nonaktif ? `; ${nonaktif} sedang tidak dipakai` : ''}.
              {' '}Asisten AI memakai ingatan aktif di setiap percakapan Anda.
            </p>
          )}
        </>
      )}
    >
      <GlassCard className="overflow-hidden p-0" data-testid="ingatan-kartu">
        {memuat && !data.items.length ? (
          <div className="space-y-2 p-4" data-testid="ingatan-memuat">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-9 w-full" />)}
          </div>
        ) : tampil.length === 0 ? (
          <EmptyState icon={disaring ? Search : Brain} testId="ingatan-kosong"
            title={disaring ? 'Tidak ada ingatan pada penyaring ini' : 'Belum ada ingatan'}
            description={disaring
              ? 'Ganti kategori atau kata pencarian di atas.'
              : 'Saat Anda berkata "ingat ya, target minimal tumbuh 8%", Asisten AI menyimpannya di sini dan memakainya di percakapan berikutnya. Anda juga bisa menambah, mengubah, atau menghapusnya sendiri.'}
            action={!disaring && onNavigate ? { label: 'Buka Asisten AI', variant: 'outline', onClick: () => onNavigate('asisten-ai'), testId: 'ingatan-ke-asisten' } : undefined} />
        ) : (
          <Table className="min-w-0 md:min-w-[760px]" data-testid="ingatan-tabel">
            <TableHeader>
              <TableRow>
                <TableHead>Isi</TableHead>
                <TableHead className="hidden md:table-cell">Kategori</TableHead>
                <TableHead className="hidden md:table-cell">Sumber</TableHead>
                <TableHead className="hidden sm:table-cell">Diperbarui</TableHead>
                <TableHead className="w-36 text-right">Aksi</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tampil.map((row) => (
                <TableRow key={row.id} data-testid={`ingatan-baris-${row.id}`} data-sorot={row.id === sorot ? '1' : undefined}
                  data-aktif={row.aktif ? '1' : '0'} className={cn(row.id === sorot && 'bg-[hsl(var(--primary)/0.06)]')}>
                  <TableCell className="whitespace-normal">
                    <p className={cn('break-words text-sm', row.aktif ? 'text-foreground' : 'text-muted-foreground')}
                      data-testid="ingatan-isi-baris">{row.isi}</p>
                    {!row.aktif && (
                      <StatusBadge status="nonaktif" label="Tidak dipakai" tone="muted" className="mt-1" testId={`ingatan-nonaktif-${row.id}`} />
                    )}
                    <p className="mt-0.5 text-xs text-muted-foreground md:hidden">
                      {row.kategoriLabel} · {row.sumber.jenis === 'percakapan' ? 'dari percakapan' : 'ditambah manual'}
                      <span className="sm:hidden"> · {waktu(row.diperbarui)}</span>
                    </p>
                    {row.sumber.jenis === 'percakapan' && (
                      <div className="md:hidden"><Sumber sumber={row.sumber} onBuka={bukaSesi} testId="ingatan-buka-sesi-hp" /></div>
                    )}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap text-sm text-foreground/80 md:table-cell" data-testid="ingatan-kategori-baris">
                    {row.kategoriLabel}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap md:table-cell"><Sumber sumber={row.sumber} onBuka={bukaSesi} /></TableCell>
                  <TableCell className="hidden whitespace-nowrap text-xs text-muted-foreground sm:table-cell">{waktu(row.diperbarui)}</TableCell>
                  <TableCell className="text-right">
                    <div className="inline-flex items-center gap-1">
                      <Switch checked={row.aktif} onCheckedChange={(v) => gantiAktif(row, v)} disabled={!!sibuk}
                        className="mr-1" aria-label={row.aktif ? 'Dipakai Asisten AI (matikan)' : 'Tidak dipakai (nyalakan)'}
                        title={row.aktif ? 'Dipakai Asisten AI' : 'Tidak dipakai Asisten AI'} data-testid={`ingatan-aktif-${row.id}`} />
                      <Button variant="ghost" size="icon-sm" onClick={() => setDialog(row)} disabled={!!sibuk}
                        title="Ubah ingatan" aria-label="Ubah ingatan" data-testid={`ingatan-ubah-${row.id}`}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => hapus(row)} disabled={!!sibuk}
                        title="Hapus ingatan" aria-label="Hapus ingatan" data-testid={`ingatan-hapus-${row.id}`}>
                        {sibuk === row.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </GlassCard>
      <DialogIngatan buka={!!dialog} awal={dialog} maksIsi={data.maksIsi} onTutup={() => setDialog(null)} onSimpan={simpan} />
    </PageLayout>
  );
}
