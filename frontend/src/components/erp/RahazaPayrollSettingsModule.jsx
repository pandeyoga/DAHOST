/**
 * RahazaPayrollSettingsModule — tab "Pengaturan Payroll" di hub Penggajian.
 *
 * 2026-11-02 (keputusan owner K22/K23/K24/K25): SATU layar untuk SELURUH koleksi `rahaza_payroll_settings`
 * (API `GET/PUT /api/rahaza/payroll-settings/*`). Tidak membuat koleksi/layar pengaturan baru:
 *   - Keterlambatan & Bonus Kehadiran (kunci late_penalty / attendance_bonus)
 *   - BPJS: tarif & plafon per program, kelas risiko JKK, saklar jurnal iuran perusahaan (hanya owner)
 *   - Lembur: aturan cadangan 1/173 × upah tetap, tingkatan hari kerja & hari istirahat
 *   - Kasbon: batas % gaji pokok & maks cicilan (0 = tanpa batas)
 * 2026-11-06 (Tahap 2): + Kalender kerja (hari kerja per minggu, bawaan 6), PPh21 (TER A/B/C, PTKP, tarif
 *   progresif — bisa diubah HR/Keuangan), aturan hangus bonus kehadiran per jenis, tingkatan lembur hari libur.
 *   Layar memakai cetakan PageLayout (PANDUAN_UI G1).
 * Kepesertaan BPJS per karyawan diatur di Data Karyawan (tab Pajak & BPJS), tarif lembur per orang di Profil Gaji.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Save, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { MoneyInput } from '@/components/ui/money-input';
import PageLayout from './layout/PageLayout';

const API = process.env.REACT_APP_BACKEND_URL || '';
const inputCls = 'h-8 w-full px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm';

const RATE_FIELDS = [
  ['kes_emp', 'Kesehatan — karyawan'], ['kes_comp', 'Kesehatan — perusahaan'],
  ['jht_emp', 'JHT — karyawan'], ['jht_comp', 'JHT — perusahaan'],
  ['jp_emp', 'JP — karyawan'], ['jp_comp', 'JP — perusahaan'], ['jkm_comp', 'JKM — perusahaan'],
];
const JKK_TIERS = [['very_low', 'Sangat rendah'], ['low', 'Rendah'], ['medium', 'Sedang'], ['high', 'Tinggi'], ['very_high', 'Sangat tinggi']];
const PTKP_CODES = ['TK/0', 'TK/1', 'TK/2', 'TK/3', 'K/0', 'K/1', 'K/2', 'K/3'];
const TER_CATS = ['A', 'B', 'C'];
const WORK_WEEK_OPTIONS = [[6, '6 hari (Senin–Sabtu)'], [5, '5 hari (Senin–Jumat)'], [7, '7 hari']];

const pct = (v) => Math.round(Number(v || 0) * 100000) / 1000;   // 0.037 → 3.7
const unpct = (v) => Number(v || 0) / 100;
const rp = (v) => `Rp ${Number(v || 0).toLocaleString('id-ID')}`;

async function errDetail(r, fallback) {
  try { const d = await r.json(); return (typeof d.detail === 'string' ? d.detail : d.detail?.message) || fallback; }
  catch { return fallback; }
}

function Row({ label, children, hint }) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] uppercase text-muted-foreground font-semibold">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-muted-foreground">{hint}</span>}
    </label>
  );
}

function Check({ label, checked, onChange, disabled, testId }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={!!checked} disabled={disabled} onChange={e => onChange(e.target.checked)} data-testid={testId} />
      <span>{label}</span>
    </label>
  );
}

function Section({ title, note, onSave, saving, testId, children, extra }) {
  return (
    <GlassCard className="p-4 space-y-3" data-testid={testId}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-sm">{title}</p>
          {note && <p className="text-xs text-muted-foreground mt-0.5">{note}</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {extra}
          <Button size="sm" onClick={onSave} disabled={saving} data-testid={`${testId}-save`}>
            <Save className="w-3.5 h-3.5 mr-1" /> {saving ? 'Menyimpan…' : 'Simpan'}
          </Button>
        </div>
      </div>
      {children}
    </GlassCard>
  );
}

/* Tabel tarif [batas atas | tarif %]; baris terakhir tanpa batas atas (= selebihnya). */
function RateTable({ rows, onChange, testId, boundLabel = 'Penghasilan bruto sampai (Rp)' }) {
  const setRow = (i, k, v) => onChange(rows.map((r, j) => (j === i ? (k === 0 ? [v, r[1]] : [r[0], v]) : r)));
  return (
    <Table data-testid={testId}>
      <TableHeader>
        <TableRow><TableHead>No</TableHead><TableHead>{boundLabel}</TableHead><TableHead className="text-right">Tarif (%)</TableHead></TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r, i) => (
          <TableRow key={i}>
            <TableCell className="tabular-nums">{i + 1}</TableCell>
            <TableCell>
              {i === rows.length - 1
                ? <span className="text-xs text-muted-foreground">selebihnya</span>
                : <MoneyInput unstyled className={inputCls} value={r[0] ?? 0} onChange={e => setRow(i, 0, Number(e.target.value))} />}
            </TableCell>
            <TableCell className="text-right">
              <input type="number" step="0.01" min="0" className={`${inputCls} text-right`} value={pct(r[1])}
                onChange={e => setRow(i, 1, unpct(e.target.value))} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

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

  const load = useCallback(async () => {
    const r = await fetch(`${API}/api/rahaza/payroll-settings`, { headers });
    if (!r.ok) { toast.error(await errDetail(r, `Gagal memuat pengaturan (HTTP ${r.status})`)); return; }
    const d = await r.json();
    setData(d);
    setLate({ ...d.late_penalty, tiers: d.late_penalty?.tiers || [] });
    setBonus({ ...d.attendance_bonus, allowance_ids: d.attendance_bonus?.allowance_ids || [] });
    setBpjs({ ...d.bpjs, rates: { ...(d.bpjs?.rates || {}) }, ceilings: { ...(d.bpjs?.ceilings || {}) },
              jkk_rates: { ...(d.bpjs?.jkk_rates || {}) } });
    setOt({ ...d.overtime });
    setKasbon({ ...d.kasbon });
    setCal({ ...d.work_calendar });
    setPph(d.pph21 ? { ...d.pph21, ptkp: { ...d.pph21.ptkp }, ter: { ...d.pph21.ter }, brackets: [...(d.pph21.brackets || [])] } : null);
    const ra = await fetch(`${API}/api/rahaza/payroll-allowances`, { headers }).catch(() => null);
    if (ra && ra.ok) setAllowanceList(((await ra.json()).allowances || []).filter(a => a.is_active !== false));
  }, [headers]);
  useEffect(() => { load(); }, [load]);

  const save = async (key, path, body) => {
    setSaving(key);
    try {
      const r = await fetch(`${API}/api/rahaza/${path}`, { method: 'PUT', headers, body: JSON.stringify(body) });
      if (!r.ok) throw new Error(await errDetail(r, `HTTP ${r.status}`));
      toast.success('Pengaturan tersimpan.');
      await load();
    } catch (e) { toast.error(`Gagal menyimpan: ${e.message}`); }
    finally { setSaving(''); }
  };

  const resetPph = async () => {
    const ok = await confirmDialog({ title: 'Kembalikan PPh21 ke bawaan peraturan?',
      body: 'PTKP, tarif progresif, dan tabel TER kembali ke PMK 101/2016, UU HPP, dan PP 58/2023.', confirmLabel: 'Kembalikan' });
    if (ok) save('pph', 'payroll-settings/pph21', { reset: true });
  };

  const tools = (
    <Button variant="outline" size="icon" onClick={load} title="Muat ulang" aria-label="Muat ulang" data-testid="ps-reload">
      <RefreshCw className="w-4 h-4" />
    </Button>
  );

  if (!data || !late || !bpjs || !ot || !kasbon || !bonus || !cal) {
    return (
      <PageLayout title="Pengaturan Payroll" subtitle="Aturan payroll: hari kerja, PPh21, BPJS, lembur, kehadiran, dan kasbon." tools={tools}>
        <div className="flex items-center justify-center h-40"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" /></div>
      </PageLayout>
    );
  }
  const canToggle = !!data.can_toggle_bpjs_journal;
  const num = (setter, k) => (e) => setter(s => ({ ...s, [k]: e.target.value === '' ? '' : Number(e.target.value) }));
  const toggleAllowance = (id, on) => setBonus(b => ({
    ...b, allowance_ids: on ? [...new Set([...(b.allowance_ids || []), id])] : (b.allowance_ids || []).filter(x => x !== id),
  }));

  return (
    <PageLayout title="Pengaturan Payroll" testId="payroll-settings-page"
      subtitle="Aturan payroll: hari kerja, PPh21, BPJS, lembur, kehadiran, dan kasbon." tools={tools}>

      {/* ── KALENDER KERJA (Tahap 2) ─────────────────────────────────────── */}
      <Section title="Kalender kerja" testId="ps-calendar" saving={saving === 'cal'}
        note="Pembagi gaji harian = hari kerja aktif periode: hari kerja per minggu dikurangi hari libur di Kalender Produksi."
        onSave={() => save('cal', 'payroll-settings/work-calendar', { work_days_per_week: Number(cal.work_days_per_week) })}>
        <div className="max-w-xs">
          <Row label="Hari kerja per minggu">
            <SmartNativeSelect className={inputCls} value={String(cal.work_days_per_week || 6)} data-testid="ps-cal-days"
              onChange={e => setCal(c => ({ ...c, work_days_per_week: Number(e.target.value) }))}>
              {WORK_WEEK_OPTIONS.map(([v, l]) => <option key={v} value={String(v)}>{l}</option>)}
            </SmartNativeSelect>
          </Row>
        </div>
      </Section>

      {/* ── PPh21 (Tahap 2) ─────────────────────────────────────────────── */}
      {pph && (
        <Section title="PPh21 — metode TER" testId="ps-pph21" saving={saving === 'pph'}
          note="TER bulanan setiap bulan, dihitung ulang setahun di Desember (atau bulan terakhir bekerja). Bawaan: PP 58/2023, PMK 168/2023, UU HPP, PMK 101/2016."
          extra={<Button variant="outline" size="sm" onClick={resetPph} data-testid="ps-pph21-reset">Bawaan peraturan</Button>}
          onSave={() => save('pph', 'payroll-settings/pph21', {
            enabled: !!pph.enabled, december_true_up: !!pph.december_true_up,
            employer_premiums_taxable: !!pph.employer_premiums_taxable,
            no_npwp_surcharge_enabled: !!pph.no_npwp_surcharge_enabled, no_npwp_surcharge_rate: pph.no_npwp_surcharge_rate,
            biaya_jabatan_rate: pph.biaya_jabatan_rate, biaya_jabatan_max_month: pph.biaya_jabatan_max_month,
            ptkp: pph.ptkp, brackets: pph.brackets, ter: pph.ter, ter_category: pph.ter_category,
          })}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            <Check label="Potong PPh21 di slip gaji" checked={pph.enabled} testId="ps-pph21-enabled"
              onChange={v => setPph(p => ({ ...p, enabled: v }))} />
            <Check label="Hitung ulang setahun di Desember / bulan terakhir bekerja" checked={pph.december_true_up}
              onChange={v => setPph(p => ({ ...p, december_true_up: v }))} />
            <Check label="Premi JKK, JKM, BPJS Kesehatan dari perusahaan masuk penghasilan bruto" checked={pph.employer_premiums_taxable}
              onChange={v => setPph(p => ({ ...p, employer_premiums_taxable: v }))} />
            <Check label="Tambahan bagi karyawan tanpa NPWP/NIK" checked={pph.no_npwp_surcharge_enabled} testId="ps-pph21-surcharge"
              onChange={v => setPph(p => ({ ...p, no_npwp_surcharge_enabled: v }))} />
          </div>
          <p className="text-xs text-muted-foreground">
            Sejak 2024 NIK 16 digit berlaku sebagai NPWP, jadi tambahan tanpa NPWP bawaannya mati. Iuran JHT &amp; JP karyawan
            mengurangi penghasilan setahun; iuran BPJS Kesehatan karyawan tidak.
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Row label="Tambahan tanpa NPWP (%)">
              <input type="number" step="1" min="0" className={inputCls} value={pct(pph.no_npwp_surcharge_rate)}
                onChange={e => setPph(p => ({ ...p, no_npwp_surcharge_rate: unpct(e.target.value) }))} />
            </Row>
            <Row label="Biaya jabatan (%)">
              <input type="number" step="0.5" min="0" className={inputCls} value={pct(pph.biaya_jabatan_rate)}
                onChange={e => setPph(p => ({ ...p, biaya_jabatan_rate: unpct(e.target.value) }))} />
            </Row>
            <Row label="Biaya jabatan maks per bulan (Rp)">
              <MoneyInput unstyled className={inputCls} value={pph.biaya_jabatan_max_month}
                onChange={e => setPph(p => ({ ...p, biaya_jabatan_max_month: Number(e.target.value) }))} />
            </Row>
          </div>
          <div>
            <p className="text-xs font-semibold mb-2">PTKP setahun dan kategori TER</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {PTKP_CODES.map(code => (
                <Row key={code} label={`${code} — kategori ${pph.ter_category?.[code] || 'A'}`}>
                  <MoneyInput unstyled className={inputCls} value={pph.ptkp?.[code] ?? 0} data-testid={`ps-ptkp-${code}`}
                    onChange={e => setPph(p => ({ ...p, ptkp: { ...p.ptkp, [code]: Number(e.target.value) } }))} />
                </Row>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold mb-2">Tarif progresif setahun (perhitungan Desember)</p>
              <RateTable rows={pph.brackets || []} boundLabel="Penghasilan kena pajak sampai (Rp)" testId="ps-pph21-brackets"
                onChange={rows => setPph(p => ({ ...p, brackets: rows }))} />
            </div>
            <div>
              <div className="flex items-center justify-between gap-2 mb-2">
                <p className="text-xs font-semibold">Tabel TER bulanan</p>
                <SmartNativeSelect className={`${inputCls} w-40`} value={terCat} onChange={e => setTerCat(e.target.value)} data-testid="ps-ter-cat">
                  {TER_CATS.map(c => <option key={c} value={c}>Kategori {c}</option>)}
                </SmartNativeSelect>
              </div>
              <RateTable rows={pph.ter?.[terCat] || []} testId="ps-pph21-ter"
                onChange={rows => setPph(p => ({ ...p, ter: { ...p.ter, [terCat]: rows } }))} />
            </div>
          </div>
        </Section>
      )}

      {/* ── BPJS ─────────────────────────────────────────────────────────── */}
      <Section title="BPJS — tarif, plafon, kelas risiko JKK" testId="ps-bpjs" saving={saving === 'bpjs'}
        note="Potongan hanya untuk program yang dicentang di Data Karyawan. Berlaku untuk semua skema gaji, dihitung per bulan."
        onSave={() => save('bpjs', 'payroll-settings/bpjs', {
          rates: Object.fromEntries(RATE_FIELDS.map(([k]) => [k, unpct(pct(bpjs.rates[k]))])),
          ceilings: bpjs.ceilings, jkk_rates: bpjs.jkk_rates, jkk_risk_tier: bpjs.jkk_risk_tier,
          employer_contribution_journal: !!bpjs.employer_contribution_journal,
        })}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {RATE_FIELDS.map(([k, label]) => (
            <Row key={k} label={`${label} (%)`}>
              <input type="number" step="0.01" min="0" className={inputCls} value={pct(bpjs.rates[k])}
                onChange={e => setBpjs(b => ({ ...b, rates: { ...b.rates, [k]: unpct(e.target.value) } }))}
                data-testid={`ps-bpjs-rate-${k}`} />
            </Row>
          ))}
          <Row label="Plafon Kesehatan (Rp)">
            <MoneyInput unstyled className={inputCls} value={bpjs.ceilings.kes}
              onChange={e => setBpjs(b => ({ ...b, ceilings: { ...b.ceilings, kes: Number(e.target.value) } }))} />
          </Row>
          <Row label="Plafon JP (Rp)">
            <MoneyInput unstyled className={inputCls} value={bpjs.ceilings.jp}
              onChange={e => setBpjs(b => ({ ...b, ceilings: { ...b.ceilings, jp: Number(e.target.value) } }))} />
          </Row>
          <Row label="Kelas risiko JKK" hint={`Tarif: ${pct(bpjs.jkk_rates[bpjs.jkk_risk_tier])}% (cek sertifikat kepesertaan)`}>
            <SmartNativeSelect className={inputCls} value={bpjs.jkk_risk_tier} data-testid="ps-bpjs-jkk"
              onChange={e => setBpjs(b => ({ ...b, jkk_risk_tier: e.target.value }))}>
              {JKK_TIERS.map(([k, l]) => <option key={k} value={k}>{l} — {pct(bpjs.jkk_rates[k])}%</option>)}
            </SmartNativeSelect>
          </Row>
        </div>
        <label className="flex items-start gap-2 text-sm rounded-lg border border-[var(--glass-border)] p-3">
          <input type="checkbox" className="mt-1" disabled={!canToggle} checked={!!bpjs.employer_contribution_journal}
            onChange={e => setBpjs(b => ({ ...b, employer_contribution_journal: e.target.checked }))} data-testid="ps-bpjs-journal" />
          <span>
            <strong>Jurnal iuran BPJS perusahaan</strong> saat finalisasi gaji: Dr 6-3200 / 6-3300 · Cr 2-1501 / 2-1502.
            <span className="block text-xs text-muted-foreground">
              Bawaan mati. {canToggle ? 'Anda (owner) dapat menyalakannya.' : 'Hanya owner yang dapat mengubah saklar ini.'}{' '}
              Iuran perusahaan tetap dihitung dan tampil di slip walau saklar mati.
            </span>
          </span>
        </label>
      </Section>

      {/* ── LEMBUR ───────────────────────────────────────────────────────── */}
      <Section title="Lembur — pengali per hari" testId="ps-overtime" saving={saving === 'ot'}
        note="Dibayar hanya bila ada pengajuan disetujui atau HR menandai lembur hari itu dibayar. Pengali dari sini, bukan pilihan pemohon (PP 35/2021)."
        onSave={() => save('ot', 'payroll-settings/overtime', ot)}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Row label="Upah sejam bila tarif Profil Gaji 0">
            <SmartNativeSelect className={inputCls} value={ot.basis} onChange={e => setOt(o => ({ ...o, basis: e.target.value }))} data-testid="ps-ot-basis">
              <option value="upah_tetap_div_173">Upah tetap ÷ pembagi</option>
              <option value="manual">Tanpa cadangan (hanya peringatan)</option>
            </SmartNativeSelect>
          </Row>
          <Row label="Pembagi" hint="Permenaker: 173 jam/bulan"><input type="number" min="1" className={inputCls} value={ot.divisor} onChange={num(setOt, 'divisor')} /></Row>
          <Row label="Hari kerja: pengali jam ke-1"><input type="number" step="0.1" min="1" className={inputCls} value={ot.first_hour_multiplier} onChange={num(setOt, 'first_hour_multiplier')} /></Row>
          <Row label="Hari kerja: jam berikutnya"><input type="number" step="0.1" min="1" className={inputCls} value={ot.next_hours_multiplier} onChange={num(setOt, 'next_hours_multiplier')} /></Row>
          <Row label="Hari libur: jam awal (6 hari kerja)" hint="Jam ke-1 s.d. ini memakai pengali awal"><input type="number" min="1" className={inputCls} value={ot.rest_day_first_hours_6d} onChange={num(setOt, 'rest_day_first_hours_6d')} /></Row>
          <Row label="Hari libur: jam awal (5 hari kerja)"><input type="number" min="1" className={inputCls} value={ot.rest_day_first_hours_5d} onChange={num(setOt, 'rest_day_first_hours_5d')} /></Row>
          <Row label="Hari libur: pengali awal"><input type="number" step="0.1" min="1" className={inputCls} value={ot.rest_day_first_multiplier} onChange={num(setOt, 'rest_day_first_multiplier')} /></Row>
          <Row label="Hari libur: jam sesudahnya / selanjutnya" hint="Satu jam berikutnya, lalu jam-jam selanjutnya">
            <div className="flex gap-2">
              <input type="number" step="0.1" min="1" className={inputCls} value={ot.rest_day_next_hour_multiplier} onChange={num(setOt, 'rest_day_next_hour_multiplier')} />
              <input type="number" step="0.1" min="1" className={inputCls} value={ot.rest_day_after_multiplier} onChange={num(setOt, 'rest_day_after_multiplier')} />
            </div>
          </Row>
        </div>
      </Section>

      {/* ── BONUS KEHADIRAN ──────────────────────────────────────────────── */}
      <Section title="Bonus kehadiran — kapan hangus" testId="ps-bonus" saving={saving === 'bonus'}
        note="Bonus dibayar lewat template Tunjangan yang dipilih di bawah. Bonus hangus bila salah satu aturan aktif terlampaui, dan selalu hangus bila tidak ada hari hadir."
        onSave={() => save('bonus', 'payroll-settings/attendance-bonus', bonus)}>
        <Check label="Terapkan aturan hangus" checked={bonus.enabled} testId="ps-bonus-enabled"
          onChange={v => setBonus(b => ({ ...b, enabled: v }))} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="space-y-1">
            <Check label="Hangus bila alpa" checked={bonus.forfeit_if_alpa} onChange={v => setBonus(b => ({ ...b, forfeit_if_alpa: v }))} />
            <Row label="Alpa yang masih boleh (hari)"><input type="number" min="0" step="0.5" className={inputCls} value={bonus.max_alpa_days} onChange={num(setBonus, 'max_alpa_days')} /></Row>
          </div>
          <div className="space-y-1">
            <Check label="Hangus bila izin/sakit tanpa surat" checked={bonus.forfeit_if_izin_no_note} onChange={v => setBonus(b => ({ ...b, forfeit_if_izin_no_note: v }))} />
            <Row label="Yang masih boleh (hari)"><input type="number" min="0" className={inputCls} value={bonus.max_izin_no_note_days} onChange={num(setBonus, 'max_izin_no_note_days')} /></Row>
          </div>
          <div className="space-y-1">
            <Check label="Hangus bila terlambat" checked={bonus.forfeit_if_late} onChange={v => setBonus(b => ({ ...b, forfeit_if_late: v }))} />
            <Row label="Hari terlambat yang masih boleh"><input type="number" min="0" className={inputCls} value={bonus.max_late_days_allowed} onChange={num(setBonus, 'max_late_days_allowed')} /></Row>
          </div>
          <Row label="Batas total menit terlambat" hint="0 = aturan menit tidak dipakai"><input type="number" min="0" className={inputCls} value={bonus.late_minutes_limit} onChange={num(setBonus, 'late_minutes_limit')} /></Row>
          <Row label="Minimal hari hadir"><input type="number" min="0" className={inputCls} value={bonus.min_days_present} onChange={num(setBonus, 'min_days_present')} /></Row>
        </div>
        <div>
          <p className="text-xs font-semibold mb-1">Tunjangan yang dihitung sebagai bonus kehadiran</p>
          <p className="text-[11px] text-muted-foreground mb-2">Tidak ada yang dipilih = tunjangan yang namanya memuat kata &quot;kehadiran&quot;.</p>
          <div className="flex flex-wrap gap-4">
            {allowanceList.map(a => (
              <Check key={a.allowance_id} label={`${a.name} (${rp(a.amount)})`} testId={`ps-bonus-al-${a.allowance_id}`}
                checked={(bonus.allowance_ids || []).includes(a.allowance_id)} onChange={v => toggleAllowance(a.allowance_id, v)} />
            ))}
          </div>
        </div>
      </Section>

      {/* ── KETERLAMBATAN ────────────────────────────────────────────────── */}
      <Section title="Potongan keterlambatan" testId="ps-late" saving={saving === 'late'}
        note="Selama tidak aktif, sistem tidak memotong keterlambatan sama sekali."
        onSave={() => save('late', 'payroll-settings/late-penalty', late)}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Row label="Aktif"><input type="checkbox" checked={!!late.enabled} onChange={e => setLate(l => ({ ...l, enabled: e.target.checked }))} /></Row>
          <Row label="Cara potong">
            <SmartNativeSelect className={inputCls} value={late.mode} onChange={e => setLate(l => ({ ...l, mode: e.target.value }))}>
              <option value="per_minute">Per menit</option><option value="per_occurrence">Per kejadian</option><option value="tiered">Bertingkat</option>
            </SmartNativeSelect>
          </Row>
          <Row label="Rp per menit"><MoneyInput unstyled className={inputCls} value={late.amount_per_minute} onChange={num(setLate, 'amount_per_minute')} /></Row>
          <Row label="Rp per kejadian"><MoneyInput unstyled className={inputCls} value={late.amount_per_occurrence} onChange={num(setLate, 'amount_per_occurrence')} /></Row>
        </div>
        {late.mode === 'tiered' && (
          <div className="space-y-2">
            {late.tiers.map((t, i) => (
              <div key={i} className="grid grid-cols-4 gap-2 items-end">
                {['from_minutes', 'to_minutes', 'amount'].map(k => {
                  const onTier = e => setLate(l => ({ ...l, tiers: l.tiers.map((x, j) => j === i ? { ...x, [k]: e.target.value === '' ? null : Number(e.target.value) } : x) }));
                  return (
                    <Row key={k} label={{ from_minutes: 'Dari menit', to_minutes: 'Sampai menit (kosong = ∞)', amount: 'Rp' }[k]}>
                      {/* menit tetap input angka; hanya kolom Rp yang MoneyInput (No.45) */}
                      {k === 'amount'
                        ? <MoneyInput unstyled className={inputCls} value={t[k] ?? ''} onChange={onTier} />
                        : <input type="number" min="0" className={inputCls} value={t[k] ?? ''} onChange={onTier} />}
                    </Row>
                  );
                })}
                <Button variant="outline" size="sm" onClick={() => setLate(l => ({ ...l, tiers: l.tiers.filter((_, j) => j !== i) }))}>Hapus</Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setLate(l => ({ ...l, tiers: [...l.tiers, { from_minutes: 0, to_minutes: null, amount: 0 }] }))}>Tambah tingkat</Button>
          </div>
        )}
      </Section>

      {/* ── KASBON ───────────────────────────────────────────────────────── */}
      <Section title="Batas kasbon & pinjaman" testId="ps-kasbon" saving={saving === 'kasbon'}
        note="0 = tanpa batas (bawaan sampai owner mengisi). Dicek saat pengajuan dan saat HR menyetujui."
        onSave={() => save('kasbon', 'payroll-settings/kasbon', kasbon)}>
        <div className="grid grid-cols-2 gap-3 max-w-lg">
          <Row label="Maks % gaji pokok" hint="Gaji pokok = Profil Gaji bulanan aktif"><input type="number" min="0" className={inputCls} value={kasbon.max_pct_of_base_salary} onChange={num(setKasbon, 'max_pct_of_base_salary')} data-testid="ps-kasbon-pct" /></Row>
          <Row label="Maks jumlah cicilan"><input type="number" min="0" className={inputCls} value={kasbon.max_installments} onChange={num(setKasbon, 'max_installments')} data-testid="ps-kasbon-inst" /></Row>
        </div>
      </Section>
    </PageLayout>
  );
}
