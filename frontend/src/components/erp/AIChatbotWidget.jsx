import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { Button } from '@/components/ui/button';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import MarkdownAman from '@/components/ui/markdown-aman';
import { MessageCircle, X, Bot, Loader2, RefreshCw, ChevronDown, Sparkles, BookOpen, ArrowRight } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { IconButton } from './IconButton';
import { todayWIB } from '@/lib/waktu';
import { canAccessPortal } from './portalAccess';
import KomposerAsisten from './asisten/KomposerAsisten';

const API = process.env.REACT_APP_BACKEND_URL;
const FALLBACK_SUGGESTIONS = [
  'Apa saja fitur di portal ini?',
  'Apa arti satuan dasar dan konversi kemasan?',
  'Bagaimana cara ekspor/impor data lewat Excel?',
];
const KUNCI_SESI = 'asisten_erp_sesi';

// 2026-11-08 (Asisten AI Tahap A): sesi percakapan disimpan per tab peramban (sessionStorage) supaya riwayat
// bisa dimuat ulang lewat `GET /api/assistant/history?session_id=` — dulu riwayat tidak pernah dimuat.
function sesiAwal(user) {
  const bawaan = `asst-${(user?.id || 'u').slice(0, 8)}-${todayWIB()}`;
  try {
    const ada = window.sessionStorage.getItem(KUNCI_SESI);
    if (ada && ada.startsWith(`asst-${(user?.id || 'u').slice(0, 8)}-`)) return ada;
    window.sessionStorage.setItem(KUNCI_SESI, bawaan);
  } catch { /* penyimpanan diblokir — pakai bawaan */ }
  return bawaan;
}

// 2026-11-06 — `docked`: dibuka dari tombol "Asisten ERP" di menu samping (event `erp-chat-toggle`), tanpa
// bulatan mengambang yang menutupi isi halaman. Tanpa menu samping (Portal Kolaborasi) bulatannya tetap ada.
// 2026-11-08 — tampilan chat disamakan dengan Asisten AI: markdown aman, kotak tanya yang sama (Enter kirim,
// Shift+Enter baris baru, huruf 16 px di HP), panel lebih tinggi & selebar layar di HP, Esc menutup, fokus otomatis,
// dan tautan "Buka Asisten AI" untuk pengguna yang boleh membuka Portal Management.
export default function AIChatbotWidget({ headers, user, portal, moduleId, docked = false }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [ctx, setCtx] = useState(null);
  const [sessionId] = useState(() => sesiAwal(user));
  const [riwayatDimuat, setRiwayatDimuat] = useState(false);
  const bottomRef = useRef(null);
  const komposerRef = useRef(null);
  const bolehAsistenAI = canAccessPortal(user?.role, 'management') && moduleId !== 'asisten-ai';

  useEffect(() => { if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [messages, open, loading]);

  const loadContext = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/assistant/context`, { headers, params: { portal: portal || undefined } });
      setCtx(data);
    } catch (e) { setCtx(null); }
  }, [headers, portal]);

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/api/assistant/history`, { headers, params: { session_id: sessionId } });
      const rows = Array.isArray(data?.messages) ? data.messages : [];
      setMessages((cur) => (cur.length ? cur : rows.map((r) => ({
        role: r.role === 'user' ? 'user' : 'assistant', content: r.content || '', source: r.source,
      }))));
    } catch (e) { /* riwayat gagal dimuat — percakapan baru tetap bisa */ }
    setRiwayatDimuat(true);
  }, [headers, sessionId]);

  useEffect(() => { if (open) loadContext(); }, [open, loadContext]);
  useEffect(() => { if (open && !riwayatDimuat) loadHistory(); }, [open, riwayatDimuat, loadHistory]);
  useEffect(() => {
    const toggle = () => setOpen(o => !o);
    window.addEventListener('erp-chat-toggle', toggle);
    return () => window.removeEventListener('erp-chat-toggle', toggle);
  }, []);
  // Esc menutup panel (kecuali Esc sudah dipakai lapisan lain, mis. dialog konfirmasi); fokus ke kotak tanya.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape' && !e.defaultPrevented) setOpen(false); };
    window.addEventListener('keydown', onKey);
    const t = setTimeout(() => komposerRef.current?.fokus(), 120);
    return () => { window.removeEventListener('keydown', onKey); clearTimeout(t); };
  }, [open]);

  const sendMessage = async (text) => {
    const msg = String(text || '').trim();
    if (!msg || loading) return;
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/api/assistant/ask`,
        { question: msg, portal: portal || null, module: moduleId || null, session_id: sessionId }, { headers });
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply, source: data.source, related: data.related || [] }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Maaf, asisten tidak dapat merespons saat ini.', source: 'error' }]);
    } finally { setLoading(false); }
  };

  const clearHistory = async () => {
    if (!messages.length) return;
    const ok = await confirmDialog({
      title: 'Bersihkan percakapan?',
      body: 'Riwayat percakapan Asisten ERP di sesi ini dihapus.',
      confirmLabel: 'Bersihkan',
      danger: true,
    });
    if (!ok) return;
    try {
      await axios.delete(`${API}/api/assistant/history`, { headers, params: { session_id: sessionId } });
    } catch (e) { /* tetap dibersihkan di layar */ }
    setMessages([]);
  };

  const bukaAsistenAI = () => {
    window.dispatchEvent(new CustomEvent('erp:navigate-module', { detail: { moduleId: 'asisten-ai' } }));
    setOpen(false);
  };

  const suggestions = (ctx?.saran?.length ? ctx.saran : FALLBACK_SUGGESTIONS).slice(0, 4);

  return (
    <>
      {!docked && <button
        onClick={() => setOpen(o => !o)}
        data-testid="ai-chat-toggle"
        aria-label="Asisten ERP"
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-primary shadow-lg flex items-center justify-center hover:scale-105 transition-transform"
      >
        <AnimatePresence mode="wait">
          {open
            ? <motion.div key="x" initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }}><X className="w-6 h-6 text-primary-foreground" /></motion.div>
            : <motion.div key="chat" initial={{ rotate: 90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: -90, opacity: 0 }}><MessageCircle className="w-6 h-6 text-primary-foreground" /></motion.div>
          }
        </AnimatePresence>
      </button>}

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.98 }}
            transition={{ duration: 0.2 }}
            role="dialog"
            aria-label="Asisten ERP"
            className={`fixed z-50 inset-x-0 bottom-0 h-[88dvh] rounded-t-2xl sm:inset-x-auto sm:w-[420px] sm:rounded-2xl sm:h-[min(640px,calc(100dvh-7rem))] ${docked ? 'sm:bottom-4 sm:right-4' : 'sm:bottom-24 sm:right-6'} flex flex-col shadow-2xl border bg-background overflow-hidden`}
            data-testid="ai-chat-window"
          >
            <div className="bg-primary px-4 py-3 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <Bot className="w-5 h-5 text-primary-foreground flex-shrink-0" />
                <div className="min-w-0">
                  <div className="font-semibold text-primary-foreground text-sm truncate" data-testid="ai-chat-title">
                    {ctx?.assistant_name || 'Asisten ERP CV. Dewi Aditya'}
                  </div>
                  {ctx?.portal_label && (
                    <div className="text-[11px] text-primary-foreground/70 truncate" data-testid="ai-chat-portal">
                      Konteks: {ctx.portal_label}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex gap-1 flex-shrink-0">
                <IconButton label="Bersihkan percakapan" onClick={clearHistory} className="text-primary-foreground/70 hover:text-primary-foreground p-1" data-testid="ai-chat-clear"><RefreshCw className="w-3.5 h-3.5" /></IconButton>
                <IconButton label="Tutup asisten" onClick={() => setOpen(false)} className="text-primary-foreground/70 hover:text-primary-foreground p-1" data-testid="ai-chat-close"><ChevronDown className="w-4 h-4" /></IconButton>
              </div>
            </div>

            {bolehAsistenAI && (
              <div className="shrink-0 flex items-center justify-between gap-2 border-b border-[var(--glass-border)] px-4 py-1.5 text-xs text-muted-foreground" data-testid="ai-chat-asisten-ai">
                <span className="truncate">Butuh analisis angka, grafik, atau laporan?</span>
                <Button variant="link" size="sm" className="h-auto shrink-0 p-0 text-xs" onClick={bukaAsistenAI} data-testid="ai-chat-buka-asisten-ai">
                  Buka Asisten AI <ArrowRight className="w-3.5 h-3.5" />
                </Button>
              </div>
            )}

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" role="log" aria-live="polite" data-testid="ai-chat-log">
              <div className="p-3 space-y-4">
                {messages.length === 0 && (
                  <div className="space-y-2" data-testid="ai-chat-welcome">
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[hsl(var(--primary)/0.12)] text-primary" aria-hidden="true">
                        <Bot className="h-3.5 w-3.5" />
                      </span>
                      <p className="pt-1 text-sm text-foreground/90">
                        {ctx?.ringkasan
                          ? `Halo! Saya bisa menjelaskan cara kerja ${ctx.portal_label}. ${ctx.total_fitur > 0 ? `Ada ${ctx.total_fitur} modul di sini.` : ''}`
                          : 'Halo! Tanyakan apa saja tentang cara kerja sistem ERP ini.'}
                      </p>
                    </div>
                    <p className="text-xs text-muted-foreground pl-9 pt-1">Pertanyaan yang sering diajukan:</p>
                    <div className="flex flex-wrap gap-2 pl-9">
                      {suggestions.map(s => (
                        <Button key={s} variant="outline" size="sm" className="h-auto min-h-8 whitespace-normal rounded-full py-1 text-left font-normal"
                          onClick={() => sendMessage(s)} data-testid="ai-chat-suggestion">{s}</Button>
                      ))}
                    </div>
                  </div>
                )}

                {messages.map((msg, i) => (
                  msg.role === 'user' ? (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[hsl(var(--primary)/0.12)] px-3.5 py-2 text-sm text-foreground"
                        data-testid="ai-chat-user-msg">{msg.content}</div>
                    </div>
                  ) : (
                    <div key={i} className="flex items-start gap-2">
                      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[hsl(var(--primary)/0.12)] text-primary" aria-hidden="true">
                        <Bot className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <MarkdownAman text={msg.content} className="leading-relaxed" testId="ai-chat-bot-msg" />
                        {msg.source && msg.source !== 'error' && (
                          <div className="flex items-center gap-1 text-[11px] text-muted-foreground" data-testid="ai-chat-source">
                            {msg.source === 'ai'
                              ? <><Sparkles className="w-3 h-3" /> Dijawab AI</>
                              : <><BookOpen className="w-3 h-3" /> Panduan sistem</>}
                          </div>
                        )}
                        {msg.related?.length > 0 && (
                          <div className="space-y-1">
                            {msg.related.slice(0, 2).map(r => (
                              <Button key={r} variant="link" size="sm" className="h-auto p-0 text-[11px] whitespace-normal text-left"
                                onClick={() => sendMessage(r)} data-testid="ai-chat-related">→ {r}</Button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )
                ))}

                {loading && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="ai-chat-loading">
                    <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[hsl(var(--primary)/0.12)] text-primary" aria-hidden="true">
                      <Bot className="h-3.5 w-3.5" />
                    </span>
                    <Loader2 className="w-4 h-4 animate-spin" /> Menyiapkan jawaban…
                  </div>
                )}
                <div ref={bottomRef} />
              </div>
            </div>

            <KomposerAsisten
              ref={komposerRef}
              testId="ai-chat"
              onKirim={sendMessage}
              sibuk={loading}
              placeholder="Tanya cara kerja sistem…"
              labelInput="Pertanyaan untuk Asisten ERP"
              catatan="Asisten ERP menjelaskan cara memakai menu. Jawaban AI bisa keliru."
            />
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
