/**
 * Prediksi karyawan keluar (Portal SDM › AI SDM) — perkiraan risiko resign karyawan dengan AI.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, daftar karyawan = tabel + unduh Excel/CSV (dulu kartu,
 * diam-diam hanya 20 pertama), detail risiko = DetailPopup, kartu angka StatTile, warna token (dulu hex &
 * gradien), bahasa Indonesia (High/Medium/Low Risk → risiko tinggi/sedang/rendah).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Brain, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from '../moduleAtoms';
import { DepartmentSelect } from './hrPickers';

const RISIKO = { high: { label: 'Tinggi', tone: 'danger' }, medium: { label: 'Sedang', tone: 'warning' }, low: { label: 'Rendah', tone: 'success' } };
function Risiko({ level }) {
  const r = RISIKO[level] || { label: level || '—', tone: 'default' };
  return <StatusBadge status={level} label={r.label} tone={r.tone} />;
}

export default function HRAttritionModule({ token }) {
  const [loading, setLoading] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [department, setDepartment] = useState('');
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [lihat, setLihat] = useState(null);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/attrition/dashboard`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setHistory(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat ringkasan: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const handlePredict = async () => {
    setPredicting(true);
    setResult(null);
    try {
      const url = `${process.env.REACT_APP_BACKEND_URL}/api/hr/ai/attrition/predict${department ? `?department=${encodeURIComponent(department)}` : ''}`;
      const r = await fetch(url, { method: 'POST', headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setResult(data?.data);
      toast.success('Prediksi selesai!', { icon: <Sparkles className="h-4 w-4" /> });
      fetchHistory();
    } catch (e) {
      toast.error(`Prediksi gagal: ${e.message}`);
    } finally {
      setPredicting(false);
    }
  };

  const emps = result?.analysis?.employees || [];
  const hitung = (lv) => emps.filter(e => e.risk_level === lv).length;
  const deptRows = result?.analysis?.department_summary || [];

  const kolom = [
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (e) => (
      <div><p className="font-medium text-foreground">{e.name}</p><p className="text-xs text-muted-foreground">{e.employee_id}</p></div>) },
    { kunci: 'dept', label: 'Departemen', isi: (e) => <span className="text-sm">{e.department || '—'}</span> },
    { kunci: 'skor', label: 'Skor risiko', rata: 'kanan', isi: (e) => <span className="font-semibold tabular-nums">{e.risk_score}</span> },
    { kunci: 'tingkat', label: 'Tingkat risiko', isi: (e) => <Risiko level={e.risk_level} /> },
  ];

  return (
    <PageLayout testId="hr-attrition-module" title="Prediksi karyawan keluar"
      subtitle="Perkiraan risiko resign karyawan dengan AI, beserta saran untuk mempertahankannya."
      actions={
        <Button onClick={handlePredict} disabled={predicting} data-testid="attrition-predict">
          {predicting ? <><Loader2 className="animate-spin" />Memprediksi…</> : <><Brain />Prediksi risiko</>}
        </Button>
      }
      filters={
        <div className="w-full sm:w-56">
          {/* 2026-11-07 (OR1): dari Struktur Organisasi — dulu daftar tetap berbahasa Inggris yang tidak cocok
              dengan departemen karyawan (saringan selalu kosong) */}
          <DepartmentSelect token={token} value={department} onChange={setDepartment}
            placeholder="Semua departemen" testId="attrition-department" />
        </div>
      }
      tools={<>
        <TombolUnduh namaBerkas="prediksi-karyawan-keluar" namaLembar="Risiko" baris={emps} testId="attrition-unduh"
          kolom={[
            { label: 'Karyawan', nilai: (e) => e.name }, { label: 'ID', nilai: (e) => e.employee_id },
            { label: 'Departemen', nilai: (e) => e.department || '' }, { label: 'Skor risiko', nilai: (e) => e.risk_score },
            { label: 'Tingkat risiko', nilai: (e) => RISIKO[e.risk_level]?.label || e.risk_level || '' },
            { label: 'Faktor risiko', nilai: (e) => (e.risk_factors || []).join('; ') },
            { label: 'Saran retensi', nilai: (e) => (e.retention_suggestions || []).join('; ') },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchHistory} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}
      summary={result && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Dianalisis" value={emps.length} sub={department ? `Departemen ${department}.` : 'Semua departemen.'} />
          <StatTile label="Risiko tinggi" value={hitung('high')} accent={hitung('high') ? 'danger' : 'default'} sub="Perlu perhatian segera." />
          <StatTile label="Risiko sedang" value={hitung('medium')} accent={hitung('medium') ? 'warning' : 'default'} sub="Pantau secara berkala." />
          <StatTile label="Risiko rendah" value={hitung('low')} sub="Stabil." />
        </div>
      )}>
      {!result ? (
        <EmptyState title="Belum ada prediksi"
          description={`Pilih departemen (opsional), lalu klik "Prediksi risiko".${history.length ? ` Sudah ada ${history.length} prediksi tersimpan.` : ''}`} />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[3fr_2fr]">
          <TabelData kolom={kolom} baris={emps} kunci={(e) => e.employee_id || e.name} onKlikBaris={setLihat} testId="attrition-employees"
            kosong={<EmptyState title="Tidak ada karyawan yang dianalisis" />} />
          <div className="space-y-4">
            {(result.analysis?.overall_insights || result.analysis?.priority_actions?.length > 0) && (
              <GlassCard hover={false} className="space-y-3 p-4">
                <p className="text-base font-semibold text-foreground">Wawasan & langkah prioritas</p>
                {result.analysis?.overall_insights && <p className="text-sm leading-relaxed text-muted-foreground">{result.analysis.overall_insights}</p>}
                {result.analysis?.priority_actions?.length > 0 && (
                  <ol className="list-decimal space-y-1 pl-5 text-sm text-foreground">
                    {result.analysis.priority_actions.map((pa, i) => <li key={i}>{pa}</li>)}
                  </ol>
                )}
              </GlassCard>
            )}
            {deptRows.length > 0 && (
              <section className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-base font-semibold text-foreground">Per departemen</p>
                  <TombolUnduh namaBerkas="risiko-per-departemen" namaLembar="Per departemen" baris={deptRows}
                    kolom={[{ label: 'Departemen', nilai: (d) => d.department }, { label: 'Rata-rata risiko', nilai: (d) => d.avg_risk ?? '' },
                      { label: 'Risiko tinggi', nilai: (d) => d.high_risk_count ?? 0 }]} />
                </div>
                <TabelData baris={deptRows} kunci={(d) => d.department} testId="attrition-departments"
                  kolom={[
                    { kunci: 'dept', label: 'Departemen', hp: 'judul', isi: (d) => <span className="font-medium text-foreground">{d.department}</span> },
                    { kunci: 'avg', label: 'Rata-rata risiko', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.avg_risk?.toFixed(1) || 0}</span> },
                    { kunci: 'tinggi', label: 'Risiko tinggi', rata: 'kanan', isi: (d) => <span className="tabular-nums">{d.high_risk_count ?? 0}</span> },
                  ]} />
              </section>
            )}
          </div>
        </div>
      )}

      {lihat && (
        <DetailPopup open onClose={() => setLihat(null)} judul={lihat.name} keterangan="Rincian risiko keluar"
          status={<Risiko level={lihat.risk_level} />} testId="attrition-detail">
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="ID karyawan">{lihat.employee_id}</BarisDetail>
            <BarisDetail label="Departemen">{lihat.department || '—'}</BarisDetail>
            <BarisDetail label="Skor risiko"><span className="font-semibold tabular-nums">{lihat.risk_score}</span></BarisDetail>
          </dl>
          <div>
            <p className="mb-1 text-sm font-medium text-foreground">Faktor risiko</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {(lihat.risk_factors || []).map((rf, j) => <li key={j}>{rf}</li>)}
              {!lihat.risk_factors?.length && <li>—</li>}
            </ul>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium text-foreground">Saran retensi</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {(lihat.retention_suggestions || []).map((rs, j) => <li key={j}>{rs}</li>)}
              {!lihat.retention_suggestions?.length && <li>—</li>}
            </ul>
          </div>
        </DetailPopup>
      )}
    </PageLayout>
  );
}
