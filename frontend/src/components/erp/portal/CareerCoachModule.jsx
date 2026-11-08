/**
 * Portal Saya › Pendamping Karier — arahan karier dari asisten AI: ringkasan profil, obrolan, dan laporan karier.
 *
 * Standar UI/UX v2 (8 Nov 2026): PageLayout (dulu kepala berikon gradien + `p-6`), tab buatan → pil penyaring (FilterChips),
 * angka profil = StatTile, "Buat laporan karier" = FormPopup (dulu form di halaman), daftar laporan = TabelData +
 * unduh Excel/CSV, isi laporan di DetailPopup, istilah Indonesia. Endpoint & isi permintaan AI tidak berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { toast } from 'sonner';
import { Loader2, MessageSquarePlus, Send, Sparkles } from 'lucide-react';
import { formatDateID } from '@/lib/format';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatTile } from '../moduleAtoms';

const FOKUS = {
  overall: 'Keseluruhan',
  career_path: 'Jalur karier',
  skills: 'Pengembangan keahlian',
  learning: 'Sumber belajar',
};
const fokus = (k) => FOKUS[k] || k || '—';
const tgl = (v) => (v ? formatDateID(v) : '—');

export default function CareerCoachModule({ token }) {
  const [activeTab, setActiveTab] = useState('dashboard'); // dashboard, chat, reports
  const [profile, setProfile] = useState(null);
  const [reports, setReports] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [chatting, setChatting] = useState(false);
  const [formOpen, setFormOpen] = useState(false);

  // Generate report form
  const [reportForm, setReportForm] = useState({
    focus_area: 'overall',
    specific_goals: ''
  });

  // Chat
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([]);

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/career-coach/profile`, { headers });
      // 404 = akun belum terhubung ke data karyawan — dijelaskan di layar, tidak perlu pesan galat.
      if (r.status === 404) { setProfile(null); return; }
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setProfile(data?.data);
    } catch (e) {
      toast.error(`Gagal memuat profil: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchReports = useCallback(async () => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/career-coach/reports`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setReports(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat laporan: ${e.message}`);
    }
  }, [headers]);

  const fetchConversations = useCallback(async () => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/career-coach/chat/history`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setConversations(data?.data || []);
    } catch (e) {
      console.error('Failed to load conversations:', e);
    }
  }, [headers]);

  useEffect(() => {
    fetchProfile();
    fetchReports();
    fetchConversations();
  }, [fetchProfile, fetchReports, fetchConversations]);

  const handleGenerateReport = async () => {
    setGenerating(true);
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/career-coach/generate-report`, {
        method: 'POST',
        headers,
        body: JSON.stringify(reportForm)
      });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      toast.success('Laporan karier selesai dibuat.');
      setFormOpen(false);
      setSelectedReport(data?.data);
      fetchReports();
      setActiveTab('reports');
    } catch (e) {
      toast.error(`Gagal membuat laporan: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleSendChat = async () => {
    if (!chatMessage.trim()) return;

    const userMessage = { role: 'user', content: chatMessage, timestamp: new Date().toISOString() };
    setChatHistory([...chatHistory, userMessage]);
    setChatMessage('');
    setChatting(true);

    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/career-coach/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          message: userMessage.content,
          conversation_id: currentConversation
        })
      });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();

      const aiMessage = {
        role: 'assistant',
        content: data?.data?.message || 'Tidak ada jawaban',
        timestamp: data?.data?.timestamp
      };

      setChatHistory(prev => [...prev, aiMessage]);
      setCurrentConversation(data?.data?.conversation_id);
      fetchConversations();
    } catch (e) {
      toast.error(`Obrolan gagal: ${e.message}`);
      setChatHistory(prev => [...prev, { role: 'error', content: `Galat: ${e.message}`, timestamp: new Date().toISOString() }]);
    } finally {
      setChatting(false);
    }
  };

  const loadConversation = async (convId) => {
    try {
      const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/portal-saya/career-coach/chat/history?conversation_id=${convId}`, { headers });
      if (!r.ok) throw new Error(`kode ${r.status}`);
      const data = await r.json();
      setChatHistory(data?.data?.messages || []);
      setCurrentConversation(convId);
    } catch (e) {
      toast.error(`Gagal memuat obrolan: ${e.message}`);
    }
  };

  const startNewChat = () => {
    setChatHistory([]);
    setCurrentConversation(null);
    setChatMessage('');
  };

  const info = profile?.basic_info || {};
  const kinerja = profile?.performance_history || [];
  const rataKinerja = kinerja.length > 0
    ? (kinerja.reduce((sum, p) => sum + (p.score || 0), 0) / kinerja.length).toFixed(1).replace('.', ',') : '—';
  const jam = (ts) => { const d = ts ? new Date(ts) : null; return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta' }) : ''; };

  return (
    <PageLayout testId="career-coach-module" title="Pendamping karier"
      subtitle="Arahan karier pribadi dari asisten AI berdasarkan profil, training, dan kinerja Anda."
      actions={<Button onClick={() => setFormOpen(true)} disabled={!profile} data-testid="career-generate-btn"><Sparkles />Buat laporan karier</Button>}>
      <FilterChips value={activeTab} onChange={(k) => setActiveTab(k || 'dashboard')} hideWhenEmpty={false} testId="career-tab"
        ariaLabel="Bagian pendamping karier" className="w-full min-w-0 flex-wrap overflow-visible pb-0 sm:w-auto" options={[
          { key: 'dashboard', label: 'Ringkasan' },
          { key: 'chat', label: 'Obrolan' },
          { key: 'reports', label: 'Laporan', count: reports.length },
        ]} />

        {/* Ringkasan */}
        {activeTab === 'dashboard' && (<div className="space-y-4">
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Memuat profil karier…</p>
          ) : profile ? (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <StatTile label="Keahlian saat ini" value={profile.current_skills?.length || 0} />
                <StatTile label="Training selesai" value={profile.training_history?.length || 0} />
                <StatTile label="Rata-rata kinerja" value={rataKinerja}
                  sub={kinerja.length ? `Dari ${kinerja.length} penilaian` : 'Belum ada penilaian'} />
              </div>
              <GlassCard className="space-y-2 p-4">
                <h3 className="text-lg font-semibold text-foreground">Profil</h3>
                <dl className="divide-y divide-[var(--glass-border)]">
                  <BarisDetail label="Nama">{info.name || '—'}</BarisDetail>
                  <BarisDetail label="Jabatan">{info.job_title || '—'}</BarisDetail>
                  <BarisDetail label="Departemen">{info.department || '—'}</BarisDetail>
                  <BarisDetail label="Kode karyawan">{info.employee_code || '—'}</BarisDetail>
                  <BarisDetail label="Masa kerja">{info.tenure_years != null ? `${info.tenure_years} tahun` : '—'}</BarisDetail>
                </dl>
              </GlassCard>
            </>
          ) : (
            <EmptyState title="Profil karier belum bisa dimuat"
              description="Pastikan akun Anda sudah terhubung ke data karyawan, lalu muat ulang halaman." />
          )}
        </div>)}

        {/* Obrolan */}
        {activeTab === 'chat' && (<div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            <GlassCard className="space-y-3 p-4 lg:col-span-1">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-foreground">Riwayat obrolan</h3>
                <Button size="sm" variant="outline" onClick={startNewChat}><MessageSquarePlus />Baru</Button>
              </div>
              {conversations.length === 0 ? (
                <p className="text-sm text-muted-foreground">Belum ada obrolan.</p>
              ) : (
                <ul className="max-h-96 divide-y divide-[var(--glass-border)] overflow-y-auto">
                  {conversations.map(conv => (
                    <li key={conv.id}>
                      <Button variant="ghost" onClick={() => loadConversation(conv.id)}
                        className={`h-auto w-full flex-col items-start gap-0.5 whitespace-normal py-2 text-left ${currentConversation === conv.id ? 'bg-[hsl(var(--primary)/0.08)]' : ''}`}>
                        <span className="line-clamp-1 text-sm font-medium">{conv.last_message?.content?.substring(0, 40) || 'Obrolan baru'}</span>
                        <span className="text-xs text-muted-foreground">{conv.message_count} pesan</span>
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </GlassCard>

            <GlassCard className="flex h-[60vh] min-h-[24rem] flex-col p-4 lg:col-span-3">
              <div className="mb-3 flex-1 space-y-3 overflow-y-auto">
                {chatHistory.length === 0 ? (
                  <EmptyState title="Mulai obrolan"
                    description="Tanyakan apa pun tentang karier Anda. Asisten AI memberi arahan berdasarkan profil dan kinerja Anda." />
                ) : (
                  chatHistory.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[85%] rounded-lg p-3 ${
                        msg.role === 'user' ? 'bg-primary text-primary-foreground'
                          : msg.role === 'error' ? 'border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--destructive)/0.08)] text-[hsl(var(--danger-text))]'
                            : 'border border-[var(--glass-border)] bg-[var(--card-surface)]'}`}>
                        <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
                        {jam(msg.timestamp) && <p className="mt-1 text-xs opacity-70">{jam(msg.timestamp)}</p>}
                      </div>
                    </div>
                  ))
                )}
                {chatting && (
                  <div className="flex justify-start">
                    <div className="rounded-lg border border-[var(--glass-border)] p-3">
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    </div>
                  </div>
                )}
              </div>
              <div className="flex gap-2">
                <Textarea placeholder="Tanyakan tentang karier Anda…" value={chatMessage} rows={2} disabled={chatting}
                  onChange={e => setChatMessage(e.target.value)}
                  onKeyPress={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSendChat())} />
                <Button onClick={handleSendChat} disabled={chatting || !chatMessage.trim()} className="shrink-0"
                  size="icon" title="Kirim" aria-label="Kirim">
                  <Send />
                </Button>
              </div>
            </GlassCard>
          </div>
        </div>)}

        {/* Laporan */}
        {activeTab === 'reports' && (<div className="space-y-3">
          {reports.length > 0 && (
            <div className="flex justify-end">
              <TombolUnduh namaBerkas="laporan-karier-saya" namaLembar="Laporan" baris={reports} testId="career-unduh" kolom={[
                { label: 'Fokus', nilai: (r) => fokus(r.focus_area) }, { label: 'Dibuat', nilai: (r) => tgl(r.generated_at) },
                { label: 'Ringkasan', nilai: (r) => r.report?.summary || '' },
              ]} />
            </div>
          )}
          <TabelData baris={reports} onKlikBaris={setSelectedReport} testId="career-reports"
            kosong={<EmptyState title="Belum ada laporan karier" description="Tekan Buat laporan karier untuk membuat laporan pertama." />}
            kolom={[
              { kunci: 'fokus', label: 'Fokus', hp: 'judul', isi: (r) => <span className="font-medium">{fokus(r.focus_area)}</span> },
              { kunci: 'dibuat', label: 'Dibuat', isi: (r) => <span className="whitespace-nowrap">{tgl(r.generated_at)}</span> },
              { kunci: 'ringkasan', label: 'Ringkasan', isi: (r) => <p className="line-clamp-2 text-sm text-muted-foreground md:max-w-[34rem]">{r.report?.summary || '—'}</p> },
              { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (r) => <Button size="sm" variant="outline" onClick={() => setSelectedReport(r)}>Buka</Button> },
            ]} />
        </div>)}

      {/* Buat laporan karier */}
      <FormPopup open={formOpen} onClose={() => setFormOpen(false)} ukuran="pendek" testId="career-generate-form"
        judul="Buat laporan karier" keterangan="Asisten AI menyusun laporan dari profil, training, dan kinerja Anda."
        onSimpan={handleGenerateReport} menyimpan={generating} labelSimpan="Buat laporan">
        <Isian label="Fokus">
          <SmartNativeSelect value={reportForm.focus_area} searchable={false} className="w-full"
            onChange={(e) => setReportForm({ ...reportForm, focus_area: e.target.value })}>
            {Object.entries(FOKUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Tujuan karier khusus (opsional)" htmlFor="career-goals">
          <Textarea id="career-goals" rows={3} placeholder="Jelaskan tujuan karier spesifik Anda…"
            value={reportForm.specific_goals} onChange={e => setReportForm({ ...reportForm, specific_goals: e.target.value })} />
        </Isian>
      </FormPopup>

      {/* Isi laporan */}
      {selectedReport && (
        <DetailPopup open onClose={() => setSelectedReport(null)} testId="career-report-detail" judul="Laporan karier"
          keterangan={`Fokus: ${fokus(selectedReport.focus_area)} · ${selectedReport.employee_name || ''} · dibuat ${tgl(selectedReport.generated_at)}`}>
          {selectedReport.report?.full_report && (
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{selectedReport.report.full_report}</div>
          )}
          {selectedReport.report?.sections && Object.keys(selectedReport.report.sections).length > 0 && (
            <dl className="divide-y divide-[var(--glass-border)]">
              {Object.entries(selectedReport.report.sections).map(([key, value]) => (
                <BarisDetail key={key} label={key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())}>
                  <span className="whitespace-pre-line">{value}</span>
                </BarisDetail>
              ))}
            </dl>
          )}
        </DetailPopup>
      )}
    </PageLayout>
  );
}
