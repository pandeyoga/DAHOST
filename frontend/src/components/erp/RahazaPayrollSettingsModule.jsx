/**
 * RahazaPayrollSettingsModule — tab "Pengaturan gaji" di hub Penggajian.
 *
 * 2026-11-02 (keputusan owner K22/K23/K24/K25): SATU layar untuk SELURUH koleksi `rahaza_payroll_settings`
 * (API `GET/PUT /api/rahaza/payroll-settings/*`). Tidak membuat koleksi/layar pengaturan baru:
 *   - Keterlambatan & Bonus Kehadiran (kunci late_penalty / attendance_bonus)
 *   - BPJS: tarif & plafon per program, kelas risiko JKK, saklar jurnal iuran perusahaan (hanya owner)
 *   - Lembur: aturan cadangan 1/173 × upah tetap, tingkatan hari kerja & hari istirahat
 *   - Kasbon: batas % gaji pokok & maks cicilan (0 = tanpa batas)
 * 2026-11-06 (Tahap 2): + Kalender kerja (hari kerja per minggu, bawaan 6), PPh21 (TER A/B/C, PTKP, tarif
 *   progresif — bisa diubah HR/Keuangan), aturan hangus bonus kehadiran per jenis, tingkatan lembur hari libur.
 * Kepesertaan BPJS per karyawan diatur di Data Karyawan (tab Pajak & BPJS), tarif lembur per orang di Profil Gaji.
 *
 * Standar UI/UX v2 (8 Nov 2026, keputusan owner #2 "form selalu popup"): halaman ini dulu berisi 7 formulir
 * terbuka sekaligus (± 70 isian, layar sangat panjang). Kini halaman menampilkan RINGKASAN aturan yang berlaku,
 * dikelompokkan; tombol "Ubah" membuka FormPopup berisi isian yang sama dan menyimpan ke endpoint yang sama
 * dengan isi yang sama. Ubahan yang dibatalkan tidak tersimpan (dulu tetap tertinggal di layar sampai dimuat ulang).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { BarisDetail } from '@/components/ui/detail-popup';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { MoneyInput } from '@/components/ui/money-input';
import PageLayout from './layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL || '';

const RATE_FIELDS = [
  ['kes_emp', 'Kesehatan — karyawan'], ['kes_comp', 'Kesehatan — perusahaan'],
  ['jht_emp', 'JHT — karyawan'], ['jht_comp', 'JHT — perusahaan'],
  ['jp_emp', 'JP — karyawan'], ['jp_comp', 'JP — perusahaan'], ['jkm_comp', 'JKM — perusahaan'],
];
const JKK_TIERS = [['very_low', 'Sangat rendah'], ['low', 'Rendah'], ['medium', 'Sedang'], ['high', 'Tinggi'], ['very_high', 'Sangat tinggi']];
const PTKP_CODES = ['TK/0', 'TK/1', 'TK/2', 'TK/3', 'K/0', 'K/1', 'K/2', 'K/3'];
const TER_CATS = ['A', 'B', 'C'];
const WORK_WEEK_OPTIONS = [[6, '6 hari (Senin–Sabtu)'], [5, '5 hari (Senin–Jumat)'], [7, '7 hari']];
const OT_BASIS = { upah_tetap_div_173: 'Upah tetap ÷ pembagi', manual: 'Tanpa cadangan (hanya peringatan)' };
const LATE_MODE = { per_minute: 'Per menit', per_occurrence: 'Per kejadian', tiered: 'Bertingkat' };

const pct = (v) => Math.round(Number(v || 0) * 100000) / 1000;   // 0.037 → 3.7
const unpct = (v) => Number(v || 0) / 100;
const rp = (v) => `Rp ${Number(v || 0).toLocaleString('id-ID')}`;
const pctTeks = (v) => `${String(pct(v)).replace('.', ',')}%`;
const kali = (v) => `× ${String(v ?? '—').replace('.', ',')}`;
const yaTidak = (v) => (v ? 'Ya' : 'Tidak');

async function errDetail(r, fallback) {
  try { const d = await r.json(); return (typeof d.detail === 'string' ? d.detail : d.detail?.message) || fallback; }
  catch { return fallback; }
}

/** Kotak centang berlabel (komponen bersama Checkbox). */
function Check({ label, checked, onChange, disabled, testId }) {
  return (
    <label className="flex items-start gap-2.5 text-sm">
      <Checkbox className="mt-0.5" checked={!!checked} disabled={disabled} onCheckedChange={v => onChange(v === true)} data-testid={testId} />
      <span>{label}</span>
    </label>
  );
}

/** Kartu ringkasan satu bagian pengaturan: judul, satu kalimat, nilai yang berlaku, tombol Ubah. */
function Ringkasan({ title, note, onEdit, testId, children }) {
  return (
    <GlassCard className="space-y-2 p-4" data-testid={testId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-base font-semibold text-foreground">{title}</p>
          {note && <p className="mt-0.5 text-sm text-muted-foreground">{note}</p>}
        </div>
        <Button size="sm" variant="outline" onClick={onEdit} data-testid={`${testId}-edit`}><Pencil />Ubah</Button>
      </div>
      <dl className="divide-y divide-[var(--glass-border)]">{children}</dl>
    </GlassCard>
  );
}

/* Tabel tarif [batas atas | tarif %]; baris terakhir tanpa batas atas (= selebihnya). */
function RateTable({ rows, onChange, testId, boundLabel = 'Penghasilan bruto sampai (Rp)' }) {
  const setRow = (i, k, v) => onChange(rows.map((r, j) => (j === i ? (k === 0 ? [v, r[1]] : [r[0], v]) : r)));
  return (
    <Table data-testid={testId}>
      <TableHeader>
        <TableRow><TableHead className="w-12">No</TableHead><TableHead>{boundLabel}</TableHead><TableHead className="w-32 text-right">Tarif (%)</TableHead></TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={i}>
            <TableCell className="tabular-nums">{i + 1}</TableCell>
            <TableCell>
              {i === rows.length - 1
                ? <span className="text-sm text-muted-foreground">selebihnya</span>
                : <MoneyInput value={r[0] ?? 0} onChange={e => setRow(i, 0, Number(e.target.value))} aria-label={`Batas baris ${i + 1}`} />}
            </TableCell>
            <TableCell className="text-right">
              <Input type="number" step="0.01" min="0" className="text-right" value={pct(r[1])} aria-label={`Tarif baris ${i + 1}`}
                onChange={e => setRow(i, 1, unpct(e.target.value))} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

const SEKSI_JUDUL = {
  cal: 'Kalender kerja', pph: 'PPh21 — metode TER', bpjs: 'BPJS — tarif, plafon, kelas risiko JKK',
  ot: 'Lembur — pengali per hari', bonus: 'Bonus kehadiran — kapan hangus', late: 'Potongan keterlambatan',
  kasbon: 'Batas kasbon & pinjaman',
};

export default function RahazaPayrollSettingsModule({ token }) {
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState('');
  const [late, setLate] = useState(null);
  const [bonus, setBonus] = useState(null);
  const [bpjs, setBpjs] = useState(null);
  const [ot, setOt] = useState(null);
  const [kasbon, setKasbon] = useState(null);
  const [cal, setCal] = useState(null);
  const [pph, setPph] = useState(null);
  const [terCat, setTerCat] = useState('A');
  const [allowanceList, setAllowanceList] = useState([]);
  const [memuat, setMemuat] = useState(false);
  const [edit, setEdit] = useState('');       // '' | cal | pph | bpjs | ot | bonus | late | kasbon
  const [galat, setGalat] = useState('');

  /** Isi ulang semua salinan isian dari data tersimpan (dipakai saat memuat & saat popup dibuka). */
  const isiDari = useCallback((d) => {
    setLate({ ...d.late_penalty, tiers: d.late_penalty?.tiers || [] });
    setBonus({ ...d.attendance_bonus, allowance_ids: d.attendance_bonus?.allowance_ids || [] });
    setBpjs({ ...d.bpjs, rates: { ...(d.bpjs?.rates || {}) }, ceilings: { ...(d.bpjs?.ceilings || {}) },
              jkk_rates: { ...(d.bpjs?.jkk_rates || {}) } });
    setOt({ ...d.overtime });
    setKasbon({ ...d.kasbon });
    setCal({ ...d.work_calendar });
    setPph(d.pph21 ? { ...d.pph21, ptkp: { ...d.pph21.ptkp }, ter: { ...d.pph21.ter }, brackets: [...(d.pph21.brackets || [])] } : null);
  }, []);

  const load = useCallback(async () => {
    setMemuat(true);
    try {
      const r = await fetch(`${API}/api/rahaza/payroll-settings`, { headers });
      if (!r.ok) { toast.error(await errDetail(r, `Gagal memuat pengaturan (HTTP ${r.status})`)); return; }
      const d = await r.json();
      setData(d);
      isiDari(d);
      const ra = await fetch(`${API}/api/rahaza/payroll-allowances`, { headers }).catch(() => null);
      if (ra && ra.ok) setAllowanceList(((await ra.json()).allowances || []).filter(a => a.is_active !== false));
    } finally { setMemuat(false); }
  }, [headers, isiDari]);
  useEffect(() => { load(); }, [load]);

  const save = async (key, path, body) => {
    setSaving(key);
    setGalat('');
    try {
      const r = await fetch(`${API}/api/rahaza/${path}`, { method: 'PUT', headers, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await errDetail(r, `HTTP ${r.status}`));
      toast.success('Pengaturan tersimpan.');
      setEdit('');
      await load();
    } catch (e) { setGalat(`Gagal menyimpan: ${e.message}`); }
    finally { setSaving(''); }
  };

  const resetPph = async () => {
    const ok = await confirmDialog({ title: 'Kembalikan PPh21 ke bawaan peraturan?',
      body: 'PTKP, tarif progresif, dan tabel TER kembali ke PMK 101/2016, UU HPP, dan PP 58/2023.', confirmLabel: 'Kembalikan' });
    if (ok) save('pph', 'payroll-settings/pph21', { reset: true });
  };

  const buka = (key) => { if (data) isiDari(data); setGalat(''); setTerCat('A'); setEdit(key); };
  const tutup = () => { if (!saving) setEdit(''); };

  const tools = (
    <Button variant="outline" size="icon" onClick={load} disabled={memuat} title="Muat ulang" aria-label="Muat ulang" data-testid="ps-reload">
      <RefreshCw className={memuat ? 'animate-spin' : ''} />
    </Button>
  );

  if (!data || !late || !bpjs || !ot || !kasbon || !bonus || !cal) {
    return (
      <PageLayout title="Pengaturan penggajian" subtitle="Aturan penggajian: hari kerja, PPh21, BPJS, lembur, kehadiran, dan kasbon." tools={tools}>
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat pengaturan…</p>
      </PageLayout>
    );
  }
  const canToggle = !!data.can_toggle_bpjs_journal;
  const num = (setter, k) => (e) => setter(s => ({ ...s, [k]: e.target.value === '' ? '' : Number(e.target.value) }));
  const toggleAllowance = (id, on) => setBonus(b => ({
    ...b, allowance_ids: on ? [...new Set([...(b.allowance_ids || []), id])] : (b.allowance_ids || []).filter(x => x !== id),
  }));

  // Ringkasan dibaca dari DATA TERSIMPAN (bukan salinan isian yang sedang diubah).
  const d = data;
  const sPph = d.pph21;
  const sB = d.bpjs || {};
  const sR = sB.rates || {};
  const sOt = d.overtime || {};
  const sBo = d.attendance_bonus || {};
  const sLa = d.late_penalty || {};
  const sKa = d.kasbon || {};
  const hangus = (aktif, maks, satuan = 'hari') => (aktif ? `hangus bila lebih dari ${maks || 0} ${satuan}` : 'tidak dipakai');
  const namaTunjangan = (ids) => {
    const nama = (ids || []).map(id => allowanceList.find(a => a.allowance_id === id)?.name).filter(Boolean);
    return nama.length ? nama.join(', ') : 'Tunjangan yang namanya memuat kata "kehadiran"';
  };
  const ptkpUrut = sPph ? PTKP_CODES.map(c => [c, Number(sPph.ptkp?.[c] || 0)]).sort((a, b) => a[1] - b[1]) : [];
  const brk = sPph?.brackets || [];

  // Kelompok mengalir dalam dua kolom (bukan grid berbaris) supaya kartu pendek tidak menyisakan ruang kosong.
  const kelompok = (judul, isi) => (
    <section className="mb-4 space-y-2 break-inside-avoid">
      <h3 className="text-lg font-semibold text-foreground">{judul}</h3>
      <div className="space-y-4">{isi}</div>
    </section>
  );

  return (
    <PageLayout title="Pengaturan penggajian" testId="payroll-settings-page"
      subtitle="Aturan penggajian: hari kerja, PPh21, BPJS, lembur, kehadiran, dan kasbon." tools={tools}>
      <div className="gap-4 lg:columns-2" data-testid="ps-ringkasan">
      {kelompok('Gaji & pajak', <>
        <Ringkasan title={SEKSI_JUDUL.cal} testId="ps-calendar" onEdit={() => buka('cal')}
          note="Pembagi gaji harian = hari kerja aktif periode (hari libur dari Kalender Libur).">
          <BarisDetail label="Hari kerja per minggu">
            {(WORK_WEEK_OPTIONS.find(([v]) => v === Number(d.work_calendar?.work_days_per_week || 6)) || [0, `${d.work_calendar?.work_days_per_week} hari`])[1]}
          </BarisDetail>
        </Ringkasan>

        {sPph && (
          <Ringkasan title={SEKSI_JUDUL.pph} testId="ps-pph21" onEdit={() => buka('pph')}
            note="TER tiap bulan, dihitung ulang setahun di Desember atau bulan terakhir bekerja.">
            <BarisDetail label="Potong PPh21 di slip">{yaTidak(sPph.enabled)}</BarisDetail>
            <BarisDetail label="Hitung ulang setahun">{yaTidak(sPph.december_true_up)}</BarisDetail>
            <BarisDetail label="Premi perusahaan masuk bruto">{yaTidak(sPph.employer_premiums_taxable)}</BarisDetail>
            <BarisDetail label="Tambahan tanpa NPWP/NIK">{sPph.no_npwp_surcharge_enabled ? pctTeks(sPph.no_npwp_surcharge_rate) : 'Mati'}</BarisDetail>
            <BarisDetail label="Biaya jabatan">{pctTeks(sPph.biaya_jabatan_rate)}, maks {rp(sPph.biaya_jabatan_max_month)} per bulan</BarisDetail>
            <BarisDetail label="PTKP setahun">
              {ptkpUrut.length ? `${rp(ptkpUrut[0][1])} (${ptkpUrut[0][0]}) sampai ${rp(ptkpUrut[ptkpUrut.length - 1][1])} (${ptkpUrut[ptkpUrut.length - 1][0]})` : '—'}
            </BarisDetail>
            <BarisDetail label="Tarif progresif">
              {brk.length ? `${brk.length} lapis, ${pctTeks(brk[0]?.[1])} sampai ${pctTeks(brk[brk.length - 1]?.[1])}` : '—'}
            </BarisDetail>
            <BarisDetail label="Tabel TER bulanan">
              {TER_CATS.map(c => `Kategori ${c}: ${(sPph.ter?.[c] || []).length} baris`).join(' · ')}
            </BarisDetail>
          </Ringkasan>
        )}

        <Ringkasan title={SEKSI_JUDUL.bpjs} testId="ps-bpjs" onEdit={() => buka('bpjs')}
          note="Potongan hanya untuk program yang dicentang di Data Karyawan; dihitung per bulan.">
          <BarisDetail label="Kesehatan">karyawan {pctTeks(sR.kes_emp)} · perusahaan {pctTeks(sR.kes_comp)} · plafon {rp(sB.ceilings?.kes)}</BarisDetail>
          <BarisDetail label="JHT">karyawan {pctTeks(sR.jht_emp)} · perusahaan {pctTeks(sR.jht_comp)}</BarisDetail>
          <BarisDetail label="JP">karyawan {pctTeks(sR.jp_emp)} · perusahaan {pctTeks(sR.jp_comp)} · plafon {rp(sB.ceilings?.jp)}</BarisDetail>
          <BarisDetail label="JKM">perusahaan {pctTeks(sR.jkm_comp)}</BarisDetail>
          <BarisDetail label="Kelas risiko JKK">
            {(JKK_TIERS.find(([k]) => k === sB.jkk_risk_tier) || [0, sB.jkk_risk_tier || '—'])[1]} — {pctTeks(sB.jkk_rates?.[sB.jkk_risk_tier])}
          </BarisDetail>
          <BarisDetail label="Jurnal iuran perusahaan">{sB.employer_contribution_journal ? 'Nyala' : 'Mati'}</BarisDetail>
        </Ringkasan>
      </>)}

      {kelompok('Kehadiran & lembur', <>
        <Ringkasan title={SEKSI_JUDUL.ot} testId="ps-overtime" onEdit={() => buka('ot')}
          note="Dibayar hanya bila pengajuan disetujui atau HR menandai lembur hari itu dibayar (PP 35/2021).">
          <BarisDetail label="Bila tarif profil 0">{OT_BASIS[sOt.basis] || sOt.basis || '—'}{sOt.basis === 'upah_tetap_div_173' ? ` (${sOt.divisor || 173})` : ''}</BarisDetail>
          <BarisDetail label="Hari kerja">jam ke-1 {kali(sOt.first_hour_multiplier)} · jam berikutnya {kali(sOt.next_hours_multiplier)}</BarisDetail>
          <BarisDetail label="Hari libur">
            {sOt.rest_day_first_hours_6d} jam awal (6 hari kerja) / {sOt.rest_day_first_hours_5d} jam awal (5 hari kerja) {kali(sOt.rest_day_first_multiplier)} ·
            jam sesudahnya {kali(sOt.rest_day_next_hour_multiplier)} · selanjutnya {kali(sOt.rest_day_after_multiplier)}
          </BarisDetail>
        </Ringkasan>

        <Ringkasan title={SEKSI_JUDUL.bonus} testId="ps-bonus" onEdit={() => buka('bonus')}
          note="Bonus dibayar lewat tunjangan terpilih; selalu hangus bila tidak ada hari hadir.">
          <BarisDetail label="Aturan hangus">{sBo.enabled ? 'Aktif' : 'Tidak aktif'}</BarisDetail>
          <BarisDetail label="Alpa">{hangus(sBo.forfeit_if_alpa, sBo.max_alpa_days)}</BarisDetail>
          <BarisDetail label="Izin/sakit tanpa surat">{hangus(sBo.forfeit_if_izin_no_note, sBo.max_izin_no_note_days)}</BarisDetail>
          <BarisDetail label="Terlambat">
            {hangus(sBo.forfeit_if_late, sBo.max_late_days_allowed)}{Number(sBo.late_minutes_limit || 0) > 0 ? ` · batas total ${sBo.late_minutes_limit} menit` : ''}
          </BarisDetail>
          <BarisDetail label="Minimal hari hadir">{Number(sBo.min_days_present || 0) > 0 ? `${sBo.min_days_present} hari` : 'Tidak dipakai'}</BarisDetail>
          <BarisDetail label="Tunjangan yang dihitung">{namaTunjangan(sBo.allowance_ids)}</BarisDetail>
        </Ringkasan>

        <Ringkasan title={SEKSI_JUDUL.late} testId="ps-late" onEdit={() => buka('late')}
          note="Selama tidak aktif, sistem tidak memotong keterlambatan sama sekali.">
          <BarisDetail label="Status">{sLa.enabled ? 'Aktif' : 'Tidak aktif'}</BarisDetail>
          <BarisDetail label="Cara potong">{LATE_MODE[sLa.mode] || sLa.mode || '—'}</BarisDetail>
          {sLa.mode === 'tiered'
            ? <BarisDetail label="Tingkatan">{(sLa.tiers || []).length} tingkat</BarisDetail>
            : <BarisDetail label="Besar potongan">{rp(sLa.amount_per_minute)} per menit · {rp(sLa.amount_per_occurrence)} per kejadian</BarisDetail>}
        </Ringkasan>
      </>)}

      {kelompok('Kasbon', (
        <Ringkasan title={SEKSI_JUDUL.kasbon} testId="ps-kasbon" onEdit={() => buka('kasbon')}
          note="Dicek saat pengajuan dan saat HR menyetujui. 0 = tanpa batas.">
          <BarisDetail label="Maks % gaji pokok">{Number(sKa.max_pct_of_base_salary || 0) > 0 ? `${sKa.max_pct_of_base_salary}%` : 'Tanpa batas'}</BarisDetail>
          <BarisDetail label="Maks jumlah cicilan">{Number(sKa.max_installments || 0) > 0 ? `${sKa.max_installments} kali` : 'Tanpa batas'}</BarisDetail>
        </Ringkasan>
      ))}
      </div>

      {/* ── KALENDER KERJA (Tahap 2) ─────────────────────────────────────── */}
      <FormPopup open={edit === 'cal'} onClose={tutup} ukuran="pendek" judul={SEKSI_JUDUL.cal} testId="ps-calendar-form"
        keterangan="Pembagi gaji harian = hari kerja aktif periode: hari kerja per minggu dikurangi hari libur di Kalender Libur."
        menyimpan={saving === 'cal'} galat={galat}
        onSimpan={() => save('cal', 'payroll-settings/work-calendar', { work_days_per_week: Number(cal.work_days_per_week) })}>
        <Isian label="Hari kerja per minggu">
          <SmartNativeSelect value={String(cal.work_days_per_week || 6)} data-testid="ps-cal-days" searchable={false}
            onChange={e => setCal(c => ({ ...c, work_days_per_week: Number(e.target.value) }))}>
            {WORK_WEEK_OPTIONS.map(([v, l]) => <option key={v} value={String(v)}>{l}</option>)}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>

      {/* ── PPh21 (Tahap 2) ─────────────────────────────────────────────── */}
      {pph && (
        <FormPopup open={edit === 'pph'} onClose={tutup} ukuran="panjang" judul={SEKSI_JUDUL.pph} testId="ps-pph21-form"
          keterangan="TER bulanan setiap bulan, dihitung ulang setahun di Desember (atau bulan terakhir bekerja). Bawaan: PP 58/2023, PMK 168/2023, UU HPP, PMK 101/2016."
          menyimpan={saving === 'pph'} galat={galat}
          aksiKiri={<Button type="button" variant="outline" onClick={resetPph} disabled={!!saving} data-testid="ps-pph21-reset">Bawaan peraturan</Button>}
          onSimpan={() => save('pph', 'payroll-settings/pph21', {
            enabled: !!pph.enabled, december_true_up: !!pph.december_true_up,
            employer_premiums_taxable: !!pph.employer_premiums_taxable,
            no_npwp_surcharge_enabled: !!pph.no_npwp_surcharge_enabled, no_npwp_surcharge_rate: pph.no_npwp_surcharge_rate,
            biaya_jabatan_rate: pph.biaya_jabatan_rate, biaya_jabatan_max_month: pph.biaya_jabatan_max_month,
            ptkp: pph.ptkp, brackets: pph.brackets, ter: pph.ter, ter_category: pph.ter_category,
          })}>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <Check label="Potong PPh21 di slip gaji" checked={pph.enabled} testId="ps-pph21-enabled"
              onChange={v => setPph(p => ({ ...p, enabled: v }))} />
            <Check label="Hitung ulang setahun di Desember / bulan terakhir bekerja" checked={pph.december_true_up}
              onChange={v => setPph(p => ({ ...p, december_true_up: v }))} />
            <Check label="Premi JKK, JKM, BPJS Kesehatan dari perusahaan masuk penghasilan bruto" checked={pph.employer_premiums_taxable}
              onChange={v => setPph(p => ({ ...p, employer_premiums_taxable: v }))} />
            <Check label="Tambahan bagi karyawan tanpa NPWP/NIK" checked={pph.no_npwp_surcharge_enabled} testId="ps-pph21-surcharge"
              onChange={v => setPph(p => ({ ...p, no_npwp_surcharge_enabled: v }))} />
          </div>
          <p className="text-sm text-muted-foreground">
            Sejak 2024 NIK 16 digit berlaku sebagai NPWP, jadi tambahan tanpa NPWP bawaannya mati. Iuran JHT &amp; JP karyawan
            mengurangi penghasilan setahun; iuran BPJS Kesehatan karyawan tidak.
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Isian label="Tambahan tanpa NPWP (%)">
              <Input type="number" step="1" min="0" value={pct(pph.no_npwp_surcharge_rate)}
                onChange={e => setPph(p => ({ ...p, no_npwp_surcharge_rate: unpct(e.target.value) }))} />
            </Isian>
            <Isian label="Biaya jabatan (%)">
              <Input type="number" step="0.5" min="0" value={pct(pph.biaya_jabatan_rate)}
                onChange={e => setPph(p => ({ ...p, biaya_jabatan_rate: unpct(e.target.value) }))} />
            </Isian>
            <Isian label="Biaya jabatan maks per bulan (Rp)">
              <MoneyInput value={pph.biaya_jabatan_max_month}
                onChange={e => setPph(p => ({ ...p, biaya_jabatan_max_month: Number(e.target.value) }))} />
            </Isian>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">PTKP setahun dan kategori TER</p>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {PTKP_CODES.map(code => (
                <Isian key={code} label={`${code} — kategori ${pph.ter_category?.[code] || 'A'}`}>
                  <MoneyInput value={pph.ptkp?.[code] ?? 0} data-testid={`ps-ptkp-${code}`}
                    onChange={e => setPph(p => ({ ...p, ptkp: { ...p.ptkp, [code]: Number(e.target.value) } }))} />
                </Isian>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Tarif progresif setahun (perhitungan Desember)</p>
            <RateTable rows={pph.brackets || []} boundLabel="Penghasilan kena pajak sampai (Rp)" testId="ps-pph21-brackets"
              onChange={rows => setPph(p => ({ ...p, brackets: rows }))} />
          </div>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Tabel TER bulanan</p>
              <SmartNativeSelect className="w-40" value={terCat} onChange={e => setTerCat(e.target.value)} searchable={false}
                aria-label="Kategori TER" data-testid="ps-ter-cat">
                {TER_CATS.map(c => <option key={c} value={c}>Kategori {c}</option>)}
              </SmartNativeSelect>
            </div>
            <RateTable rows={pph.ter?.[terCat] || []} testId="ps-pph21-ter"
              onChange={rows => setPph(p => ({ ...p, ter: { ...p.ter, [terCat]: rows } }))} />
          </div>
        </FormPopup>
      )}

      {/* ── BPJS ─────────────────────────────────────────────────────────── */}
      <FormPopup open={edit === 'bpjs'} onClose={tutup} ukuran="panjang" judul={SEKSI_JUDUL.bpjs} testId="ps-bpjs-form"
        keterangan="Potongan hanya untuk program yang dicentang di Data Karyawan. Berlaku untuk semua skema gaji, dihitung per bulan."
        menyimpan={saving === 'bpjs'} galat={galat}
        onSimpan={() => save('bpjs', 'payroll-settings/bpjs', {
          rates: Object.fromEntries(RATE_FIELDS.map(([k]) => [k, unpct(pct(bpjs.rates[k]))])),
          ceilings: bpjs.ceilings, jkk_rates: bpjs.jkk_rates, jkk_risk_tier: bpjs.jkk_risk_tier,
          employer_contribution_journal: !!bpjs.employer_contribution_journal,
        })}>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {RATE_FIELDS.map(([k, label]) => (
            <Isian key={k} label={`${label} (%)`}>
              <Input type="number" step="0.01" min="0" value={pct(bpjs.rates[k])}
                onChange={e => setBpjs(b => ({ ...b, rates: { ...b.rates, [k]: unpct(e.target.value) } }))}
                data-testid={`ps-bpjs-rate-${k}`} />
            </Isian>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Isian label="Plafon Kesehatan (Rp)">
            <MoneyInput value={bpjs.ceilings.kes}
              onChange={e => setBpjs(b => ({ ...b, ceilings: { ...b.ceilings, kes: Number(e.target.value) } }))} />
          </Isian>
          <Isian label="Plafon JP (Rp)">
            <MoneyInput value={bpjs.ceilings.jp}
              onChange={e => setBpjs(b => ({ ...b, ceilings: { ...b.ceilings, jp: Number(e.target.value) } }))} />
          </Isian>
          <Isian label="Kelas risiko JKK" petunjuk={`Tarif: ${pctTeks(bpjs.jkk_rates[bpjs.jkk_risk_tier])} (cek sertifikat kepesertaan)`}>
            <SmartNativeSelect value={bpjs.jkk_risk_tier} data-testid="ps-bpjs-jkk" searchable={false}
              onChange={e => setBpjs(b => ({ ...b, jkk_risk_tier: e.target.value }))}>
              {JKK_TIERS.map(([k, l]) => <option key={k} value={k}>{l} — {pctTeks(bpjs.jkk_rates[k])}</option>)}
            </SmartNativeSelect>
          </Isian>
        </div>
        <div className="space-y-1">
          <Check label="Jurnal iuran BPJS perusahaan saat finalisasi gaji (debit 6-3200 / 6-3300, kredit 2-1501 / 2-1502)"
            checked={bpjs.employer_contribution_journal} disabled={!canToggle} testId="ps-bpjs-journal"
            onChange={v => setBpjs(b => ({ ...b, employer_contribution_journal: v }))} />
          <p className="pl-6 text-xs text-muted-foreground">
            Bawaan mati. {canToggle ? 'Anda (owner) dapat menyalakannya.' : 'Hanya owner yang dapat mengubah saklar ini.'}{' '}
            Iuran perusahaan tetap dihitung dan tampil di slip walau saklar mati.
          </p>
        </div>
      </FormPopup>

      {/* ── LEMBUR ───────────────────────────────────────────────────────── */}
      <FormPopup open={edit === 'ot'} onClose={tutup} ukuran="panjang" judul={SEKSI_JUDUL.ot} testId="ps-overtime-form"
        keterangan="Dibayar hanya bila ada pengajuan disetujui atau HR menandai lembur hari itu dibayar. Pengali dari sini, bukan pilihan pemohon (PP 35/2021)."
        menyimpan={saving === 'ot'} galat={galat}
        onSimpan={() => save('ot', 'payroll-settings/overtime', ot)}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Upah sejam bila tarif Profil Gaji 0">
            <SmartNativeSelect value={ot.basis} onChange={e => setOt(o => ({ ...o, basis: e.target.value }))} searchable={false} data-testid="ps-ot-basis">
              <option value="upah_tetap_div_173">Upah tetap ÷ pembagi</option>
              <option value="manual">Tanpa cadangan (hanya peringatan)</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Pembagi" petunjuk="Permenaker: 173 jam/bulan"><Input type="number" min="1" value={ot.divisor} onChange={num(setOt, 'divisor')} /></Isian>
          <Isian label="Hari kerja: pengali jam ke-1"><Input type="number" step="0.1" min="1" value={ot.first_hour_multiplier} onChange={num(setOt, 'first_hour_multiplier')} /></Isian>
          <Isian label="Hari kerja: jam berikutnya"><Input type="number" step="0.1" min="1" value={ot.next_hours_multiplier} onChange={num(setOt, 'next_hours_multiplier')} /></Isian>
          <Isian label="Hari libur: jam awal (6 hari kerja)" petunjuk="Jam ke-1 sampai ini memakai pengali awal"><Input type="number" min="1" value={ot.rest_day_first_hours_6d} onChange={num(setOt, 'rest_day_first_hours_6d')} /></Isian>
          <Isian label="Hari libur: jam awal (5 hari kerja)"><Input type="number" min="1" value={ot.rest_day_first_hours_5d} onChange={num(setOt, 'rest_day_first_hours_5d')} /></Isian>
          <Isian label="Hari libur: pengali awal"><Input type="number" step="0.1" min="1" value={ot.rest_day_first_multiplier} onChange={num(setOt, 'rest_day_first_multiplier')} /></Isian>
          <Isian label="Hari libur: jam sesudahnya / selanjutnya" petunjuk="Satu jam berikutnya, lalu jam-jam selanjutnya">
            <div className="flex gap-2">
              <Input type="number" step="0.1" min="1" value={ot.rest_day_next_hour_multiplier} onChange={num(setOt, 'rest_day_next_hour_multiplier')} aria-label="Pengali satu jam berikutnya" />
              <Input type="number" step="0.1" min="1" value={ot.rest_day_after_multiplier} onChange={num(setOt, 'rest_day_after_multiplier')} aria-label="Pengali jam selanjutnya" />
            </div>
          </Isian>
        </div>
      </FormPopup>

      {/* ── BONUS KEHADIRAN ──────────────────────────────────────────────── */}
      <FormPopup open={edit === 'bonus'} onClose={tutup} ukuran="panjang" judul={SEKSI_JUDUL.bonus} testId="ps-bonus-form"
        keterangan="Bonus dibayar lewat tunjangan yang dipilih di bawah. Bonus hangus bila salah satu aturan aktif terlampaui, dan selalu hangus bila tidak ada hari hadir."
        menyimpan={saving === 'bonus'} galat={galat}
        onSimpan={() => save('bonus', 'payroll-settings/attendance-bonus', bonus)}>
        <Check label="Terapkan aturan hangus" checked={bonus.enabled} testId="ps-bonus-enabled"
          onChange={v => setBonus(b => ({ ...b, enabled: v }))} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="space-y-2">
            <Check label="Hangus bila alpa" checked={bonus.forfeit_if_alpa} onChange={v => setBonus(b => ({ ...b, forfeit_if_alpa: v }))} />
            <Isian label="Alpa yang masih boleh (hari)"><Input type="number" min="0" step="0.5" value={bonus.max_alpa_days} onChange={num(setBonus, 'max_alpa_days')} /></Isian>
          </div>
          <div className="space-y-2">
            <Check label="Hangus bila izin/sakit tanpa surat" checked={bonus.forfeit_if_izin_no_note} onChange={v => setBonus(b => ({ ...b, forfeit_if_izin_no_note: v }))} />
            <Isian label="Yang masih boleh (hari)"><Input type="number" min="0" value={bonus.max_izin_no_note_days} onChange={num(setBonus, 'max_izin_no_note_days')} /></Isian>
          </div>
          <div className="space-y-2">
            <Check label="Hangus bila terlambat" checked={bonus.forfeit_if_late} onChange={v => setBonus(b => ({ ...b, forfeit_if_late: v }))} />
            <Isian label="Hari terlambat yang masih boleh"><Input type="number" min="0" value={bonus.max_late_days_allowed} onChange={num(setBonus, 'max_late_days_allowed')} /></Isian>
          </div>
          <Isian label="Batas total menit terlambat" petunjuk="0 = aturan menit tidak dipakai"><Input type="number" min="0" value={bonus.late_minutes_limit} onChange={num(setBonus, 'late_minutes_limit')} /></Isian>
          <Isian label="Minimal hari hadir"><Input type="number" min="0" value={bonus.min_days_present} onChange={num(setBonus, 'min_days_present')} /></Isian>
        </div>
        <Isian label="Tunjangan yang dihitung sebagai bonus kehadiran" petunjuk='Tidak ada yang dipilih = tunjangan yang namanya memuat kata "kehadiran".'>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {allowanceList.map(a => (
              <Check key={a.allowance_id} label={`${a.name} (${rp(a.amount)})`} testId={`ps-bonus-al-${a.allowance_id}`}
                checked={(bonus.allowance_ids || []).includes(a.allowance_id)} onChange={v => toggleAllowance(a.allowance_id, v)} />
            ))}
            {allowanceList.length === 0 && <span className="text-sm text-muted-foreground">Buat tunjangan aktif dulu di tab Tunjangan.</span>}
          </div>
        </Isian>
      </FormPopup>

      {/* ── KETERLAMBATAN ────────────────────────────────────────────────── */}
      <FormPopup open={edit === 'late'} onClose={tutup} ukuran="pendek" judul={SEKSI_JUDUL.late} testId="ps-late-form"
        keterangan="Selama tidak aktif, sistem tidak memotong keterlambatan sama sekali."
        menyimpan={saving === 'late'} galat={galat}
        onSimpan={() => save('late', 'payroll-settings/late-penalty', late)}>
        <Check label="Aktif — potong keterlambatan di slip" checked={late.enabled} testId="ps-late-enabled"
          onChange={v => setLate(l => ({ ...l, enabled: v }))} />
        <Isian label="Cara potong">
          <SmartNativeSelect value={late.mode} onChange={e => setLate(l => ({ ...l, mode: e.target.value }))} searchable={false} data-testid="ps-late-mode">
            <option value="per_minute">Per menit</option><option value="per_occurrence">Per kejadian</option><option value="tiered">Bertingkat</option>
          </SmartNativeSelect>
        </Isian>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Rp per menit"><MoneyInput value={late.amount_per_minute} onChange={num(setLate, 'amount_per_minute')} /></Isian>
          <Isian label="Rp per kejadian"><MoneyInput value={late.amount_per_occurrence} onChange={num(setLate, 'amount_per_occurrence')} /></Isian>
        </div>
        {late.mode === 'tiered' && (
          <Isian label="Tingkatan">
            <div className="space-y-2">
              {late.tiers.map((t, i) => {
                const onTier = (k) => e => setLate(l => ({ ...l, tiers: l.tiers.map((x, j) => j === i ? { ...x, [k]: e.target.value === '' ? null : Number(e.target.value) } : x) }));
                return (
                  <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">
                    <Isian label="Dari menit"><Input type="number" min="0" value={t.from_minutes ?? ''} onChange={onTier('from_minutes')} /></Isian>
                    <Isian label="Sampai menit"><Input type="number" min="0" value={t.to_minutes ?? ''} onChange={onTier('to_minutes')} placeholder="tanpa batas" /></Isian>
                    {/* menit tetap input angka; hanya kolom Rp yang MoneyInput (No.45) */}
                    <Isian label="Rp"><MoneyInput value={t.amount ?? ''} onChange={onTier('amount')} /></Isian>
                    <Button type="button" variant="ghost" size="icon" title="Hapus tingkat" aria-label="Hapus tingkat"
                      onClick={() => setLate(l => ({ ...l, tiers: l.tiers.filter((_, j) => j !== i) }))}><Trash2 /></Button>
                  </div>
                );
              })}
              <Button type="button" variant="outline" size="sm" onClick={() => setLate(l => ({ ...l, tiers: [...l.tiers, { from_minutes: 0, to_minutes: null, amount: 0 }] }))}>
                <Plus />Tambah tingkat
              </Button>
            </div>
          </Isian>
        )}
      </FormPopup>

      {/* ── KASBON ───────────────────────────────────────────────────────── */}
      <FormPopup open={edit === 'kasbon'} onClose={tutup} ukuran="pendek" judul={SEKSI_JUDUL.kasbon} testId="ps-kasbon-form"
        keterangan="0 = tanpa batas (bawaan sampai owner mengisi). Dicek saat pengajuan dan saat HR menyetujui."
        menyimpan={saving === 'kasbon'} galat={galat}
        onSimpan={() => save('kasbon', 'payroll-settings/kasbon', kasbon)}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Maks % gaji pokok" petunjuk="Gaji pokok = Profil Gaji bulanan aktif"><Input type="number" min="0" value={kasbon.max_pct_of_base_salary} onChange={num(setKasbon, 'max_pct_of_base_salary')} data-testid="ps-kasbon-pct" /></Isian>
          <Isian label="Maks jumlah cicilan"><Input type="number" min="0" value={kasbon.max_installments} onChange={num(setKasbon, 'max_installments')} data-testid="ps-kasbon-inst" /></Isian>
        </div>
      </FormPopup>
    </PageLayout>
  );
}
