/**
 * AqlSamplingTool — alat "Hitung sampel AQL" (ANSI/ASQ Z1.4, sampel tunggal, inspeksi normal).
 *
 * Tahap 9 (keputusan owner 11, 7 Nov 2026): kalkulator AQL PINDAH ke Terima & QC — dipakai saat
 * memeriksa barang yang datang dari CMT, bukan dari menu Analitik Produksi. Komponen ini satu-satunya
 * tampilan kalkulatornya: dipakai di dalam layar Terima & QC (panel di halaman) dan oleh
 * `RahazaAQLCalculatorModule` (tautan lama `prod-aql-calculator`).
 *
 * Backend: POST /api/rahaza/aql/calculate (routes/rahaza_aql.py) — rumus tidak dihitung di layar.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { GlassInput } from '@/components/ui/glass';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Notice, StatTile } from '../moduleAtoms';
import { apiPost } from '../../../lib/api';

export const AQL_OPTIONS = [
  { value: '0.65', label: 'AQL 0,65 — sangat ketat (produk premium)' },
  { value: '1', label: 'AQL 1,0 — ketat (ekspor)' },
  { value: '1.5', label: 'AQL 1,5 — ketat-sedang' },
  { value: '2.5', label: 'AQL 2,5 — standar garmen (paling umum)' },
  { value: '4', label: 'AQL 4,0 — longgar (pasar lokal)' },
  { value: '6.5', label: 'AQL 6,5 — sangat longgar' },
  { value: '10', label: 'AQL 10 — pemeriksaan cepat' },
];
export const LEVEL_OPTIONS = [
  { value: 'I', label: 'Tingkat I — longgar' },
  { value: 'II', label: 'Tingkat II — umum' },
  { value: 'III', label: 'Tingkat III — ketat' },
];
const fmtNum = (n) => Number(n || 0).toLocaleString('id-ID');

/** Keputusan dari jumlah cacat yang ditemukan pada sampel (fungsi murni, diuji di frontend). */
export function aqlDecision(result, defects) {
  if (!result || result.error || defects === '' || defects === null || defects === undefined) return null;
  const d = Number(defects);
  if (!Number.isFinite(d) || d < 0) return null;
  if (d <= Number(result.accept_number)) return { tone: 'success', text: 'Lulus — terima seluruh kiriman.' };
  if (d >= Number(result.reject_number)) return { tone: 'danger', text: 'Gagal — periksa 100% atau kembalikan ke CMT.' };
  return { tone: 'warning', text: 'Di antara batas — ambil sampel ulang satu kali.' };
}

export default function AqlSamplingTool({ initialLot, contextLabel, testId = 'aql-tool' }) {
  const [lotSize, setLotSize] = useState(String(initialLot && initialLot >= 2 ? initialLot : 500));
  const [aql, setAql] = useState('2.5');
  const [level, setLevel] = useState('II');
  const [result, setResult] = useState(null);
  const [defects, setDefects] = useState('');

  useEffect(() => { if (initialLot && initialLot >= 2) setLotSize(String(initialLot)); }, [initialLot]);

  const calculate = useCallback(async () => {
    const lot = parseInt(lotSize, 10);
    if (!lot || lot < 2) { setResult({ error: 'Jumlah barang minimal 2 pcs.' }); return; }
    try {
      setResult(await apiPost('/rahaza/aql/calculate', { lot_size: lot, aql: parseFloat(aql), inspection_level: level }));
    } catch (e) {
      setResult({ error: e.message || 'Gagal menghitung sampel' });
    }
  }, [lotSize, aql, level]);
  useEffect(() => { calculate(); }, [calculate]);

  const decision = aqlDecision(result, defects);
  return (
    <div className="space-y-3" data-testid={testId}>
      {contextLabel && <p className="text-sm text-muted-foreground">{contextLabel}</p>}
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block text-sm">
          <span className="text-xs text-muted-foreground">Jumlah barang diperiksa (pcs)</span>
          <GlassInput type="number" min={2} value={lotSize} onChange={(e) => setLotSize(e.target.value)}
            className="mt-1 h-9" data-testid={`${testId}-lot`} />
        </label>
        <label className="block text-sm">
          <span className="text-xs text-muted-foreground">Batas mutu (AQL)</span>
          <SmartNativeSelect value={aql} onChange={(e) => setAql(e.target.value)} className="mt-1 h-9 w-full"
            aria-label="Batas mutu (AQL)" data-testid={`${testId}-aql`}>
            {AQL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        </label>
        <label className="block text-sm">
          <span className="text-xs text-muted-foreground">Tingkat pemeriksaan</span>
          <SmartNativeSelect value={level} onChange={(e) => setLevel(e.target.value)} className="mt-1 h-9 w-full"
            aria-label="Tingkat pemeriksaan" data-testid={`${testId}-level`}>
            {LEVEL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SmartNativeSelect>
        </label>
      </div>
      {result?.error ? (
        <Notice tone="danger" icon={AlertTriangle} testId={`${testId}-error`}>{result.error}</Notice>
      ) : result ? (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <StatTile testId={`${testId}-sample`} label="Sampel diperiksa" value={fmtNum(result.sample_size)} suffix="pcs"
              sub={`Kode huruf ${result.final_code_letter || result.code_letter}`} />
            <StatTile testId={`${testId}-accept`} label="Lulus bila cacat paling banyak" value={fmtNum(result.accept_number)}
              accent="success" suffix="pcs" />
            <StatTile testId={`${testId}-reject`} label="Gagal bila cacat sedikitnya" value={fmtNum(result.reject_number)}
              accent="danger" suffix="pcs" />
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block text-sm">
              <span className="text-xs text-muted-foreground">Cacat yang ditemukan di sampel</span>
              <GlassInput type="number" min={0} value={defects} onChange={(e) => setDefects(e.target.value)}
                placeholder="mis. 3" className="mt-1 h-9 w-40" data-testid={`${testId}-defects`} />
            </label>
            {decision && (
              <Notice tone={decision.tone} icon={decision.tone === 'success' ? CheckCircle2 : decision.tone === 'danger' ? AlertTriangle : Info}
                className="flex-1 min-w-[16rem]" testId={`${testId}-decision`}>{decision.text}</Notice>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Ambil {fmtNum(result.sample_size)} pcs secara acak dari {fmtNum(result.lot_size)} pcs. Standar ANSI/ASQ Z1.4, inspeksi normal.
          </p>
        </>
      ) : null}
    </div>
  );
}
