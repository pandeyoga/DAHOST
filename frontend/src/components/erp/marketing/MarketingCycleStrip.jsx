import { useEffect, useState, useMemo } from 'react';
import { Info } from 'lucide-react';
import { formatRupiah } from '@/lib/format';
import { StatTile } from '../moduleAtoms';

// FASE D (2026-08-16) — angka RESMI satu bulan kerja marketing, diambil apa adanya
// dari SSOT `core/marketing_cycle.py` lewat `GET /api/marketing/cycle/overview`.
//
// Kenapa tidak dihitung di layar ini: target, omzet, anggaran, dan ROI dipakai
// bersama oleh Portal Marketing, Portal Manajemen, dan lampiran ekspor. Begitu
// browser ikut menjumlah, tiga tempat itu bisa menampilkan tiga angka untuk satu
// pertanyaan yang sama — dan yang salah tidak akan pernah kelihatan salah.
// Semua penjumlahan, peringkat, dan persentase di bawah datang dari `totals`.

const API_BASE = process.env.REACT_APP_BACKEND_URL;

const compact = (n) => {
  const v = Number(n || 0);
  if (v >= 1_000_000_000) return `Rp ${(v / 1_000_000_000).toFixed(1)}M`;
  if (v >= 1_000_000) return `Rp ${(v / 1_000_000).toFixed(1)}jt`;
  if (v >= 1_000) return `Rp ${(v / 1_000).toFixed(0)}rb`;
  return formatRupiah(v);
};

const monthLabel = (period) => {
  if (!period) return '';
  const [y, m] = period.split('-');
  const names = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
    'Agustus', 'September', 'Oktober', 'November', 'Desember'];
  return `${names[Number(m) - 1] || m} ${y}`;
};

export function MarketingCycleStrip({ token, period }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  useEffect(() => {
    if (!period) return;
    let alive = true;
    setErr('');
    fetch(`${API_BASE}/api/marketing/cycle/overview?period=${period}`, { headers })
      .then(async (r) => {
        if (!r.ok) throw new Error(`gagal memuat siklus (HTTP ${r.status})`);
        return r.json();
      })
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [period, headers]);

  if (err) {
    return (
      <p className="text-sm text-[hsl(var(--danger-text))]" data-testid="cycle-strip-error">
        Angka siklus bulan {monthLabel(period)} tidak bisa dimuat: {err}
      </p>
    );
  }
  if (!data) {
    return <p className="text-sm text-muted-foreground" data-testid="cycle-strip-loading">Memuat angka siklus bulan {monthLabel(period)}…</p>;
  }

  const t = data.totals || {};
  const attention = data.attention || [];
  const adaTarget = Number(t.target_revenue || 0) > 0;
  const adaAnggaran = Number(t.total_plan || 0) > 0;
  const adaBiaya = Number(t.total_spend || 0) > 0;
  const pct1 = (v) => `${Number(v || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })}%`;
  // Persen tanpa pembanding (target/anggaran 0) = "—" + alasan, bukan 0,0% merah (Standar UI/UX v2 #9).
  const revAccent = !adaTarget ? 'default' : t.revenue_pct >= t.pace_pct ? 'success' : (t.revenue_pct >= t.pace_pct * 0.7 ? 'warning' : 'danger');
  const budgetAccent = !adaAnggaran ? 'default' : t.total_used_pct >= 100 ? 'danger' : (t.total_used_pct >= 80 ? 'warning' : 'default');

  return (
    <div className="space-y-2" data-testid="marketing-cycle-strip">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-base font-semibold">Siklus {monthLabel(period)} — angka resmi</p>
        <span className="text-sm text-muted-foreground" data-testid="cycle-strip-progress">
          Hari ke-{data.progress?.days_elapsed} dari {data.progress?.days_total} · {t.accounts} toko · {t.accounts_with_target} bertarget
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile testId="cycle-target" label="Omzet terhadap target" accent={revAccent}
          value={adaTarget ? pct1(t.revenue_pct) : '—'}
          sub={adaTarget
            ? `${compact(t.revenue)} dari ${compact(t.target_revenue)} · laju bulan ${pct1(t.pace_pct)}`
            : `Belum ada target bulan ini · omzet ${compact(t.revenue)}`} />
        <StatTile testId="cycle-budget" label="Anggaran terpakai" accent={budgetAccent}
          value={adaAnggaran ? pct1(t.total_used_pct) : '—'}
          sub={adaAnggaran
            ? `${compact(t.total_spend)} dari ${compact(t.total_plan)} · sisa ${compact(t.total_remaining)}`
            : `Belum ada rencana anggaran · terpakai ${compact(t.total_spend)}`} />
        <StatTile testId="cycle-roas" label="ROAS · ROI"
          accent={!adaBiaya ? 'default' : t.roi_reliable ? (t.roi_pct >= 0 ? 'success' : 'danger') : 'warning'}
          value={adaBiaya ? `${Number(t.roas || 0).toLocaleString('id-ID', { maximumFractionDigits: 2 })}×` : '—'}
          sub={!adaBiaya ? 'Belum ada biaya iklan bulan ini'
            : t.roi_reliable
              ? `ROI ${pct1(t.roi_pct)} · laba kotor ${compact(t.gross_profit)}`
              : `ROI belum bisa dipercaya — HPP baru ${pct1(t.hpp_coverage_pct)} unit`} />
        <StatTile testId="cycle-attention" label="Perlu perhatian"
          accent={(t.flags_red ?? 0) > 0 ? 'danger' : ((t.flags_yellow ?? 0) > 0 ? 'warning' : 'default')}
          value={`${t.flags_red ?? 0} merah`}
          sub={`${t.flags_yellow ?? 0} kuning · ${attention.length} toko ditandai`} />
      </div>
      {attention.length > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="cycle-attention-list">
          Toko ditandai (peringkat dari server):{' '}
          {attention.slice(0, 6).map((a, i) => (
            <span key={a.account_id} data-testid={`cycle-attention-${a.account_code || a.account_id}`}>
              {i > 0 && ' · '}<span className="text-foreground">{a.account_name}</span> ({a.flags.length} tanda)
            </span>
          ))}
          {attention.length > 6 ? ` · +${attention.length - 6} lainnya` : ''}
        </p>
      )}
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="cycle-strip-note">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span title={String(data.label || '').replace(/Pencairan\s*\/\s*Settlement/gi, 'Pencairan')}>
          Angka siklus = rekap sebulan penuh (omzet sebelum potongan platform, menghormati koreksi SPV); kartu periode
          di bawah = input harian pada rentang yang dipilih, jadi bisa berbeda.
        </span>
      </p>
    </div>
  );
}

export default MarketingCycleStrip;
