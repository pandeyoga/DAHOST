/**
 * RahazaPayrollSettingsModule — tab "Pengaturan Payroll" di hub Penggajian.
 *
 * 2026-11-02 (keputusan owner K22/K23/K24/K25): SATU layar untuk SELURUH koleksi `rahaza_payroll_settings`
 * (API `GET/PUT /api/rahaza/payroll-settings/*` sudah ada sejak FASE 15 tetapi tanpa UI). Tidak membuat
 * koleksi/layar pengaturan baru:
 *   - Keterlambatan & Bonus Kehadiran (kunci lama late_penalty / attendance_bonus)
 *   - BPJS: tarif & plafon per program, kelas risiko JKK, saklar jurnal iuran perusahaan (hanya owner)
 *   - Lembur: aturan cadangan bila tarif lembur Profil Gaji = 0 (1/173 × upah tetap, 1,5× lalu 2×)
 *   - Kasbon: batas % gaji pokok & maks cicilan (0 = tanpa batas)
 * Kepesertaan BPJS per karyawan diatur di Data Karyawan (tab Pajak & BPJS), tarif lembur per orang di Profil Gaji.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Settings, Save, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';
const inputCls = 'h-8 w-full px-2 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm';

const RATE_FIELDS = [
  ['kes_emp', 'Kesehatan — karyawan'], ['kes_comp', 'Kesehatan — perusahaan'],
  ['jht_emp', 'JHT — karyawan'], ['jht_comp', 'JHT — perusahaan'],
  ['jp_emp', 'JP — karyawan'], ['jp_comp', 'JP — perusahaan'], ['jkm_comp', 'JKM — perusahaan'],
];
const JKK_TIERS = [['very_low', 'Sangat rendah'], ['low', 'Rendah'], ['medium', 'Sedang'], ['high', 'Tinggi'], ['very_high', 'Sangat tinggi']];

const pct = (v) => Math.round(Number(v || 0) * 100000) / 1000;   // 0.037 → 3.7
const unpct = (v) => Number(v || 0) / 100;

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

function Section({ title, note, onSave, saving, testId, children }) {
  return (
    <GlassCard className="p-4 space-y-3" data-testid={testId}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-sm">{title}</h3>
          {note && <p className="text-xs text-muted-foreground mt-0.5">{note}</p>}
        </div>
        <Button size="sm" className="h-8 shrink-0" onClick={onSave} disabled={saving} data-testid={`${testId}-save`}>
          <Save className="w-3.5 h-3.5 mr-1" /> {saving ? 'Menyimpan…' : 'Simpan'}
        </Button>
      </div>
      {children}
    </GlassCard>
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

  const load = useCallback(async () => {
    const r = await fetch(`${API}/api/rahaza/payroll-settings`, { headers });
    if (!r.ok) { toast.error(await errDetail(r, `Gagal memuat pengaturan (HTTP ${r.status})`)); return; }
    const d = await r.json();
    setData(d);
    setLate({ ...d.late_penalty, tiers: d.late_penalty?.tiers || [] });
    setBonus({ ...d.attendance_bonus });
    setBpjs({ ...d.bpjs, rates: { ...(d.bpjs?.rates || {}) }, ceilings: { ...(d.bpjs?.ceilings || {}) },
              jkk_rates: { ...(d.bpjs?.jkk_rates || {}) } });
    setOt({ ...d.overtime });
    setKasbon({ ...d.kasbon });
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

  if (!data || !late || !bpjs || !ot || !kasbon || !bonus) {
    return <div className="flex items-center justify-center h-40"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" /></div>;
  }
  const canToggle = !!data.can_toggle_bpjs_journal;
  const num = (setter, k) => (e) => setter(s => ({ ...s, [k]: e.target.value === '' ? '' : Number(e.target.value) }));

  return (
    <div className="space-y-4" data-testid="payroll-settings-page">
      <PageHeader icon={Settings} eyebrow="Portal SDM · Penggajian" title="Pengaturan Payroll"
        subtitle="Satu tempat untuk aturan payroll: keterlambatan, bonus kehadiran, BPJS, lembur, dan batas kasbon."
        actions={<Button variant="ghost" onClick={load} className="h-9 border border-[var(--glass-border)]"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Muat ulang</Button>} />

      {/* ── BPJS ─────────────────────────────────────────────────────────── */}
      <Section title="BPJS — tarif, plafon, kelas risiko JKK" testId="ps-bpjs" saving={saving === 'bpjs'}
        note="Potongan hanya untuk program yang dicentang di Data Karyawan. Nilai bawaan = tarif sistem lama."
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
            <input type="number" min="0" className={inputCls} value={bpjs.ceilings.kes}
              onChange={e => setBpjs(b => ({ ...b, ceilings: { ...b.ceilings, kes: Number(e.target.value) } }))} />
          </Row>
          <Row label="Plafon JP (Rp)">
            <input type="number" min="0" className={inputCls} value={bpjs.ceilings.jp}
              onChange={e => setBpjs(b => ({ ...b, ceilings: { ...b.ceilings, jp: Number(e.target.value) } }))} />
          </Row>
          <Row label="Kelas risiko JKK" hint={`Tarif: ${pct(bpjs.jkk_rates[bpjs.jkk_risk_tier])}% (cek sertifikat kepesertaan)`}>
            <select className={inputCls} value={bpjs.jkk_risk_tier} data-testid="ps-bpjs-jkk"
              onChange={e => setBpjs(b => ({ ...b, jkk_risk_tier: e.target.value }))}>
              {JKK_TIERS.map(([k, l]) => <option key={k} value={k}>{l} — {pct(bpjs.jkk_rates[k])}%</option>)}
            </select>
          </Row>
        </div>
        <label className={`flex items-start gap-2 text-sm rounded-lg border p-3 ${bpjs.employer_contribution_journal ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-500/10' : 'border-[var(--glass-border)]'}`}>
          <input type="checkbox" className="mt-1" disabled={!canToggle} checked={!!bpjs.employer_contribution_journal}
            onChange={e => setBpjs(b => ({ ...b, employer_contribution_journal: e.target.checked }))} data-testid="ps-bpjs-journal" />
          <span>
            <strong>Jurnal iuran BPJS perusahaan</strong> saat finalisasi gaji: Dr 6-3200 / 6-3300 · Cr 2-1501 / 2-1502.
            <span className="block text-xs text-muted-foreground">
              Bawaan MATI. {canToggle ? 'Anda (owner) dapat menyalakannya.' : 'Hanya owner yang dapat mengubah saklar ini.'}{' '}
              Iuran perusahaan tetap dihitung & tampil di slip walau saklar mati.
            </span>
          </span>
        </label>
      </Section>

      {/* ── LEMBUR ───────────────────────────────────────────────────────── */}
      <Section title="Lembur — aturan cadangan" testId="ps-overtime" saving={saving === 'ot'}
        note="Tarif lembur per orang tetap di Profil Gaji. Aturan ini dipakai HANYA bila tarif Profil Gaji = 0 (skema bulanan)."
        onSave={() => save('ot', 'payroll-settings/overtime', ot)}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Row label="Dasar">
            <select className={inputCls} value={ot.basis} onChange={e => setOt(o => ({ ...o, basis: e.target.value }))} data-testid="ps-ot-basis">
              <option value="upah_tetap_div_173">1/pembagi × upah tetap</option>
              <option value="manual">Tanpa cadangan (hanya peringatan)</option>
            </select>
          </Row>
          <Row label="Pembagi" hint="Permenaker: 173 jam/bulan"><input type="number" min="1" className={inputCls} value={ot.divisor} onChange={num(setOt, 'divisor')} /></Row>
          <Row label="Pengali jam ke-1"><input type="number" step="0.1" min="1" className={inputCls} value={ot.first_hour_multiplier} onChange={num(setOt, 'first_hour_multiplier')} /></Row>
          <Row label="Pengali jam berikutnya"><input type="number" step="0.1" min="1" className={inputCls} value={ot.next_hours_multiplier} onChange={num(setOt, 'next_hours_multiplier')} /></Row>
        </div>
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

      {/* ── KETERLAMBATAN ────────────────────────────────────────────────── */}
      <Section title="Potongan keterlambatan" testId="ps-late" saving={saving === 'late'}
        note="Selama tidak aktif, sistem TIDAK memotong keterlambatan sama sekali."
        onSave={() => save('late', 'payroll-settings/late-penalty', late)}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Row label="Aktif"><input type="checkbox" checked={!!late.enabled} onChange={e => setLate(l => ({ ...l, enabled: e.target.checked }))} /></Row>
          <Row label="Mode">
            <select className={inputCls} value={late.mode} onChange={e => setLate(l => ({ ...l, mode: e.target.value }))}>
              <option value="per_minute">Per menit</option><option value="per_occurrence">Per kejadian</option><option value="tiered">Bertingkat</option>
            </select>
          </Row>
          <Row label="Rp per menit"><input type="number" min="0" className={inputCls} value={late.amount_per_minute} onChange={num(setLate, 'amount_per_minute')} /></Row>
          <Row label="Rp per kejadian"><input type="number" min="0" className={inputCls} value={late.amount_per_occurrence} onChange={num(setLate, 'amount_per_occurrence')} /></Row>
        </div>
        {late.mode === 'tiered' && (
          <div className="space-y-2">
            {late.tiers.map((t, i) => (
              <div key={i} className="grid grid-cols-4 gap-2 items-end">
                {['from_minutes', 'to_minutes', 'amount'].map(k => (
                  <Row key={k} label={{ from_minutes: 'Dari menit', to_minutes: 'Sampai menit (kosong = ∞)', amount: 'Rp' }[k]}>
                    <input type="number" min="0" className={inputCls} value={t[k] ?? ''}
                      onChange={e => setLate(l => ({ ...l, tiers: l.tiers.map((x, j) => j === i ? { ...x, [k]: e.target.value === '' ? null : Number(e.target.value) } : x) }))} />
                  </Row>
                ))}
                <Button variant="ghost" className="h-8 border border-[var(--glass-border)]" onClick={() => setLate(l => ({ ...l, tiers: l.tiers.filter((_, j) => j !== i) }))}>Hapus</Button>
              </div>
            ))}
            <Button variant="ghost" className="h-8 border border-[var(--glass-border)]" onClick={() => setLate(l => ({ ...l, tiers: [...l.tiers, { from_minutes: 0, to_minutes: null, amount: 0 }] }))}>+ Tingkat</Button>
          </div>
        )}
      </Section>

      {/* ── BONUS KEHADIRAN ──────────────────────────────────────────────── */}
      <Section title="Bonus kehadiran — kapan hangus" testId="ps-bonus" saving={saving === 'bonus'}
        note="Nominal bonus dibayar lewat template Tunjangan; aturan ini menentukan kapan bonus itu hangus."
        onSave={() => save('bonus', 'payroll-settings/attendance-bonus', bonus)}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <Row label="Aktif"><input type="checkbox" checked={!!bonus.enabled} onChange={e => setBonus(b => ({ ...b, enabled: e.target.checked }))} /></Row>
          <Row label="Nominal (Rp)"><input type="number" min="0" className={inputCls} value={bonus.amount} onChange={num(setBonus, 'amount')} /></Row>
          <Row label="Wajib hadir penuh"><input type="checkbox" checked={!!bonus.require_full_attendance} onChange={e => setBonus(b => ({ ...b, require_full_attendance: e.target.checked }))} /></Row>
          <Row label="Hangus bila terlambat"><input type="checkbox" checked={!!bonus.forfeit_if_late} onChange={e => setBonus(b => ({ ...b, forfeit_if_late: e.target.checked }))} /></Row>
          <Row label="Maks hari terlambat"><input type="number" min="0" className={inputCls} value={bonus.max_late_days_allowed} onChange={num(setBonus, 'max_late_days_allowed')} /></Row>
          <Row label="Min hari hadir"><input type="number" min="0" className={inputCls} value={bonus.min_days_present} onChange={num(setBonus, 'min_days_present')} /></Row>
        </div>
      </Section>
    </div>
  );
}
