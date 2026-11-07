// K28 (keputusan owner 2026-11-02): output AI = USULAN yang dikonfirmasi pengguna.
// Satu panel untuk komplain, ulasan, dan kandidat: menampilkan nilai usulan + alasan +
// waktu, dengan tombol Terima / Ubah / Tolak. Nilai resmi baru berubah di server saat
// diterima (aktor dicatat di sana) — panel ini tidak pernah menulis nilai resmi sendiri.
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Bot, Check, Pencil, X, Loader2 } from 'lucide-react';

const STATUS_LABEL = {
  pending: 'Menunggu keputusan',
  accepted: 'Diterima',
  modified: 'Diubah lalu diterima',
  rejected: 'Ditolak',
};

function fmtTime(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

/**
 * props:
 *  - suggestion : dokumen `ai_suggestion` dari server
 *  - fields     : [{ key, label, options?: [{value,label}], type?: 'number' }]
 *  - decideUrl  : URL POST {action, values}
 *  - headers    : header auth
 *  - onDecided  : (respJson) => void
 */
export default function AISuggestionPanel({ suggestion, fields, decideUrl, headers, onDecided, testId = 'ai-suggestion' }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  if (!suggestion) return null;
  const values = suggestion.values || {};
  const pending = suggestion.status === 'pending';
  const labelOf = (f, v) => (f.options || []).find(o => o.value === v)?.label || (v ?? '—');

  const decide = async (action) => {
    setBusy(action);
    setError('');
    try {
      const body = { action };
      if (action === 'modify') body.values = draft;
      const r = await fetch(decideUrl, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data?.detail || `HTTP ${r.status}`);
      setEditing(false);
      onDecided && onDecided(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="rounded-[var(--radius-md)] border border-[hsl(var(--primary)/0.3)] bg-[hsl(var(--primary)/0.06)] p-3 space-y-2" data-testid={testId}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-[hsl(var(--primary))] flex items-center gap-1">
          <Bot size={13} /> Usulan AI — belum mengubah data resmi sebelum diterima
        </p>
        <Badge variant="outline" className="text-xs">{STATUS_LABEL[suggestion.status] || 'Menunggu'}</Badge>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {fields.map(f => (
          <div key={f.key}>
            <p className="text-xs text-muted-foreground">{f.label}</p>
            {editing && f.options ? (
              <Select value={draft[f.key] ?? values[f.key] ?? ''} onValueChange={v => setDraft(d => ({ ...d, [f.key]: v }))}>
                <SelectTrigger className="h-8 text-xs" data-testid={`${testId}-edit-${f.key}`}><SelectValue /></SelectTrigger>
                <SelectContent>
                  {f.options.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                </SelectContent>
              </Select>
            ) : editing && f.type === 'number' ? (
              <Input type="number" className="h-8 text-xs" value={draft[f.key] ?? values[f.key] ?? ''}
                onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value === '' ? null : Number(e.target.value) }))} />
            ) : (
              <p className="text-sm font-medium">{labelOf(f, (suggestion.final_values || {})[f.key] ?? values[f.key])}</p>
            )}
          </div>
        ))}
      </div>

      {suggestion.reason && <p className="text-xs text-muted-foreground italic">Alasan AI: {suggestion.reason}</p>}
      <p className="text-xs text-muted-foreground">
        Diusulkan {fmtTime(suggestion.suggested_at)}
        {suggestion.confidence != null && ` · keyakinan ${Math.round(suggestion.confidence * 100)}%`}
        {suggestion.decided_by && ` · diputuskan ${suggestion.decided_by} ${fmtTime(suggestion.decided_at)}`}
      </p>
      {error && <p className="text-xs text-[hsl(var(--danger-text))]">{error}</p>}

      {pending && (
        <div className="flex flex-wrap gap-2 pt-1">
          {!editing ? (
            <>
              <Button size="sm" variant="success" onClick={() => decide('accept')} disabled={!!busy} data-testid={`${testId}-accept`}>
                {busy === 'accept' ? <Loader2 className="animate-spin" /> : <Check />} Terima
              </Button>
              <Button size="sm" variant="outline" onClick={() => { setDraft({}); setEditing(true); }} disabled={!!busy} data-testid={`${testId}-modify`}>
                <Pencil /> Ubah
              </Button>
              <Button size="sm" variant="destructive" onClick={() => decide('reject')} disabled={!!busy} data-testid={`${testId}-reject`}>
                {busy === 'reject' ? <Loader2 className="animate-spin" /> : <X />} Tolak
              </Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="success" onClick={() => decide('modify')} disabled={!!busy || Object.keys(draft).length === 0} data-testid={`${testId}-save`}>
                {busy === 'modify' ? <Loader2 className="animate-spin" /> : <Check />} Simpan perubahan
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={!!busy}>Batal</Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
