/**
 * KartuTindakan — kartu konfirmasi Asisten AI (Tahap B, Kontrak F, 8 Nov 2026).
 *
 * Model hanya MENYIAPKAN rencana; data baru berubah setelah pengguna menekan "Setujui" di sini.
 *   ┌ Usulan perubahan · label alat                                  [StatusBadge]
 *   ├ judul, ringkas, tabel perubahan (yang berubah | sebelum → sesudah), catatan, peringatan
 *   ├ "Ubah": isian sebaris untuk `rencana.ubah` (rupiah berformat, angka, teks, tanggal, pilihan)
 *   ├ Setujui (utama) · Ubah · Batal — dikunci selama permintaan berjalan (tidak ada klik ganda)
 *   │   risiko "menengah": Setujui → dialog alasan (≥ 10 huruf) → konfirmasi kedua
 *   └ setelah diputuskan: ringkas/pesan hasil, isian yang diubah, tautan "Buka layar …" (onNavigate)
 *
 * Teks dari server selalu dirender sebagai teks biasa (React meng-escape); tidak ada HTML mentah.
 */
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight, ArrowUpRight, Ban, Check, CheckCircle2, ClipboardCheck, Clock, Info, Loader2, Pencil, Power,
  Undo2, X, XCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { formatDateTimeID } from '@/lib/format';
import { parseServerTime } from '@/lib/waktu';
import { cn } from '@/lib/utils';
import { Notice, StatusBadge } from '../moduleAtoms';
import {
  PESAN_BAWAAN, daftarUbah, formatNilaiUbah, jenisUbah, keadaanEfektif, keadaanTindakan, nilaiAwalUbah,
  susunUbahan, tautanAman,
} from './tindakanAsisten';

const BARIS_AWAL = 8;
const KEPALA = 'h-9 whitespace-nowrap bg-foreground/[0.03] px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground';

/** Tabel `rencana.perubahan` — dipakai kartu chat dan rincian di halaman Tindakan AI. */
export function TabelPerubahan({ perubahan, testId = 'tindakan-perubahan' }) {
  const [semua, setSemua] = useState(false);
  const rows = (Array.isArray(perubahan) ? perubahan : []).filter((r) => r && typeof r === 'object');
  if (!rows.length) return null;
  const tampil = semua ? rows : rows.slice(0, BARIS_AWAL);
  return (
    <div className="min-w-0 space-y-1" data-testid={testId}>
      <div className="min-w-0 overflow-hidden rounded-[var(--radius-sm)] border border-[var(--glass-border)]">
        <Table className="min-w-0 text-[13px]" wrapperClassName="max-w-full">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className={KEPALA}>Yang berubah</TableHead>
              <TableHead className={KEPALA}>Sebelum → sesudah</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tampil.map((r, i) => {
              const sebelum = String(r.sebelum ?? '') || '—';
              const sesudah = String(r.sesudah ?? '') || '—';
              return (
                <TableRow key={i} data-testid={`${testId}-baris`}>
                  <TableCell className="min-w-[7rem] whitespace-normal px-3 py-2 text-foreground/85">{String(r.label ?? '—')}</TableCell>
                  <TableCell className="whitespace-normal px-3 py-2">
                    {/* nilai pendek (uang, angka) tidak dipatahkan di tengah: "Rp 135.000.000" tetap satu baris */}
                    <span className={cn('text-muted-foreground tabular-nums', sebelum.length <= 24 && 'whitespace-nowrap')}
                      data-testid={`${testId}-sebelum`}>{sebelum}</span>
                    <ArrowRight className="mx-1.5 inline h-3.5 w-3.5 align-[-2px] text-muted-foreground" aria-label="menjadi" />
                    <span className={cn('font-medium text-foreground tabular-nums', sesudah.length <= 24 && 'whitespace-nowrap')}
                      data-testid={`${testId}-sesudah`}>{sesudah}</span>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      {rows.length > BARIS_AWAL && (
        <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setSemua((s) => !s)}
          data-testid={`${testId}-semua`}>
          {semua ? 'Tampilkan lebih sedikit' : `Tampilkan semua (${rows.length} baris)`}
        </Button>
      )}
    </div>
  );
}

/** Catatan (abu) dan peringatan (kuning) rencana. */
export function CatatanRencana({ rencana }) {
  const catatan = (Array.isArray(rencana?.catatan) ? rencana.catatan : []).filter(Boolean).map(String);
  const peringatan = (Array.isArray(rencana?.peringatan) ? rencana.peringatan : []).filter(Boolean).map(String);
  if (!catatan.length && !peringatan.length) return null;
  return (
    <div className="space-y-2">
      {catatan.length > 0 && (
        <ul className="space-y-1" data-testid="tindakan-catatan">
          {catatan.map((c, i) => (
            <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><span className="min-w-0">{c}</span>
            </li>
          ))}
        </ul>
      )}
      {peringatan.length > 0 && (
        <Notice tone="warning" icon={Info} className="px-3 py-2 text-xs" testId="tindakan-peringatan">
          {peringatan.length === 1 ? peringatan[0] : (
            <ul className="list-disc space-y-0.5 pl-4">{peringatan.map((p, i) => <li key={i}>{p}</li>)}</ul>
          )}
        </Notice>
      )}
    </div>
  );
}

function IsianUbah({ field, id, value, onChange, galat, disabled }) {
  const jenis = jenisUbah(field);
  const umum = { id, disabled, 'aria-invalid': galat ? true : undefined, 'data-testid': `tindakan-isian-${field.kunci}` };
  let kotak;
  if (jenis === 'rupiah') {
    kotak = <MoneyInput {...umum} prefix="Rp" value={value} onChange={(e) => onChange(e.target.value)} />;
  } else if (jenis === 'angka') {
    kotak = <MoneyInput {...umum} decimals={2} value={value} onChange={(e) => onChange(e.target.value)} />;
  } else if (jenis === 'tanggal') {
    kotak = <Input {...umum} type="date" value={value} onChange={(e) => onChange(e.target.value)} />;
  } else if (jenis === 'pilihan') {
    kotak = (
      <SmartNativeSelect id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}
        className="h-9 w-full" aria-label={field.label || 'Pilihan'} data-testid={`tindakan-isian-${field.kunci}`}>
        <option value="">— Pilih —</option>
        {(Array.isArray(field.pilihan) ? field.pilihan : []).map((o) => (
          <option key={String(o?.nilai)} value={String(o?.nilai)}>{String(o?.label ?? o?.nilai)}</option>
        ))}
      </SmartNativeSelect>
    );
  } else {
    kotak = <Input {...umum} value={value} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={id} className="block text-xs text-muted-foreground">{field.label || 'Isian'}</label>
      {kotak}
      {galat && <p className="text-xs text-destructive" role="alert" data-testid={`tindakan-galat-${field.kunci}`}>{galat}</p>}
    </div>
  );
}

const IKON_AKHIR = {
  disetujui: Loader2, dijalankan: CheckCircle2, gagal: XCircle, dibatalkan: Ban, kedaluwarsa: Clock, dibalikkan: Undo2,
};
const WARNA_AKHIR = {
  disetujui: 'text-primary', dijalankan: 'text-[hsl(var(--success))]', gagal: 'text-destructive',
};

function pesanAkhir(blok, keadaan) {
  if (keadaan === 'dijalankan') return blok.ringkas || blok.pesan || PESAN_BAWAAN.dijalankan;
  if (keadaan === 'gagal') return blok.pesan || blok.ringkas || PESAN_BAWAAN.gagal;
  if (keadaan === 'disetujui') return PESAN_BAWAAN.disetujui;
  // `ringkas` kartu yang dibalikkan masih hasil jalannya dulu ("Target … terpasang") → jangan ditampilkan sebagai hasil
  if (keadaan === 'dibalikkan') return PESAN_BAWAAN.dibalikkan;
  return blok.pesan || PESAN_BAWAAN[keadaan] || '';
}

/**
 * @param {object} props
 * @param {object} props.blok              blok `tindakan` (Kontrak E)
 * @param {(id, {keputusan, ubahan?, alasan?}) => Promise<{ok:boolean}>} props.onPutuskan
 * @param {(menu) => void} [props.onNavigate]
 * @param {boolean} [props.nonaktif]       jawaban lain sedang mengalir → tombol ditahan
 * @param {boolean} [props.tindakanAktif]  false = admin mematikan Tindakan AI (Setujui ditahan, Batal tetap)
 */
function KartuTindakan({ blok, onPutuskan, onNavigate, nonaktif = false, tindakanAktif = true }) {
  const rencana = useMemo(() => (blok?.rencana && typeof blok.rencana === 'object' ? blok.rencana : {}), [blok?.rencana]);
  const fields = useMemo(() => daftarUbah(rencana), [rencana]);
  const [now, setNow] = useState(() => new Date());
  const keadaan = keadaanEfektif(blok, now);
  const menunggu = keadaan === 'menunggu';
  const info = keadaanTindakan(keadaan);
  const menengah = blok?.risiko === 'menengah';
  const judul = String(rencana.judul || blok?.label || 'Usulan perubahan');
  const tautan = tautanAman(rencana.tautan);

  const [sibuk, setSibuk] = useState(null); // 'setujui' | 'batal' | null
  const kunci = useRef(false);
  const [ubahBuka, setUbahBuka] = useState(false);
  const [isian, setIsian] = useState({});
  const [galat, setGalat] = useState({});

  // kartu menunggu yang lama terbuka berganti jadi kedaluwarsa tanpa reload
  useEffect(() => {
    if (!menunggu || !blok?.kedaluwarsa_pada) return undefined;
    const batas = parseServerTime(blok.kedaluwarsa_pada);
    if (!batas) return undefined;
    const sisa = batas.getTime() - Date.now();
    if (sisa > 2 ** 31 - 1) return undefined;
    const t = setTimeout(() => setNow(new Date()), Math.max(0, sisa) + 500);
    return () => clearTimeout(t);
  }, [menunggu, blok?.kedaluwarsa_pada]);

  useEffect(() => { if (!menunggu) setUbahBuka(false); }, [menunggu]);

  const bukaUbah = () => {
    if (ubahBuka) { setUbahBuka(false); setIsian({}); setGalat({}); return; }
    setIsian(Object.fromEntries(fields.map((f) => [f.kunci, nilaiAwalUbah(f)])));
    setGalat({});
    setUbahBuka(true);
  };

  const kirim = async (keputusan, extra = {}) => {
    if (kunci.current) return;
    kunci.current = true;
    setSibuk(keputusan);
    try {
      const r = await onPutuskan?.(blok.id, { keputusan, ...extra });
      if (r?.ok !== false) { setUbahBuka(false); setIsian({}); }
    } catch { /* galat sudah dikabarkan modul (toast) */ } finally {
      kunci.current = false;
      setSibuk(null);
    }
  };

  const setujui = async () => {
    if (kunci.current || !menunggu || nonaktif || !tindakanAktif) return;
    let ubahan;
    if (ubahBuka) {
      const r = susunUbahan(fields, isian);
      setGalat(r.galat);
      if (!r.ok) return;
      ubahan = r.ubahan;
    }
    let alasan;
    if (menengah) {
      kunci.current = true; // tahan klik lain selama dua dialog terbuka
      try {
        const a = await confirmDialog({
          title: 'Tulis alasan persetujuan',
          body: 'Tindakan ini berisiko menengah. Alasan Anda ikut tercatat di jejak Tindakan AI.',
          confirmLabel: 'Lanjut',
          input: { label: 'Alasan (minimal 10 huruf)', minLength: 10, placeholder: 'Mis. sudah dibahas di rapat mingguan' },
        });
        if (!a) return;
        const ok = await confirmDialog({
          title: 'Setujui dan jalankan sekarang?',
          body: `${judul}. Data langsung diubah setelah Anda menekan "Setujui". Alasan: ${a}`,
          confirmLabel: 'Setujui',
        });
        if (!ok) return;
        alasan = a;
      } finally {
        kunci.current = false;
      }
    }
    await kirim('setujui', { ubahan, alasan });
  };

  const tahan = !!sibuk || nonaktif;
  const IkonAkhir = IKON_AKHIR[keadaan];
  const diubah = Array.isArray(rencana.diubah) ? rencana.diubah : [];
  const batas = menunggu && blok?.kedaluwarsa_pada ? parseServerTime(blok.kedaluwarsa_pada) : null;

  return (
    <section
      className={cn('min-w-0 space-y-3 rounded-[var(--radius-md)] border px-3 py-3 sm:px-4',
        menunggu ? 'border-[hsl(var(--warning)/0.45)]' : 'border-[var(--glass-border)]')}
      aria-label={`Usulan perubahan: ${judul}`}
      data-testid="asisten-tindakan" data-id={blok?.id} data-keadaan={keadaan} data-risiko={menengah ? 'menengah' : 'rendah'}
      aria-busy={!!sibuk}
    >
      <div className="flex items-start gap-2">
        <ClipboardCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">
            Usulan perubahan{blok?.label ? ` · ${blok.label}` : ''}{menengah ? ' · perlu alasan' : ''}
          </p>
          <p className="text-sm font-semibold leading-snug text-foreground" data-testid="tindakan-judul">{judul}</p>
        </div>
        <StatusBadge status={keadaan} label={info.label} tone={info.tone} className="shrink-0" testId="tindakan-status" />
      </div>

      {rencana.ringkas && <p className="text-sm text-foreground/85" data-testid="tindakan-ringkas">{String(rencana.ringkas)}</p>}
      <TabelPerubahan perubahan={rencana.perubahan} />
      <CatatanRencana rencana={rencana} />

      {menunggu && ubahBuka && fields.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2" data-testid="tindakan-ubah">
          {fields.map((f, i) => (
            <IsianUbah key={f.kunci} field={f} id={`tnd-${blok.id}-${i}`} value={isian[f.kunci] ?? ''} galat={galat[f.kunci]}
              disabled={tahan} onChange={(v) => setIsian((s) => ({ ...s, [f.kunci]: v }))} />
          ))}
        </div>
      )}

      {menunggu && (
        <div className="space-y-2">
          {!tindakanAktif && (
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="tindakan-mati">
              <Power className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Tindakan AI sedang dimatikan admin, jadi usulan ini belum bisa disetujui.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={setujui} disabled={tahan || !tindakanAktif}
              title={!tindakanAktif ? 'Tindakan AI sedang dimatikan admin' : (nonaktif ? 'Tunggu jawaban selesai' : undefined)}
              data-testid="tindakan-setujui">
              {sibuk === 'setujui' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Setujui
            </Button>
            {fields.length > 0 && (
              <Button size="sm" variant="outline" onClick={bukaUbah} disabled={tahan} aria-expanded={ubahBuka}
                data-testid="tindakan-ubah-buka">
                {ubahBuka ? <Undo2 className="h-4 w-4" /> : <Pencil className="h-4 w-4" />}
                {ubahBuka ? 'Urungkan ubahan' : 'Ubah'}
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => kirim('batal')} disabled={tahan}
              title={nonaktif ? 'Tunggu jawaban selesai' : undefined} data-testid="tindakan-batal">
              {sibuk === 'batal' ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
              Batal
            </Button>
            {batas && (
              <span className="text-xs text-muted-foreground" data-testid="tindakan-batas">
                Berlaku sampai {formatDateTimeID(batas)}
              </span>
            )}
          </div>
        </div>
      )}

      {!menunggu && (
        <p className="flex items-start gap-1.5 text-sm text-foreground/85" data-testid="tindakan-hasil">
          {IkonAkhir && <IkonAkhir className={cn('mt-0.5 h-4 w-4 shrink-0', WARNA_AKHIR[keadaan] || 'text-muted-foreground',
            keadaan === 'disetujui' && 'animate-spin')} aria-hidden="true" />}
          <span className="min-w-0">{pesanAkhir(blok, keadaan)}</span>
        </p>
      )}

      {!menunggu && diubah.length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="tindakan-diubah">
          Diubah sebelum disetujui: {diubah.map((d) => `${d.label} ${formatNilaiUbah(d, d.sesudah)}`).join(' · ')}
        </p>
      )}

      {tautan && onNavigate && (
        <Button variant="link" size="sm" className="h-auto px-0" onClick={() => onNavigate(tautan.menu)} data-testid="tindakan-tautan">
          {tautan.label} <ArrowUpRight className="h-3.5 w-3.5" />
        </Button>
      )}
    </section>
  );
}

export default memo(KartuTindakan);
