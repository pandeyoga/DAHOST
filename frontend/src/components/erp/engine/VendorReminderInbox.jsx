import { useState, useEffect } from 'react';
import { Bell, Clock, CheckCircle, MessageSquare, X } from 'lucide-react';
import { toast } from 'sonner';
import { apiGet, apiPut } from '../../../lib/api';
import { Button } from '@/components/ui/button';
import { GlassCard } from '@/components/ui/glass';
import { EmptyState } from '../moduleAtoms';

export default function VendorReminderInbox({ token, user }) {
  const [reminders, setReminders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [responseText, setResponseText] = useState('');
  const [respondingId, setRespondingId] = useState(null);

  useEffect(() => {
    fetchReminders();
  }, []);

  const fetchReminders = async () => {
    try {
      setReminders(await apiGet('/reminders'));
    } catch (e) {}
    setLoading(false);
  };

  const sendResponse = async (reminderId) => {
    if (!responseText.trim()) { toast.error('Tulis respon terlebih dahulu'); return; }
    try {
      await apiPut(`/reminders/${reminderId}`, { response: responseText });
      setRespondingId(null);
      setResponseText('');
      fetchReminders();
    } catch (e) { toast.error('Error: ' + e.message); }
  };

  const fmtDate = (d) => d ? new Date(d).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';
  const pending = reminders.filter(r => r.status === 'pending');
  const responded = reminders.filter(r => r.status !== 'pending');

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-foreground flex items-center gap-2"><Bell className="w-5 h-5 text-[hsl(var(--success-text))]" /> Inbox Reminder</h2>
          <p className="text-sm text-muted-foreground">Pesan dan reminder dari ERP Admin</p>
        </div>
        <div className="flex items-center gap-2">
          {pending.length > 0 && (
            <span className="px-3 py-1 bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning-text))] rounded-full text-xs font-medium">{pending.length} belum dibalas</span>
          )}
        </div>
      </div>

      {loading ? (
        <div className="text-center py-8 text-muted-foreground/70">Memuat...</div>
      ) : reminders.length === 0 ? (
        <GlassCard>
          <EmptyState icon={Bell} title="Belum ada reminder" description="Reminder dari admin akan muncul di sini." />
        </GlassCard>
      ) : (
        <div className="space-y-4">
          {/* Pending first */}
          {pending.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-[hsl(var(--warning-text))] mb-2 flex items-center gap-1"><Clock className="w-4 h-4" /> Menunggu Respon ({pending.length})</h3>
              <div className="space-y-3">
                {pending.map(r => (
                  <div key={r.id} className="bg-[hsl(var(--warning)/0.1)] border border-[hsl(var(--warning)/0.35)] rounded-xl p-4 shadow-sm">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${r.priority === 'urgent' ? 'bg-[hsl(var(--destructive)/0.2)] text-[hsl(var(--danger-text))]' : r.priority === 'high' ? 'bg-[hsl(var(--warning)/0.2)] text-[hsl(var(--warning-text))]' : 'bg-[hsl(var(--primary)/0.2)] text-[hsl(var(--primary))]'}`}>{r.priority === 'urgent' ? 'Mendesak' : r.priority === 'high' ? 'Tinggi' : 'Normal'}</span>
                          <span className="text-xs text-muted-foreground/70">{fmtDate(r.created_at)}</span>
                        </div>
                        <h4 className="font-semibold text-foreground mt-1">{r.subject}</h4>
                        {r.po_number && <p className="text-xs text-muted-foreground mt-0.5">PO: {r.po_number}</p>}
                        <p className="text-sm text-muted-foreground mt-1">{r.message}</p>
                        <p className="text-xs text-muted-foreground/70 mt-1">Dari: {r.created_by}</p>
                      </div>
                    </div>
                    {respondingId === r.id ? (
                      <div className="mt-3 space-y-2">
                        <textarea value={responseText} onChange={e => setResponseText(e.target.value)} className="w-full border border-[hsl(var(--warning)/0.35)] rounded-lg px-3 py-2 text-sm h-20 resize-none bg-card" placeholder="Tulis respon Anda..." />
                        <div className="flex gap-2">
                          <Button size="sm" onClick={() => sendResponse(r.id)}><MessageSquare className="w-3.5 h-3.5" /> Kirim Respon</Button>
                          <Button size="sm" variant="outline" onClick={() => { setRespondingId(null); setResponseText(''); }}>Batal</Button>
                        </div>
                      </div>
                    ) : (
                      <Button size="sm" className="mt-3" onClick={() => setRespondingId(r.id)}><MessageSquare className="w-3.5 h-3.5" /> Balas</Button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* Responded */}
          {responded.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-[hsl(var(--success-text))] mb-2 flex items-center gap-1"><CheckCircle className="w-4 h-4" /> Sudah Dibalas ({responded.length})</h3>
              <div className="space-y-3">
                {responded.map(r => (
                  <div key={r.id} className="bg-card border border-[hsl(var(--success)/0.35)] rounded-xl p-4 shadow-sm">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs text-muted-foreground/70">{fmtDate(r.created_at)}</span>
                      <span className="px-1.5 py-0.5 rounded text-xs bg-[hsl(var(--success)/0.2)] text-[hsl(var(--success-text))] font-medium">Dibalas</span>
                    </div>
                    <h4 className="font-medium text-foreground/90">{r.subject}</h4>
                    <p className="text-sm text-muted-foreground mt-0.5">{r.message}</p>
                    <div className="mt-2 p-2 bg-[hsl(var(--success)/0.1)] rounded-lg border border-[hsl(var(--success)/0.35)]">
                      <p className="text-sm text-[hsl(var(--success-text))]">{r.response}</p>
                      <p className="text-xs text-muted-foreground/70 mt-1">Dibalas: {fmtDate(r.response_date)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}


// ─── VENDOR VARIANCE REPORT (OVERPRODUCTION/UNDERPRODUCTION) ────────────────


