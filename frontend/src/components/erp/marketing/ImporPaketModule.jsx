/**
 * Impor banyak berkas (Portal Marketing) — "perbarui semua dalam satu langkah".
 *
 * Alur: pilih beberapa ekspor Seller Center (atau satu ZIP) → sistem mengenali jenis laporan & toko tiap
 * berkas (dengan bukti) → staf melengkapi yang kurang (toko, periode GMV Max) → Periksa (pratinjau gabungan:
 * baris, pemetaan, rumus uang, dampak omzet per hari) → Simpan semua (berurutan: pesanan → status → retur →
 * iklan → KPI) → hasil + "Tanya AI tentang impor ini". Laporan penghasilan & saldo diarahkan ke Keuangan.
 * Kolom yang belum terpetakan bisa dibantu AI (hanya usulan; kolom uang wajib lolos uji rumus).
 *
 * Backend: `routes/marketing_impor_paket.py`. Standar UI v2: PageLayout, tabel, detail & form = popup.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, FileUp, MessageSquare, Pencil, RefreshCw, Sparkles, Undo2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeID, formatNumber, formatRupiah } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, Notice, StatTile, StatusBadge } from '../moduleAtoms';
import { STATUS_PAKET, hitungStatus, kalimatHasil, labelPeriode, statusBerkas, tahapBerikut } from './imporPaketAturan';

const API = process.env.REACT_APP_BACKEND_URL;
const DASAR = '/api/marketing/impor-paket';

async function panggil(path, { method = 'GET', body, form } = {}) {
  const token = localStorage.getItem('erp_token');
  const headers = { Authorization: `Bearer ${token}` };
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}${DASAR}${path}`, { method, headers, body: form || (body ? JSON.stringify(body) : undefined) });
  if (!res.ok) {
    let pesan = 'Permintaan gagal. Coba lagi.';
    try { const d = await res.json(); if (typeof d.detail === 'string') pesan = d.detail; } catch { /* abaikan */ }
    throw new Error(pesan);
  }
  return res.json();
}

async function unduhGalat(sesiId) {
  const token = localStorage.getItem('erp_token');
  const res = await fetch(`${API}/api/marketing/data-import/sessions/${sesiId}/errors.csv`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) { toast.error('Daftar baris bermasalah tidak bisa diunduh.'); return; }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url; a.download = `baris-bermasalah-${sesiId.slice(0, 8)}.csv`; a.click();
  URL.revokeObjectURL(url);
}

// ─── Form ubah satu berkas (popup pendek) ──────────────────────────────────────
function FormBerkas({ berkas, pilihan, onClose, onSimpan }) {
  const [f, setF] = useState(() => ({
    source_type: berkas.source_type || '', account_id: berkas.account_id || '',
    periode_mulai: berkas.periode_mulai || '', periode_selesai: berkas.periode_selesai || '', ikut: berkas.ikut !== false,
  }));
  const [galat, setGalat] = useState('');
  const [menyimpan, setMenyimpan] = useState(false);
  const butuhPeriode = f.source_type === 'tiktok_gmv_max';
  const calon = new Set((berkas.toko_calon || []).map((c) => c.id));
  const simpan = async () => {
    setMenyimpan(true); setGalat('');
    try { await onSimpan(f); } catch (e) { setGalat(e.message); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open onClose={onClose} judul="Lengkapi berkas" keterangan={berkas.nama} onSimpan={simpan}
      menyimpan={menyimpan} galat={galat} testId="form-berkas-paket">
      <Isian label="Jenis data" htmlFor="pk-jenis" petunjuk={berkas.sidik?.dikenal ? `Dikenali: ${berkas.sidik.label}` : 'Belum dikenali otomatis.'}>
        <SmartNativeSelect id="pk-jenis" value={f.source_type} onChange={(e) => setF({ ...f, source_type: e.target.value })}
          data-testid="pk-jenis">
          <option value="">— pilih jenis —</option>
          {(pilihan.jenis || []).map((j) => <option key={j.key} value={j.key}>{j.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      <Isian label="Toko tujuan" htmlFor="pk-toko" wajib
        petunjuk={(berkas.toko_calon || [])[0]?.alasan?.[0] ? `Bukti: ${berkas.toko_calon[0].alasan[0]}` : 'Tidak ada bukti toko di berkas — pilih sendiri.'}>
        <SmartNativeSelect id="pk-toko" value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })}
          data-testid="pk-toko">
          <option value="">— pilih toko —</option>
          {(pilihan.toko || []).map((t) => (
            <option key={t.id} value={t.id}>{t.nama}{calon.has(t.id) ? ' (cocok dengan berkas)' : ''}</option>
          ))}
        </SmartNativeSelect>
      </Isian>
      {butuhPeriode && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Isian label="Periode mulai" wajib petunjuk="Tanggal awal saat mengekspor GMV Max.">
            <DatePicker value={f.periode_mulai} onChange={(v) => setF({ ...f, periode_mulai: v })} testId="pk-periode-mulai" />
          </Isian>
          <Isian label="Periode selesai" wajib petunjuk="Harus dalam bulan yang sama.">
            <DatePicker value={f.periode_selesai} min={f.periode_mulai || undefined}
              onChange={(v) => setF({ ...f, periode_selesai: v })} testId="pk-periode-selesai" />
          </Isian>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm" htmlFor="pk-ikut">
        <Checkbox id="pk-ikut" checked={f.ikut} onCheckedChange={(v) => setF({ ...f, ikut: !!v })} data-testid="pk-ikut" />
        Ikut diimpor
      </label>
    </FormPopup>
  );
}

// ─── Popup AI pemeta (kolom sisa) ──────────────────────────────────────────────
function PopupAIPemeta({ berkas, onClose, onSelesai }) {
  const [data, setData] = useState(null);
  const [galat, setGalat] = useState('');
  const [pilih, setPilih] = useState({});
  const [menyimpan, setMenyimpan] = useState(false);
  useEffect(() => {
    panggil(`/sesi/${berkas.sesi_id}/ai-pemeta`, { method: 'POST' })
      .then((d) => { setData(d); setPilih(Object.fromEntries((d.usulan || []).filter((u) => u.diterima).map((u) => [u.kolom, u.field]))); })
      .catch((e) => setGalat(e.message));
  }, [berkas.sesi_id]);
  const terapkan = async () => {
    setMenyimpan(true); setGalat('');
    try {
      await panggil(`/sesi/${berkas.sesi_id}/terapkan-pemetaan`, { method: 'POST', body: { pilihan: pilih, simpan_untuk_toko: true } });
      toast.success('Pemetaan diterapkan dan diingat untuk toko ini.');
      onSelesai();
    } catch (e) { setGalat(e.message); } finally { setMenyimpan(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="panjang" judul="Bantu petakan kolom dengan AI"
      keterangan="Hanya nama kolom dan bentuk isinya yang dikirim ke AI — bukan data pembeli. Kolom uang wajib lolos uji rumus."
      onSimpan={terapkan} labelSimpan="Terapkan yang dipilih" menyimpan={menyimpan} galat={galat}
      bisaSimpan={Object.keys(pilih).length > 0} testId="popup-ai-pemeta">
      {!data && !galat && <p className="text-sm text-muted-foreground">AI sedang membaca kolom yang belum terpetakan…</p>}
      {data && (
        <>
          <p className="text-sm text-muted-foreground">{data.pesan}</p>
          <Table>
            <TableHeader><TableRow><TableHead className="w-10" /><TableHead>Kolom berkas</TableHead>
              <TableHead>Usulan</TableHead><TableHead>Keterangan</TableHead></TableRow></TableHeader>
            <TableBody>
              {(data.usulan || []).length === 0 && (
                <TableRow><TableCell colSpan={4} className="p-0"><EmptyState title="Tidak ada kolom yang perlu dipetakan" /></TableCell></TableRow>
              )}
              {(data.usulan || []).map((u) => (
                <TableRow key={u.kolom} data-testid="ai-usulan-baris">
                  <TableCell>
                    <Checkbox checked={!!pilih[u.kolom]} disabled={!u.diterima} aria-label={`Pakai usulan untuk ${u.kolom}`}
                      onCheckedChange={(v) => setPilih((p) => { const n = { ...p }; if (v) n[u.kolom] = u.field; else delete n[u.kolom]; return n; })} />
                  </TableCell>
                  <TableCell className="font-medium">{u.kolom}</TableCell>
                  <TableCell>{u.field_label || '—'}{u.field && <span className="text-muted-foreground"> · yakin {Math.round((u.keyakinan || 0) * 100)}%</span>}</TableCell>
                  <TableCell className={u.diterima ? 'text-muted-foreground' : 'text-[hsl(var(--warning-text))]'}>{u.catatan || u.alasan}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </FormPopup>
  );
}

// ─── Detail satu berkas (popup) ────────────────────────────────────────────────
function DetailBerkas({ berkas, onClose, onUbah, onAI }) {
  const st = statusBerkas(berkas.status);
  const p = berkas.periksa || {};
  const dampak = p.dampak_omzet;
  return (
    <DetailPopup open onClose={onClose} judul={berkas.nama} keterangan={berkas.label_jenis}
      status={<StatusBadge status={berkas.status} label={st.label} tone={st.tone} />}
      aksi={<>
        {berkas.sesi_id && (p.baris?.error || p.baris?.warning) ? <Button variant="outline" onClick={() => unduhGalat(berkas.sesi_id)}>Unduh baris bermasalah</Button> : null}
        {berkas.status === 'perlu_pemetaan' && <Button variant="outline" onClick={onAI}><Sparkles />Bantu petakan dengan AI</Button>}
        {!['disimpan', 'dibatalkan'].includes(berkas.status) && <Button variant="outline" onClick={onUbah}><Pencil />Lengkapi</Button>}
      </>} testId="detail-berkas-paket">
      <dl>
        <BarisDetail label="Jenis laporan">{berkas.sidik?.dikenal ? `${berkas.sidik.label} (${berkas.sidik.versi})` : 'Belum dikenali'}</BarisDetail>
        {berkas.sidik?.bukti?.kolom_wajib && <BarisDetail label="Bukti jenis">Kolom {berkas.sidik.bukti.kolom_wajib.join(', ')}</BarisDetail>}
        <BarisDetail label="Toko">{berkas.account_name || 'Belum dipilih'}
          {(berkas.toko_calon || [])[0]?.alasan?.length ? <span className="block text-muted-foreground">{berkas.toko_calon[0].alasan.join('; ')}</span> : null}
        </BarisDetail>
        <BarisDetail label="Periode">{labelPeriode(berkas.periode_mulai, berkas.periode_selesai)}</BarisDetail>
        <BarisDetail label="Baris">{formatNumber(berkas.baris)}{berkas.baris_perkiraan ? ' (perkiraan)' : ''}</BarisDetail>
        {p.baris && <BarisDetail label="Hasil pemeriksaan">{p.baris.valid ?? 0} sah · {p.baris.warning ?? 0} berperingatan · {p.baris.error ?? 0} ditolak</BarisDetail>}
        {p.rencana && Object.keys(p.rencana).length > 0 && (
          <BarisDetail label="Rencana simpan">{Object.entries(p.rencana).map(([k, v]) => `${v} ${k}`).join(' · ')}</BarisDetail>
        )}
        {p.pemetaan && <BarisDetail label="Pemetaan kolom">{p.pemetaan.terpetakan}/{p.pemetaan.total_kolom} kolom terpetakan
          {p.pemetaan.kolom_wajib_kurang?.length ? ` · wajib belum ada: ${p.pemetaan.kolom_wajib_kurang.join(', ')}` : ''}
          {p.pemetaan.dari_pemetaan_toko?.length ? ` · ${p.pemetaan.dari_pemetaan_toko.length} kolom dari pemetaan toko` : ''}</BarisDetail>}
        {p.invarian && <BarisDetail label="Uji rumus uang">{p.invarian.kalimat}</BarisDetail>}
        {berkas.hasil && <BarisDetail label="Hasil simpan">{kalimatHasil(berkas.hasil)}</BarisDetail>}
      </dl>
      {(berkas.kekurangan || []).length > 0 && (
        <Notice tone="warning" icon={AlertTriangle} title="Perlu dilengkapi">{berkas.kekurangan.join(' ')}</Notice>
      )}
      {berkas.galat && <Notice tone="danger" icon={AlertTriangle} title="Tidak bisa disimpan">{berkas.galat}</Notice>}
      {[...(berkas.peringatan || []), ...(p.peringatan || []), ...(p.penghalang || [])].map((w, i) => (
        <Notice key={i} tone="warning" icon={AlertTriangle}>{w}</Notice>
      ))}
      {berkas.jalur === 'pencairan' && <Notice tone="info">Laporan penghasilan disimpan lewat Keuangan › Pencairan (staf Keuangan memeriksa draf lalu menyimpan & menjurnal).</Notice>}
      {berkas.jalur === 'penarikan' && <Notice tone="info">Laporan saldo/penarikan disimpan lewat Keuangan › Penarikan.</Notice>}
      {dampak && (
        <div className="space-y-2">
          <p className="text-sm font-medium">Omzet berkas per hari dibanding rekap yang sudah tersimpan</p>
          <Table data-testid="tabel-dampak-omzet">
            <TableHeader><TableRow><TableHead>Tanggal</TableHead><TableHead className="text-right">Pesanan</TableHead>
              <TableHead className="text-right">Omzet berkas</TableHead><TableHead className="text-right">Rekap tersimpan</TableHead></TableRow></TableHeader>
            <TableBody>
              {dampak.hari.map((h) => (
                <TableRow key={h.tanggal}>
                  <TableCell>{h.tanggal}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(h.pesanan_berkas)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatRupiah(h.omzet_berkas)}</TableCell>
                  <TableCell className="text-right tabular-nums">{h.rekap_tersimpan == null ? '—' : formatRupiah(h.rekap_tersimpan)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">Omzet = sesudah diskon penjual; pesanan batal & belum dibayar tidak dihitung.</p>
        </div>
      )}
    </DetailPopup>
  );
}

// ─── Layar ─────────────────────────────────────────────────────────────────────
export default function ImporPaketModule() {
  const [pilihan, setPilihan] = useState({ toko: [], jenis: [] });
  const [riwayat, setRiwayat] = useState([]);
  const [paket, setPaket] = useState(null);
  const [sibuk, setSibuk] = useState('');
  const [detail, setDetail] = useState(null);
  const [ubah, setUbah] = useState(null);
  const [ai, setAi] = useState(null);
  const inputRef = useRef(null);

  const muatRiwayat = useCallback(() => panggil('').then((d) => setRiwayat(d.paket || [])).catch(() => {}), []);
  useEffect(() => {
    panggil('/pilihan').then(setPilihan).catch((e) => toast.error(e.message));
    muatRiwayat();
  }, [muatRiwayat]);

  const muatPaket = useCallback(async (id) => {
    const d = await panggil(`/${id}`);
    setPaket(d.paket);
    return d.paket;
  }, []);

  // pantau progres simpan di latar
  useEffect(() => {
    if (!paket || paket.status !== 'menyimpan') return undefined;
    const t = setInterval(() => { muatPaket(paket.id).catch(() => {}); }, 2000);
    return () => clearInterval(t);
  }, [paket, muatPaket]);

  const jalan = async (label, fn) => {
    setSibuk(label);
    try { return await fn(); } catch (e) { toast.error(e.message); return null; } finally { setSibuk(''); }
  };

  const unggah = (files) => jalan('unggah', async () => {
    const form = new FormData();
    Array.from(files || []).forEach((f) => form.append('files', f));
    const d = await panggil('', { method: 'POST', form });
    setPaket(d.paket);
    muatRiwayat();
    toast.success(`${d.paket.berkas.length} berkas dibaca. Periksa jenis & toko tiap berkas.`);
  });

  const periksa = () => jalan('periksa', async () => {
    const d = await panggil(`/${paket.id}/periksa`, { method: 'POST' });
    setPaket(d.paket);
  });

  const simpan = async () => {
    const siap = (paket.berkas || []).filter((b) => b.status === 'diperiksa').length;
    const ok = await confirmDialog({ title: `Simpan ${siap} berkas?`, body: 'Data disimpan berurutan: pesanan, status, retur, iklan, lalu KPI. Pesanan yang sudah ada diperbarui. Bisa dibatalkan dari layar ini.', confirmLabel: 'Simpan semua' });
    if (!ok) return;
    await jalan('simpan', async () => {
      const d = await panggil(`/${paket.id}/simpan`, { method: 'POST', body: { on_duplicate: 'update' } });
      setPaket(d.paket);
      toast.success(d.pesan);
    });
  };

  const batalkan = async () => {
    const ok = await confirmDialog({ title: 'Batalkan paket impor ini?', body: 'Semua baris yang dimasukkan atau diubah paket ini dipulihkan (batas 72 jam per berkas).', confirmLabel: 'Batalkan paket', danger: true });
    if (!ok) return;
    await jalan('batal', async () => {
      const d = await panggil(`/${paket.id}/batalkan`, { method: 'POST' });
      setPaket(d.paket);
      const gagal = (d.hasil || []).filter((h) => !h.ok);
      if (gagal.length) toast.error(`${gagal.length} berkas tidak bisa dibatalkan: ${gagal[0].pesan}`);
      else toast.success('Paket dibatalkan.');
    });
  };

  const tanyaAI = () => jalan('ai', async () => {
    const d = await panggil(`/${paket.id}/tanya-ai`, { method: 'POST' });
    toast.success(d.pesan);
    window.dispatchEvent(new CustomEvent('erp:navigate-module', { detail: { moduleId: 'asisten-ai', params: { sesi: d.sesi_id } } }));
  });

  const simpanBerkas = async (b, f) => {
    const d = await panggil(`/${paket.id}/berkas/${b.idx}`, { method: 'PUT', body: f });
    setPaket(d.paket);
    setUbah(null);
    setDetail(null);
  };

  const tahap = tahapBerikut(paket);
  const n = hitungStatus(paket?.berkas);
  const ringkas = paket?.ringkas || {};
  const kolom = useMemo(() => [
    { kunci: 'nama', label: 'Berkas', hp: 'judul', isi: (b) => <span className="font-medium">{b.nama}</span> },
    { kunci: 'jenis', label: 'Jenis data', hp: 'keterangan', isi: (b) => b.label_jenis || '—' },
    { kunci: 'toko', label: 'Toko', isi: (b) => b.account_name || <span className="text-muted-foreground">Belum dipilih</span> },
    { kunci: 'periode', label: 'Periode', isi: (b) => labelPeriode(b.periode_mulai, b.periode_selesai) },
    { kunci: 'baris', label: 'Baris', rata: 'kanan', isi: (b) => formatNumber(b.baris) },
    { kunci: 'status', label: 'Status', isi: (b) => { const s = statusBerkas(b.status); return <StatusBadge status={b.status} label={s.label} tone={s.tone} />; } },
    { kunci: 'hasil', label: 'Hasil', isi: (b) => (b.hasil ? kalimatHasil(b.hasil) : (b.galat || (b.kekurangan || [])[0] || '')) },
    { kunci: 'aksi', label: '', rata: 'kanan', isi: (b) => (
      !['disimpan', 'dibatalkan'].includes(b.status) && paket?.status !== 'menyimpan'
        ? <Button variant="outline" size="sm" onClick={() => setUbah(b)} data-testid="pk-lengkapi">Lengkapi</Button> : null) },
  ], [paket]);

  const tombolUtama = (() => {
    if (tahap === 'unggah' || tahap === 'selesai') {
      return <Button onClick={() => inputRef.current?.click()} disabled={!!sibuk} data-testid="pk-pilih-berkas"><FileUp />Pilih berkas</Button>;
    }
    if (tahap === 'simpan') return <Button variant="success" onClick={simpan} disabled={!!sibuk} data-testid="pk-simpan"><CheckCircle2 />Simpan semua</Button>;
    if (tahap === 'menunggu') return <Button disabled>Menyimpan…</Button>;
    return <Button onClick={periksa} disabled={!!sibuk} data-testid="pk-periksa">{sibuk === 'periksa' ? 'Memeriksa…' : 'Periksa semua'}</Button>;
  })();

  return (
    <PageLayout testId="impor-paket-module" title="Impor banyak berkas"
      subtitle="Unggah beberapa ekspor Seller Center sekaligus; jenis dan tokonya dikenali dari isi berkas."
      actions={tombolUtama}
      filters={riwayat.length > 0 && (
        <SmartNativeSelect value={paket?.id || ''} onChange={(e) => (e.target.value ? muatPaket(e.target.value) : setPaket(null))}
          className="w-64" data-testid="pk-riwayat" aria-label="Paket impor">
          <option value="">Paket baru</option>
          {riwayat.map((r) => (
            <option key={r.id} value={r.id}>{formatDateTimeID(r.created_at)} · {(r.berkas || []).length} berkas · {STATUS_PAKET[r.status] || r.status}</option>
          ))}
        </SmartNativeSelect>
      )}
      tools={<>
        {paket && <Button variant="outline" size="icon" title="Muat ulang" aria-label="Muat ulang" onClick={() => muatPaket(paket.id)}><RefreshCw /></Button>}
        {paket && ['selesai', 'sebagian'].includes(paket.status) && <Button variant="outline" onClick={tanyaAI} disabled={!!sibuk} data-testid="pk-tanya-ai"><MessageSquare />Tanya AI tentang impor ini</Button>}
        {paket && ['selesai', 'sebagian', 'gagal'].includes(paket.status) && <Button variant="outline" onClick={batalkan} disabled={!!sibuk} data-testid="pk-batalkan"><Undo2 />Batalkan paket</Button>}
      </>}
      summary={paket && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Berkas" value={formatNumber((paket.berkas || []).length)} hint="Berkas di paket ini (isi ZIP dihitung per berkas)." />
          {['selesai', 'sebagian', 'gagal', 'dibatalkan', 'menyimpan'].includes(paket.status) ? (<>
            <StatTile label="Baris baru" value={formatNumber(ringkas.baris_masuk || 0)} hint="Baris yang dibuat oleh paket ini." />
            <StatTile label="Diperbarui" value={formatNumber(ringkas.baris_diperbarui || 0)} hint="Baris lama yang ditimpa angka terbaru." />
            <StatTile label="Ditolak" value={formatNumber(ringkas.baris_ditolak || 0)} accent={ringkas.baris_ditolak ? 'danger' : 'default'} hint="Baris yang tidak disimpan — buka berkasnya untuk alasannya." />
          </>) : (<>
            <StatTile label="Siap disimpan" value={formatNumber(n.diperiksa || 0)} accent={n.diperiksa ? 'success' : 'default'} hint="Sudah diperiksa, tanpa penghalang." />
            <StatTile label="Perlu dilengkapi" value={formatNumber((n.perlu_isian || 0) + (n.perlu_pemetaan || 0) + (n.ditolak || 0))} accent={(n.perlu_isian || n.perlu_pemetaan || n.ditolak) ? 'warning' : 'default'} hint="Toko/periode belum diisi, pemetaan belum lengkap, atau ditolak penjaga." />
            <StatTile label="Diproses di Keuangan" value={formatNumber(n.keuangan || 0)} hint="Laporan penghasilan/saldo: disimpan lewat menu Keuangan." />
          </>)}
        </div>
      )}>
      <input ref={inputRef} type="file" multiple accept=".csv,.xlsx,.xls,.xlsm,.zip" className="hidden"
        data-testid="pk-input-berkas" onChange={(e) => { unggah(e.target.files); e.target.value = ''; }} />
      {paket?.status === 'menyimpan' && paket.progres && (
        <Notice tone="info" title={`Menyimpan ${paket.progres.selesai}/${paket.progres.total} berkas`}>
          {paket.progres.sedang ? `Sedang: ${paket.progres.sedang}.` : 'Menyelesaikan…'} Layar ini memperbarui progresnya sendiri.
        </Notice>
      )}
      {paket && ['selesai', 'sebagian'].includes(paket.status) && (
        <Notice tone={paket.status === 'selesai' ? 'success' : 'warning'} icon={CheckCircle2}
          title={paket.status === 'selesai' ? 'Semua berkas tersimpan' : 'Sebagian berkas gagal disimpan'}>
          Rekap harian dihitung ulang otomatis. Tekan “Tanya AI tentang impor ini” untuk ringkasan temuan berangka.
        </Notice>
      )}
      <TabelData kolom={kolom} baris={paket?.berkas || []} kunci={(b) => b.idx} onKlikBaris={setDetail} testId="tabel-paket"
        kosong={<EmptyState title="Belum ada berkas"
          description="Pilih beberapa ekspor Seller Center (pesanan, iklan, retur, KPI) atau satu berkas ZIP. Tidak ada yang disimpan sebelum Anda menekan Simpan semua."
          action={<Button onClick={() => inputRef.current?.click()}><FileUp />Pilih berkas</Button>} />} />
      {detail && <DetailBerkas berkas={detail} onClose={() => setDetail(null)}
        onUbah={() => { setUbah(detail); setDetail(null); }} onAI={() => { setAi(detail); setDetail(null); }} />}
      {ubah && <FormBerkas berkas={ubah} pilihan={pilihan} onClose={() => setUbah(null)} onSimpan={(f) => simpanBerkas(ubah, f)} />}
      {ai && <PopupAIPemeta berkas={ai} onClose={() => setAi(null)} onSelesai={() => { setAi(null); periksa(); }} />}
    </PageLayout>
  );
}
