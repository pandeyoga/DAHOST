/**
 * Wawasan AI (Portal SDM › AI SDM) — ringkasan harian, analisis akar masalah, pencarian, prediksi keterlambatan WO.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout (di hub: judul hub, bagian jadi pil), hasil pencarian &
 * prediksi = tabel + unduh Excel/CSV (dulu kartu berulang), simpan sebagai tugas = FormPopup, tanggal =
 * DatePicker (dulu input tanggal bawaan), kartu angka StatTile, warna token, bahasa Indonesia.
 * Angka: efisiensi dulu dibagi target 1 bila target kosong (bisa 5000%) dan rasio gagal QC "0%" walau belum ada
 * pemeriksaan — kini "—" dengan alasan.
 */
import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Brain, CheckSquare, Loader2, RefreshCw, Search, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { GlassCard } from '@/components/ui/glass';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import { useToast } from '@/hooks/use-toast';
import { todayWIB } from '@/lib/waktu';
import { formatDateID, formatDateTimeID } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL;
const RISIKO = { high: { label: 'Risiko tinggi', tone: 'danger' }, medium: { label: 'Risiko sedang', tone: 'warning' }, low: { label: 'Risiko rendah', tone: 'success' } };
const JENIS_HASIL = { wo: 'WO', order: 'Order', employee: 'Karyawan', karyawan: 'Karyawan' };
const CONTOH_PERTANYAAN = ['Kenapa QC fail rate tinggi?', 'Apa penyebab downtime terbanyak?', 'Mengapa output turun minggu ini?'];

export default function RahazaAIModule({ headers }) {
  const { toast } = useToast();
  const [tab, setTab] = useState('summary');
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryDate, setSummaryDate] = useState(() => todayWIB());

  const [rcQuestion, setRcQuestion] = useState('');
  const [rcAnswer, setRcAnswer] = useState(null);
  const [rcLoading, setRcLoading] = useState(false);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searchLoading, setSearchLoading] = useState(false);

  const [delays, setDelays] = useState(null);
  const [delaysLoading, setDelaysLoading] = useState(false);

  // Save-as-Task dialog
  const [taskDialog, setTaskDialog] = useState(null);
  const [savingTask, setSavingTask] = useState(false);

  const openSaveTask = (source, title, description, source_ref = '') => {
    setTaskDialog({
      source, source_ref,
      title: title.slice(0, 200),
      description: description || '',
      priority: 'medium',
      due_date: '',
    });
  };

  const submitTask = async () => {
    if (!taskDialog?.title?.trim()) { toast({ title: 'Judul wajib diisi', variant: 'destructive' }); return; }
    setSavingTask(true);
    try {
      await axios.post(`${API}/api/dewi/ai-actions`, taskDialog, { headers });
      toast({ title: 'Tersimpan sebagai tugas', description: 'Buka tab "Tindak lanjut" untuk memantau.' });
      setTaskDialog(null);
    } catch (e) {
      toast({ title: 'Gagal menyimpan tugas', variant: 'destructive' });
    } finally { setSavingTask(false); }
  };

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const { data } = await axios.get(`${API}/api/rahaza/ai/daily-summary`, { headers, params: { date: summaryDate } });
      setSummary(data);
    } catch (e) {
      toast({ title: 'Gagal memuat ringkasan AI', variant: 'destructive' });
    } finally { setSummaryLoading(false); }
  }, [headers, summaryDate, toast]);

  const loadDelays = useCallback(async () => {
    setDelaysLoading(true);
    try {
      const { data } = await axios.get(`${API}/api/rahaza/ai/predictive-delay`, { headers });
      setDelays(data);
    } catch (e) {} finally { setDelaysLoading(false); }
  }, [headers]);

  const handleRootCause = async () => {
    if (!rcQuestion.trim()) return;
    setRcLoading(true);
    try {
      const { data } = await axios.post(`${API}/api/rahaza/ai/root-cause`, { question: rcQuestion }, { headers });
      setRcAnswer(data);
    } catch (e) {
      toast({ title: 'Gagal', variant: 'destructive' });
    } finally { setRcLoading(false); }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    try {
      const { data } = await axios.post(`${API}/api/rahaza/ai/smart-search`, { query: searchQuery }, { headers });
      setSearchResults(data);
    } catch (e) {
      toast({ title: 'Gagal', variant: 'destructive' });
    } finally { setSearchLoading(false); }
  };

  useEffect(() => {
    if (tab === 'summary') loadSummary();
    if (tab === 'delay') loadDelays();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, loadSummary, loadDelays]);

  const ctx = summary?.context || {};
  const adaTarget = (ctx.target_output_pcs || 0) > 0;
  const adaQc = (ctx.total_qc_checked || 0) > 0;

  const kolomCari = [
    { kunci: 'jenis', label: 'Jenis', isi: (r) => <StatusBadge status={r.type} label={JENIS_HASIL[r.type] || r.type} tone="default" /> },
    { kunci: 'label', label: 'Hasil', hp: 'judul', isi: (r) => <span className="font-medium text-foreground">{r.label}</span> },
    { kunci: 'kode', label: 'Kode', isi: (r) => <span className="text-sm">{r.code || '—'}</span> },
    { kunci: 'pelanggan', label: 'Pelanggan', isi: (r) => <span className="text-sm">{r.customer || '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => <span className="text-sm">{r.status || '—'}</span> },
  ];
  const kolomDelay = [
    { kunci: 'wo', label: 'WO', hp: 'judul', isi: (wo) => (
      <div className="min-w-0 md:max-w-[26rem]"><p className="font-medium text-foreground">{wo.wo_number}</p><p className="text-xs text-muted-foreground">{wo.message}</p></div>) },
    { kunci: 'risiko', label: 'Risiko', isi: (wo) => {
      const r = RISIKO[wo.risk_level] || { label: wo.risk_level || '—', tone: 'default' };
      return <StatusBadge status={wo.risk_level} label={r.label} tone={r.tone} />;
    } },
    { kunci: 'tenggat', label: 'Jatuh tempo', isi: (wo) => <span className="text-sm md:whitespace-nowrap">{formatDateID(wo.due_date)}</span> },
    { kunci: 'sisa', label: 'Sisa hari', rata: 'kanan', isi: (wo) => <span className="tabular-nums">{wo.days_left}</span> },
    { kunci: 'peluang', label: 'Peluang terlambat', rata: 'kanan', isi: (wo) => <span className="font-medium tabular-nums">{wo.prob_delay_pct}%</span> },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (wo) => ((wo.risk_level === 'high' || wo.risk_level === 'medium') ? (
      <Button size="sm" variant="outline" data-testid={`save-delay-task-${wo.wo_id}`}
        onClick={() => openSaveTask('predictive-delay', `Cegah delay WO ${wo.wo_number}`, wo.message + `\n\nProb delay: ${wo.prob_delay_pct}%, due ${wo.due_date}, sisa ${wo.days_left} hari, butuh ${wo.days_needed} hari lagi.`, wo.wo_id)}>
        <CheckSquare />Jadikan tugas
      </Button>) : null) },
  ];

  return (
    <PageLayout testId="hr-ai-insights" title="Wawasan AI"
      subtitle="Ringkasan harian, analisis akar masalah, dan prediksi keterlambatan berbasis data.">
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="summary">Ringkasan harian</TabsTrigger>
          <TabsTrigger value="rootcause">Akar masalah</TabsTrigger>
          <TabsTrigger value="search">Pencarian pintar</TabsTrigger>
          <TabsTrigger value="delay">Prediksi keterlambatan</TabsTrigger>
        </TabsList>

        {/* Ringkasan harian */}
        <TabsContent value="summary" className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-44"><DatePicker value={summaryDate} onChange={setSummaryDate} bolehKosong={false} testId="ai-summary-date" /></div>
            <Button onClick={loadSummary} disabled={summaryLoading}>
              {summaryLoading ? <Loader2 className="animate-spin" /> : <RefreshCw />}Buat ringkasan
            </Button>
          </div>
          {summary ? (
            <>
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Output" value={`${ctx.total_output_pcs || 0} pcs`} sub={`Hasil produksi ${formatDateID(summaryDate)}.`} />
                <StatTile label="Target" value={adaTarget ? `${ctx.target_output_pcs} pcs` : '—'} sub={adaTarget ? 'Target penugasan hari itu.' : 'Belum ada target hari itu.'} />
                <StatTile label="Efisiensi" value={adaTarget ? `${ctx.efisiensi_pct || 0}%` : '—'} sub={adaTarget ? 'Output ÷ target.' : 'Tidak bisa dihitung tanpa target.'} />
                <StatTile label="Rasio gagal QC" value={adaQc ? `${ctx.fail_rate_pct || 0}%` : '—'}
                  sub={adaQc ? `${ctx.total_qc_fail || 0} gagal dari ${ctx.total_qc_checked} diperiksa.` : 'Belum ada pemeriksaan QC hari itu.'} />
              </div>
              <GlassCard hover={false} className="space-y-3 p-4">
                <p className="text-sm leading-relaxed text-foreground">{summary.summary}</p>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">Dibuat {summary.generated_at ? formatDateTimeID(summary.generated_at) : '—'}</p>
                  <Button size="sm" variant="outline" data-testid="save-summary-task"
                    onClick={() => openSaveTask('daily-summary', `Follow-up Ringkasan ${summaryDate}`, summary.summary, summaryDate)}>
                    <CheckSquare />Jadikan tugas
                  </Button>
                </div>
              </GlassCard>
            </>
          ) : !summaryLoading && (
            <EmptyState icon={Sparkles} title="Belum ada ringkasan" description='Pilih tanggal lalu klik "Buat ringkasan".' />
          )}
        </TabsContent>

        {/* Akar masalah */}
        <TabsContent value="rootcause" className="mt-4 space-y-3">
          <p className="text-sm text-muted-foreground">Tanyakan penyebab masalah produksi. AI memakai data nyata dari sistem.</p>
          <Textarea value={rcQuestion} onChange={e => setRcQuestion(e.target.value)} rows={3}
            placeholder="Contoh: Kenapa rasio gagal QC tinggi di line A minggu ini?" />
          <div className="flex flex-wrap items-center gap-2">
            <SmartNativeSelect searchable={false} value="" onChange={(e) => e.target.value && setRcQuestion(e.target.value)} className="w-64" aria-label="Contoh pertanyaan">
              <option value="">Pakai contoh pertanyaan…</option>
              {CONTOH_PERTANYAAN.map(s => <option key={s} value={s}>{s}</option>)}
            </SmartNativeSelect>
            <Button onClick={handleRootCause} disabled={rcLoading || !rcQuestion.trim()}>
              {rcLoading ? <Loader2 className="animate-spin" /> : <Brain />}Analisis
            </Button>
          </div>
          {rcAnswer && (
            <GlassCard hover={false} className="space-y-3 p-4">
              <p className="text-sm text-muted-foreground">Pertanyaan: {rcAnswer.question}</p>
              <p className="whitespace-pre-wrap text-sm text-foreground">{rcAnswer.analysis}</p>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">Periode data: {rcAnswer.data_period}</p>
                <Button size="sm" variant="outline" data-testid="save-rca-task"
                  onClick={() => openSaveTask('root-cause', `RCA: ${rcAnswer.question.slice(0, 80)}`, rcAnswer.analysis, rcAnswer.data_period)}>
                  <CheckSquare />Jadikan tugas
                </Button>
              </div>
            </GlassCard>
          )}
        </TabsContent>

        {/* Pencarian pintar */}
        <TabsContent value="search" className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex w-full gap-2 sm:w-auto">
              <div className="relative w-full sm:w-96">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && handleSearch()}
                  placeholder="Contoh: WO terlambat, order PT Matahari" className="pl-8" />
              </div>
              <Button onClick={handleSearch} disabled={searchLoading}>{searchLoading ? <Loader2 className="animate-spin" /> : <Search />}Cari</Button>
            </div>
            {searchResults && (
              <TombolUnduh namaBerkas="hasil-pencarian-ai" namaLembar="Hasil" baris={searchResults.results || []}
                kolom={[
                  { label: 'Jenis', nilai: (r) => JENIS_HASIL[r.type] || r.type }, { label: 'Hasil', nilai: (r) => r.label },
                  { label: 'Kode', nilai: (r) => r.code || '' }, { label: 'Pelanggan', nilai: (r) => r.customer || '' }, { label: 'Status', nilai: (r) => r.status || '' },
                ]} />
            )}
          </div>
          <p className="text-sm text-muted-foreground">
            {searchResults ? `${searchResults.count} hasil untuk "${searchResults.query}".` : 'Cari WO, order, atau karyawan dengan kalimat biasa.'}
          </p>
          {searchResults && (
            <TabelData kolom={kolomCari} baris={searchResults.results || []} kunci={(r) => `${r.type}-${r.code || r.label}`} testId="ai-search-results"
              kosong={<EmptyState title="Tidak ada hasil" description="Coba kata lain." />} />
          )}
        </TabsContent>

        {/* Prediksi keterlambatan */}
        <TabsContent value="delay" className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">WO berisiko terlambat, dari output historis dibanding jatuh tempo.</p>
            <div className="flex items-center gap-2">
              <TombolUnduh namaBerkas="prediksi-keterlambatan-wo" namaLembar="Prediksi" baris={delays?.data || []}
                kolom={[
                  { label: 'WO', nilai: (w) => w.wo_number }, { label: 'Risiko', nilai: (w) => RISIKO[w.risk_level]?.label || w.risk_level || '' },
                  { label: 'Jatuh tempo', nilai: (w) => formatDateID(w.due_date) }, { label: 'Sisa hari', nilai: (w) => w.days_left },
                  { label: 'Butuh hari', nilai: (w) => w.days_needed ?? '' }, { label: 'Peluang terlambat (%)', nilai: (w) => w.prob_delay_pct },
                  { label: 'Keterangan', nilai: (w) => w.message || '' },
                ]} />
              <Button variant="outline" size="icon" onClick={loadDelays} disabled={delaysLoading} title="Muat ulang" aria-label="Muat ulang">
                <RefreshCw className={delaysLoading ? 'animate-spin' : ''} />
              </Button>
            </div>
          </div>
          {delays && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="WO dianalisis" value={delays.total ?? 0} sub="WO aktif yang punya jatuh tempo." />
              <StatTile label="Risiko tinggi" value={delays.high_risk ?? 0} accent={delays.high_risk ? 'danger' : 'default'} sub="Peluang terlambat tinggi." />
            </div>
          )}
          {delaysLoading && !delays ? <p className="py-8 text-center text-sm text-muted-foreground">Memuat…</p> : (
            <TabelData kolom={kolomDelay} baris={delays?.data || []} kunci={(w) => w.wo_id} testId="ai-delay"
              kosong={<EmptyState title="Tidak ada WO aktif dengan prediksi keterlambatan" />} />
          )}
        </TabsContent>
      </Tabs>

      {/* Simpan sebagai tugas */}
      <FormPopup open={!!taskDialog} onClose={() => setTaskDialog(null)} ukuran="pendek" onSimpan={submitTask} menyimpan={savingTask}
        judul="Simpan sebagai tugas" labelSimpan="Simpan tugas" testId="ai-save-task-form">
        {taskDialog && (
          <>
            <Isian label="Judul" wajib htmlFor="ai-task-judul">
              <Input id="ai-task-judul" value={taskDialog.title} data-testid="save-task-title"
                onChange={e => setTaskDialog(t => ({ ...t, title: e.target.value }))} />
            </Isian>
            <Isian label="Rekomendasi AI" htmlFor="ai-task-desk">
              <Textarea id="ai-task-desk" value={taskDialog.description} rows={5}
                onChange={e => setTaskDialog(t => ({ ...t, description: e.target.value }))} />
            </Isian>
            <div className="grid gap-4 sm:grid-cols-2">
              <Isian label="Prioritas">
                <SmartNativeSelect searchable={false} value={taskDialog.priority} onChange={e => setTaskDialog(t => ({ ...t, priority: e.target.value }))}>
                  <option value="low">Rendah</option>
                  <option value="medium">Sedang</option>
                  <option value="high">Tinggi</option>
                  <option value="critical">Kritis</option>
                </SmartNativeSelect>
              </Isian>
              <Isian label="Tenggat">
                <DatePicker value={taskDialog.due_date} onChange={v => setTaskDialog(t => ({ ...t, due_date: v }))} placeholder="Tanpa tenggat" testId="ai-task-tenggat" />
              </Isian>
            </div>
          </>
        )}
      </FormPopup>
    </PageLayout>
  );
}
