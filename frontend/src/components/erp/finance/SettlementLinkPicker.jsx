/**
 * SettlementLinkPicker — pilih PENARIKAN saldo platform (tahap 2) untuk satu baris mutasi bank.
 * Kandidat diurutkan server: nominal sama persis → tanggal terdekat. Tautan dengan
 * nominal berbeda DITOLAK server, jadi di sini tombolnya dinonaktifkan dengan alasan.
 */
import { useEffect, useState } from 'react';
import axios from 'axios';
import { Loader2, Banknote, CheckCircle2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatDateID, formatRupiah as fmt } from '@/lib/format';

const PLATFORM = { shopee: 'Shopee', tiktok: 'TikTok', tokopedia: 'Tokopedia', lazada: 'Lazada' };
const namaPlatform = (p) => PLATFORM[String(p || '').toLowerCase()] || (p ? String(p).charAt(0).toUpperCase() + String(p).slice(1).toLowerCase() : '');

const API = process.env.REACT_APP_BACKEND_URL;

export function SettlementLinkPicker({ sessionId, txn, headers, onLink }) {
  const [items, setItems] = useState([]);
  const [exact, setExact] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    axios.get(`${API}/api/finance/bank-recon/sessions/${sessionId}/transactions/${txn.id}/settlement-candidates`, { headers })
      .then(({ data }) => { if (alive) { setItems(data.items || []); setExact(data.exact_count || 0); } })
      .catch((e) => { if (alive) setError(e.response?.data?.detail || 'Gagal memuat penarikan.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [sessionId, txn.id, headers]);

  const link = async (s) => {
    setBusy(s.id); setError('');
    try {
      const { data } = await axios.post(`${API}/api/finance/bank-recon/sessions/${sessionId}/link-settlement`,
        { txn_id: txn.id, settlement_doc_id: s.id }, { headers });
      onLink?.(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Gagal menautkan.');
    } finally { setBusy(''); }
  };

  return (
    <div className="mt-3 pl-4 border-l-2 border-[hsl(var(--success)/0.4)]" data-testid={`settlement-picker-${txn.id}`}>
      <p className="text-sm font-medium mb-1 text-foreground flex items-center gap-1.5">
        <Banknote className="w-4 h-4" /> Tautkan ke penarikan saldo marketplace
        <span className="font-normal text-muted-foreground">
          · {exact} penarikan bernominal sama persis
        </span>
      </p>
      {txn.type !== 'debit' ? (
        <p className="text-xs text-[hsl(var(--warning-text))]" data-testid="settlement-picker-not-debit">
          Baris ini uang keluar — penarikan saldo marketplace selalu uang masuk.
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-[hsl(var(--danger-text))] flex items-start gap-1 mb-1" data-testid="settlement-picker-error">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {error}
        </p>
      ) : null}
      {loading ? (
        <div className="py-3 text-xs text-muted-foreground flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> memuat…</div>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="settlement-picker-empty">
          Tidak ada penarikan saldo yang belum tertaut. Catat dulu di Marketplace › Penarikan ke bank.
        </p>
      ) : (
        <div className="max-h-56 overflow-y-auto space-y-1">
          {items.map((s) => (
            <Button key={s.id} type="button" variant="outline" disabled={!s.amount_match || busy === s.id || txn.type !== 'debit'}
              onClick={() => link(s)}
              data-testid={`settlement-pick-${s.settlement_id}`}
              title={s.amount_match ? 'Tautkan' : `Nominal berbeda ${fmt(s.amount_diff)} — koreksi penarikan dulu`}
              className={`w-full h-auto px-3 py-2 text-left text-xs font-normal whitespace-normal flex items-center justify-between gap-2
                ${s.amount_match ? 'border-[hsl(var(--success)/0.4)]' : ''}`}>
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="font-medium">{s.settlement_id}</span>
                  <span className="text-muted-foreground">{s.account_name}</span>
                  <span className="text-muted-foreground">{namaPlatform(s.platform)}</span>
                </div>
                <div className="text-muted-foreground">
                  masuk bank {formatDateID(s.settlement_date)} · {s.days_apart != null ? `${s.days_apart} hari dari mutasi` : 'tanggal tak terbaca'}
                  {s.je_number ? ` · ${s.je_number} (${s.je_status})` : ' · belum dijurnal'}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-medium tabular-nums">{fmt(s.net_payout)}</div>
                {s.amount_match
                  ? <span className="text-[hsl(var(--success-text))] flex items-center gap-0.5 justify-end"><CheckCircle2 className="w-3 h-3" /> nominal sama</span>
                  : <span className="text-[hsl(var(--warning-text))]">selisih {fmt(s.amount_diff)}</span>}
              </div>
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
