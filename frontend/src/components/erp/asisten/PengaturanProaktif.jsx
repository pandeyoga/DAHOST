/**
 * PengaturanProaktif — bagian "Asisten AI proaktif" di Monitor AI › Pengaturan (Asisten AI Tahap D, D1 + D2, 8 Nov 2026).
 *
 *   Ingatan AI aktif                                                     [saklar]
 *   Briefing pagi · Peringatan harian · Laporan mingguan                 [saklar]
 *     Jam (WIB) [07:00]   [Jalankan sekarang]   ← tombol hanya untuk owner/superadmin, lewat dialog konfirmasi
 *   Penerima briefing & laporan mingguan: [nama ×] [nama ×] [+ Tambah penerima]   (kosong = semua owner aktif)
 *
 * Nilai disimpan bersama pengaturan AI lain lewat PUT /api/ai/usage/settings yang SAMA (tombol "Simpan Pengaturan"
 * modul induk); bagian ini hanya mengisi `form` lewat `setField`. Jam = isian teks JJ:MM (tidak ada komponen jam di
 * aplikasi; tidak memakai input tanggal/bulan bawaan peramban). Penerima paling banyak 20.
 * Owner/superadmin juga melihat jadwal berikutnya per jenis dan riwayat jalan terakhir (GET /proaktif; peran lain 403
 * → bagian itu disembunyikan). Bentuk data: `adapterTahapCD.js` (A6, A7, A9, A10).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Brain, BellRing, CalendarClock, History, Loader2, MessageSquare, Play, RefreshCw, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { GlassCard } from '@/components/ui/glass';
import { Input } from '@/components/ui/input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Switch } from '@/components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { EmptyState, Notice, StatusBadge } from '../moduleAtoms';
import { asistenApi } from './asistenApi';
import {
  BATAS_PENERIMA, JADWAL_PROAKTIF, bacaDaftarPengguna, bacaHasilJalankan, bacaRingkasanProaktif, bolehJalankanProaktif,
  normalJam, proaktifBerubah, teksHasilJalankan, teksWaktuJadwal,
} from './adapterTahapCD';

const PENERIMA = 'asisten_briefing_penerima';
const BARIS = 'space-y-3 border-t border-[var(--glass-border)] pt-4';

function Judul({ judul, keterangan, children }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-sm font-medium text-foreground">{judul}</p>
        <p className="text-xs text-muted-foreground">{keterangan}</p>
      </div>
      {children}
    </div>
  );
}

/** Jadwal berikutnya menurut pengaturan yang SUDAH tersimpan di server (GET /proaktif). */
function JadwalBerikut({ info, testId }) {
  if (!info) return null;
  const t = info.aktif ? teksWaktuJadwal(info.berikutnya) : '';
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid={testId}>
      <CalendarClock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      {info.aktif ? (t ? `Berikutnya: ${t} WIB` : 'Belum ada jadwal berikutnya.') : 'Tidak terjadwal: sedang dimatikan.'}
    </p>
  );
}

function BarisJadwal({ jadwal, form, setField, galat, boleh, sibuk, onJalankan, info }) {
  const { jenis, judul, keterangan, kunciAktif, kunciJam } = jadwal;
  const [disentuh, setDisentuh] = useState(false);
  const nilai = form[kunciJam] ?? '';
  const salah = !normalJam(nilai) && (disentuh || !!galat[kunciJam]);
  const id = `ai-set-${jenis}-jam`;
  return (
    <div className={BARIS} data-testid={`ai-set-proaktif-${jenis}`}>
      <Judul judul={judul} keterangan={keterangan}>
        <Switch checked={!!form[kunciAktif]} onCheckedChange={(v) => setField(kunciAktif, v)} className="shrink-0"
          aria-label={`${judul} aktif`} data-testid={`ai-set-${jenis}-aktif`} />
      </Judul>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={id} className="mb-1 block text-xs text-muted-foreground">Jam (WIB)</label>
          <Input id={id} value={nilai} inputMode="numeric" maxLength={5} placeholder="07:00" autoComplete="off"
            className="h-9 w-28 tabular-nums" aria-invalid={salah ? true : undefined}
            aria-describedby={salah ? `${id}-galat` : undefined}
            onChange={(e) => setField(kunciJam, e.target.value)}
            onBlur={() => { setDisentuh(true); const n = normalJam(nilai); if (n && n !== nilai) setField(kunciJam, n); }}
            data-testid={id} />
        </div>
        {boleh && (
          <Button variant="outline" size="sm" onClick={() => onJalankan(jadwal)} disabled={!!sibuk}
            title={`Jalankan ${judul.toLowerCase()} sekarang tanpa menunggu jadwal`} data-testid={`ai-set-${jenis}-jalankan`}>
            {sibuk === jenis ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Jalankan sekarang
          </Button>
        )}
      </div>
      {salah && (
        <p id={`${id}-galat`} className="text-xs text-destructive" role="alert" data-testid={`${id}-galat`}>
          {galat[kunciJam] || `Jam ${judul.toLowerCase()} harus berformat JJ:MM (00:00–23:59), mis. 07:00.`}
        </p>
      )}
      <JadwalBerikut info={info} testId={`ai-set-${jenis}-berikutnya`} />
    </div>
  );
}

/** Riwayat jalan terakhir (owner/superadmin): briefing, peringatan per kondisi, laporan mingguan. */
function RiwayatJalan({ riwayat, pengguna, user, onNavigate, memuat, onMuatUlang }) {
  const nama = (id) => (id ? (pengguna.get(id)?.nama || 'Pengguna lain') : '—');
  const rows = riwayat.slice(0, 10);
  return (
    <div className="space-y-2 border-t border-[var(--glass-border)] pt-4" data-testid="ai-set-proaktif-riwayat">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">Riwayat jalan terakhir</p>
          <p className="text-xs text-muted-foreground">Jalan terjadwal dan manual, terbaru di atas.</p>
        </div>
        <Button variant="outline" size="icon" onClick={onMuatUlang} title="Muat ulang" aria-label="Muat ulang riwayat"
          data-testid="ai-set-proaktif-muat-ulang">
          <RefreshCw className={memuat ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
        </Button>
      </div>
      {rows.length === 0 ? (
        <EmptyState icon={History} className="py-6" testId="ai-set-proaktif-riwayat-kosong" title="Riwayat masih kosong"
          description="Jalan terjadwal dan manual tampil di sini setelah jadwal pertama berjalan." />
      ) : (
        <div className="overflow-hidden rounded-[var(--radius-sm)] border border-[var(--glass-border)]">
          <Table className="min-w-0 text-sm">
            <TableHeader>
              <TableRow>
                <TableHead>Waktu</TableHead>
                <TableHead>Jadwal</TableHead>
                <TableHead className="hidden md:table-cell">Untuk</TableHead>
                <TableHead className="hidden sm:table-cell">Pemicu</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.id} data-testid="ai-set-proaktif-riwayat-baris" data-status={r.status}>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTimeID(parseServerTime(r.waktu))}</TableCell>
                  <TableCell className="whitespace-normal">
                    <p className="text-foreground">{r.judul}</p>
                    {r.rincian && <p className="text-xs text-muted-foreground">{r.rincian}{r.jumlah !== null ? ` · ${r.jumlah}` : ''}</p>}
                    {r.sesiId && user?.id && r.userId === String(user.id) && onNavigate && (
                      <Button variant="link" size="sm" className="h-auto px-0 text-xs" data-testid="ai-set-proaktif-buka-sesi"
                        onClick={() => onNavigate('asisten-ai', { sesi: r.sesiId })}>
                        <MessageSquare className="h-3.5 w-3.5" /> Buka percakapan
                      </Button>
                    )}
                  </TableCell>
                  <TableCell className="hidden whitespace-nowrap md:table-cell">{nama(r.userId)}</TableCell>
                  <TableCell className="hidden whitespace-nowrap sm:table-cell">{r.pemicu}</TableCell>
                  <TableCell className="text-right">
                    <StatusBadge status={r.status} label={r.statusLabel} tone={r.tone} />
                    {r.alasan && <p className="mt-0.5 text-xs text-muted-foreground">{r.alasan}</p>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function Penerima({ form, setField, pengguna, peta, memuat, galat }) {
  const terpilih = Array.isArray(form[PENERIMA]) ? form[PENERIMA] : [];
  const sisa = pengguna.filter((u) => !terpilih.includes(u.id));
  const penuh = terpilih.length >= BATAS_PENERIMA;
  const tambah = (id) => { if (id && !terpilih.includes(id) && !penuh) setField(PENERIMA, [...terpilih, id]); };
  const buang = (id) => setField(PENERIMA, terpilih.filter((x) => x !== id));
  return (
    <div className={BARIS} data-testid="ai-set-penerima">
      <Judul judul="Penerima briefing dan laporan mingguan"
        keterangan={`Kosong = semua owner aktif. Paling banyak ${BATAS_PENERIMA} pengguna aktif yang bisa membuka Portal Management.`} />
      <div className="flex flex-wrap items-center gap-1.5">
        {terpilih.length === 0 ? (
          <span className="text-xs text-muted-foreground" data-testid="ai-set-penerima-bawaan">Semua owner aktif</span>
        ) : terpilih.map((id) => {
          const u = peta.get(id);
          const nama = u?.nama || (memuat ? 'Memuat…' : 'Pengguna tidak aktif');
          return (
            <span key={id} className="inline-flex h-8 max-w-full items-center gap-1 rounded-full border border-[var(--glass-border)] pl-3 text-xs text-foreground"
              data-testid={`ai-set-penerima-${id}`}>
              <span className="truncate">{nama}</span>
              {u?.peran && <span className="shrink-0 text-muted-foreground">· {u.peran}</span>}
              <Button variant="ghost" size="icon-sm" className="shrink-0 rounded-full" onClick={() => buang(id)}
                title={`Hapus ${nama} dari penerima`} aria-label={`Hapus ${nama} dari penerima`} data-testid={`ai-set-penerima-hapus-${id}`}>
                <X className="h-3.5 w-3.5" />
              </Button>
            </span>
          );
        })}
      </div>
      <div className="w-full sm:w-72">
        <SmartNativeSelect value="" onChange={(e) => tambah(e.target.value)} className="h-9 w-full" disabled={!sisa.length || penuh}
          aria-label="Tambah penerima" title="Tambah penerima" data-testid="ai-set-penerima-tambah">
          <option value="">
            {memuat ? 'Memuat pengguna…' : (penuh ? `Sudah ${BATAS_PENERIMA} penerima (batas)` : (sisa.length ? 'Tambah penerima…' : 'Semua pengguna sudah dipilih'))}
          </option>
          {sisa.map((u) => <option key={u.id} value={u.id}>{u.peran ? `${u.nama} · ${u.peran}` : u.nama}</option>)}
        </SmartNativeSelect>
      </div>
      {galat[PENERIMA] && <p className="text-xs text-destructive" role="alert" data-testid="ai-set-penerima-galat">{galat[PENERIMA]}</p>}
    </div>
  );
}

/**
 * @param {object} props
 * @param {object} props.form          isian Pengaturan (modul induk) — kunci asisten_* dari bacaPengaturanProaktif
 * @param {(k, v) => void} props.setField
 * @param {object} [props.galat]       {kunciJam: kalimat} dari percobaan simpan terakhir
 * @param {object} [props.tersimpan]   pengaturan dari server (untuk "perubahan belum disimpan")
 * @param {object} [props.user]
 * @param {(menu, params) => void} [props.onNavigate]
 */
export default function PengaturanProaktif({ form, setField, galat = {}, tersimpan, user, onNavigate }) {
  const [pengguna, setPengguna] = useState([]);
  const [memuat, setMemuat] = useState(true);
  const [sibuk, setSibuk] = useState(null);
  const [ringkasan, setRingkasan] = useState(null); // GET /proaktif (owner/superadmin)
  const [memuatRingkasan, setMemuatRingkasan] = useState(false);
  const boleh = bolehJalankanProaktif(user?.role);
  const peta = useMemo(() => new Map(pengguna.map((u) => [u.id, u])), [pengguna]);

  const muatRingkasan = useCallback(async () => {
    if (!boleh) return;
    setMemuatRingkasan(true);
    try {
      setRingkasan(bacaRingkasanProaktif(await asistenApi.ringkasanProaktif()));
    } catch {
      setRingkasan(null); // 403 / server lama: bagian jadwal & riwayat tidak ditampilkan
    } finally {
      setMemuatRingkasan(false);
    }
  }, [boleh]);

  // jadwal berikutnya mengikuti pengaturan TERSIMPAN → dimuat ulang setiap kali pengaturan server berubah (simpan)
  useEffect(() => { muatRingkasan(); }, [muatRingkasan, tersimpan]);

  useEffect(() => {
    let hidup = true;
    asistenApi.daftarPenggunaManajemen()
      .then((d) => { if (hidup) setPengguna(bacaDaftarPengguna(d)); })
      .catch(() => { if (hidup) setPengguna([]); })
      .finally(() => { if (hidup) setMemuat(false); });
    return () => { hidup = false; };
  }, []);

  const jalankan = async (j) => {
    if (sibuk) return;
    const belumDisimpan = proaktifBerubah(form, tersimpan);
    const ok = await confirmDialog({
      title: `Jalankan ${j.judul.toLowerCase()} sekarang?`,
      body: [
        j.adaSesi
          ? `Asisten AI menyusun ${j.judul.toLowerCase()} untuk penerima sekarang juga lalu mengirim notifikasi. Biayanya masuk anggaran AI seperti biasa.`
          : 'Pemeriksaan aturan dijalankan sekarang (tanpa biaya AI); notifikasi dikirim ke peran yang bertanggung jawab.',
        belumDisimpan ? 'Perubahan pengaturan yang belum disimpan tidak ikut dipakai.' : '',
      ].filter(Boolean).join(' '),
      confirmLabel: 'Jalankan',
    });
    if (!ok) return;
    setSibuk(j.jenis);
    try {
      const h = bacaHasilJalankan(await asistenApi.jalankanProaktif(j.jenis), user?.id);
      const pesan = teksHasilJalankan(j, h);
      const opsi = h.sesiId && onNavigate
        ? { duration: 12000, action: { label: 'Buka percakapan', onClick: () => onNavigate('asisten-ai', { sesi: h.sesiId }) } }
        : undefined;
      if (h.dilewati) toast.info(pesan, opsi);
      else toast.success(pesan, opsi);
    } catch (e) {
      toast.error(e?.message || `${j.judul} gagal dijalankan.`);
    } finally {
      setSibuk(null);
      muatRingkasan();
    }
  };

  return (
    <GlassCard className="space-y-4 p-5" data-testid="ai-set-proaktif">
      <div className="flex items-center gap-3">
        <BellRing className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
        <div>
          <p className="text-sm font-semibold text-foreground">Asisten AI proaktif</p>
          <p className="text-xs text-muted-foreground">
            Asisten AI bekerja tanpa ditanya; hasilnya dikirim sebagai notifikasi dengan tautan ke percakapannya. Jam dalam WIB.
          </p>
        </div>
      </div>
      <div className={BARIS} data-testid="ai-set-proaktif-ingatan">
        <Judul judul="Ingatan AI aktif"
          keterangan="Asisten AI boleh mengingat preferensi yang Anda sampaikan (mis. target minimal tumbuh 8%). Bila dimatikan, ingatan tidak dipakai dan tidak ditambah.">
          <span className="flex shrink-0 items-center gap-2">
            <Brain className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <Switch checked={!!form.asisten_ingatan_aktif} onCheckedChange={(v) => setField('asisten_ingatan_aktif', v)}
              aria-label="Ingatan AI aktif" data-testid="ai-set-ingatan-aktif" />
          </span>
        </Judul>
      </div>
      {ringkasan && !ringkasan.aiAktif && (
        <Notice tone="warning" icon={AlertCircle} testId="ai-set-proaktif-ai-mati">
          AI sedang dimatikan (AI Master Switch atau fitur Asisten AI), jadi jadwal di bawah tidak berjalan.
        </Notice>
      )}
      {JADWAL_PROAKTIF.map((j) => (
        <BarisJadwal key={j.jenis} jadwal={j} form={form} setField={setField} galat={galat} boleh={boleh}
          sibuk={sibuk} onJalankan={jalankan} info={ringkasan?.jadwal?.[j.jenis]} />
      ))}
      <Penerima form={form} setField={setField} pengguna={pengguna} peta={peta} memuat={memuat} galat={galat} />
      {ringkasan && (
        <RiwayatJalan riwayat={ringkasan.riwayat} pengguna={peta} user={user} onNavigate={onNavigate}
          memuat={memuatRingkasan} onMuatUlang={muatRingkasan} />
      )}
      {!boleh && (
        <p className="text-xs text-muted-foreground" data-testid="ai-set-proaktif-hanya-owner">
          Tombol "Jalankan sekarang" hanya tersedia untuk owner dan super admin.
        </p>
      )}
    </GlassCard>
  );
}
