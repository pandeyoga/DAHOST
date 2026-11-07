/**
 * KPIGamificationTab — P3 Gamification: papan peringkat, lencana, pencapaian, ringkasan.
 * Dipakai di HRKPIModule (SDM, isHR) dan KPIPortalModule (portal karyawan) — props & ekspor `BadgeChip` tetap.
 *
 * Standar UI/UX v2 (8 Nov 2026): papan peringkat & katalog = tabel + unduh Excel/CSV (dulu kartu berulang &
 * podium dekoratif), kartu angka StatTile, tab standar (di dalam hub tampil sebagai pil), tanpa emoji hiasan dan
 * warna hex (ikon lencana dari data tetap tampil), bahasa Indonesia.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import axios from 'axios';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { formatDateID } from '@/lib/format';
import { EmptyState, StatTile, StatusBadge } from './moduleAtoms';

const B = process.env.REACT_APP_BACKEND_URL;
const GRADE_TONE = { A: 'success', B: 'info', C: 'warning', D: 'warning', E: 'danger' };

// ─── Lencana (ekspor dipakai KPIPortalModule) ─────────────────────────────────
export function BadgeChip({ badge, size = 'sm' }) {
  const sizeClass = size === 'lg' ? 'text-base px-3 py-1.5 gap-2' : 'text-sm px-2.5 py-1 gap-1.5';
  return (
    <span className={`inline-flex items-center rounded-full border border-[var(--glass-border)] bg-[var(--card-surface)] font-medium text-foreground ${sizeClass}`}
      title={badge.badge_desc || badge.badge_label}>
      {badge.badge_emoji && <span aria-hidden="true">{badge.badge_emoji}</span>}
      <span>{badge.badge_label}</span>
      {badge.count > 1 && <span className="tabular-nums text-muted-foreground">×{badge.count}</span>}
    </span>
  );
}

// ─── Papan peringkat ──────────────────────────────────────────────────────────
function LeaderboardTable({ entries }) {
  const kolom = [
    { kunci: 'rank', label: 'Peringkat', isi: (e) => (e.rank <= 3
      ? <StatusBadge status={`rank-${e.rank}`} label={`Juara ${e.rank}`} tone="primary" />
      : <span className="font-semibold tabular-nums text-muted-foreground">{e.rank}</span>) },
    { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (e) => (
      <div className="min-w-0"><p className="font-medium text-foreground">{e.employee_name}</p>
        <p className="text-xs text-muted-foreground">{e.employee_code}{e.department ? ` · ${e.department}` : ''}</p></div>) },
    { kunci: 'lencana', label: 'Lencana', isi: (e) => (e.badges?.length
      ? <span className="text-sm" title={e.badges.map(b => b.badge_label).join(', ')}>
          {e.badges.slice(0, 3).map(b => b.badge_emoji).join(' ')}{e.badges.length > 3 ? ` +${e.badges.length - 3}` : ''}
        </span>
      : <span className="text-muted-foreground">—</span>) },
    { kunci: 'skor', label: 'Skor', rata: 'kanan', isi: (e) => <span className="font-semibold tabular-nums">{e.score}</span> },
    { kunci: 'delta', label: 'Perubahan', rata: 'kanan', isi: (e) => (e.delta === null || e.delta === undefined
      ? <span className="text-muted-foreground">—</span>
      : <span className={`tabular-nums ${e.delta >= 0 ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}`}>{e.delta >= 0 ? `+${e.delta}` : `−${Math.abs(e.delta)}`}</span>) },
    { kunci: 'grade', label: 'Grade', isi: (e) => (e.grade ? <StatusBadge status={`grade-${e.grade}`} label={e.grade} tone={GRADE_TONE[e.grade] || 'default'} /> : '—') },
  ];
  return <TabelData kolom={kolom} baris={entries} kunci={(e) => e.employee_id} testId="kpi-leaderboard" />;
}

// ─── Pencapaian satu karyawan ─────────────────────────────────────────────────
function AchievementPanel({ employeeId, token }) {
  const [data, setData] = useState(null);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  useEffect(() => {
    if (!employeeId) return;
    axios.get(`${B}/api/dewi/kpi/achievements/${employeeId}`, { headers })
      .then(r => setData(r.data))
      .catch(console.error);
  }, [employeeId, headers]);

  if (!data) return <p className="py-4 text-center text-sm text-muted-foreground">Memuat pencapaian…</p>;
  if (data.total === 0) return <EmptyState title="Belum ada lencana" description="Ikuti penilaian KPI untuk mendapatkan lencana." />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">{data.summary.map(s => <BadgeChip key={s.badge_type} badge={s} size="lg" />)}</div>
      <TabelData baris={data.badges} kunci={(b) => `${b.badge_type}-${b.earned_at}`} testId="kpi-achievements"
        kolom={[
          { kunci: 'lencana', label: 'Lencana', hp: 'judul', isi: (b) => <BadgeChip badge={b} /> },
          { kunci: 'desk', label: 'Keterangan', isi: (b) => <span className="text-sm text-muted-foreground">{b.badge_desc}</span> },
          { kunci: 'tgl', label: 'Diraih', isi: (b) => <span className="text-sm">{b.earned_at ? formatDateID(b.earned_at) : '—'}</span> },
        ]} />
    </div>
  );
}

// ─── Ringkasan (SDM) ──────────────────────────────────────────────────────────
function GamificationSummaryPanel({ token }) {
  const [data, setData] = useState(null);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  useEffect(() => {
    axios.get(`${B}/api/dewi/kpi/gamification/summary`, { headers })
      .then(r => setData(r.data))
      .catch(console.error);
  }, [headers]);

  if (!data) return <p className="py-4 text-center text-sm text-muted-foreground">Memuat ringkasan…</p>;
  const top = data.top_earners?.[0];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Lencana diberikan" value={data.total_badges_awarded ?? 0} sub="Semua karyawan, semua periode." />
        <StatTile label="Jenis lencana" value={data.badge_types_available ?? 0} sub="Lencana yang bisa diraih." />
        <StatTile label="Peraih terbanyak" value={top?.employee_name?.split(' ')[0] || '—'} sub={top ? top.employee_name : 'Belum ada lencana.'} />
        <StatTile label="Lencana terbanyak" value={top?.badge_count || 0} sub="Milik peraih terbanyak." />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Sebaran lencana</p>
            <TombolUnduh namaBerkas="sebaran-lencana" namaLembar="Sebaran" baris={data.badge_distribution}
              kolom={[{ label: 'Lencana', nilai: (b) => b.badge_label }, { label: 'Jumlah', nilai: (b) => b.count }]} />
          </div>
          <TabelData baris={data.badge_distribution} kunci={(b) => b.badge_type} testId="kpi-badge-dist"
            kolom={[
              { kunci: 'lencana', label: 'Lencana', hp: 'judul', isi: (b) => <BadgeChip badge={b} /> },
              { kunci: 'jumlah', label: 'Jumlah', rata: 'kanan', isi: (b) => <span className="tabular-nums">{b.count}</span> },
              { kunci: 'porsi', label: 'Porsi', rata: 'kanan', isi: (b) => (
                <span className="tabular-nums text-muted-foreground">{Math.round((b.count / (data.total_badges_awarded || 1)) * 100)}%</span>) },
            ]}
            kosong={<p className="text-sm text-muted-foreground">Lencana belum diberikan.</p>} />
        </section>
        <section className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-foreground">Peraih lencana terbanyak</p>
            <TombolUnduh namaBerkas="peraih-lencana" namaLembar="Peraih" baris={data.top_earners}
              kolom={[{ label: 'Karyawan', nilai: (e) => e.employee_name }, { label: 'Kode', nilai: (e) => e.employee_code }, { label: 'Lencana', nilai: (e) => e.badge_count }]} />
          </div>
          <TabelData baris={data.top_earners} kunci={(e) => e.employee_id || e.employee_code} testId="kpi-top-earners"
            kolom={[
              { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (e) => (
                <div><p className="font-medium text-foreground">{e.employee_name}</p><p className="text-xs text-muted-foreground">{e.employee_code}</p></div>) },
              { kunci: 'n', label: 'Lencana', rata: 'kanan', isi: (e) => <span className="tabular-nums">{e.badge_count}</span> },
            ]}
            kosong={<p className="text-sm text-muted-foreground">Data belum tersedia.</p>} />
        </section>
      </div>

      {data.recent_badges.length > 0 && (
        <section className="space-y-2">
          <p className="text-sm font-semibold text-foreground">Lencana terbaru</p>
          <TabelData baris={data.recent_badges.slice(0, 6)} kunci={(b) => `${b.employee_name}-${b.badge_type}-${b.earned_at}`} testId="kpi-recent-badges"
            kolom={[
              { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (b) => <span className="font-medium text-foreground">{b.employee_name}</span> },
              { kunci: 'lencana', label: 'Lencana', isi: (b) => <BadgeChip badge={b} /> },
              { kunci: 'tgl', label: 'Diraih', isi: (b) => <span className="text-sm">{b.earned_at ? formatDateID(b.earned_at) : '—'}</span> },
            ]} />
        </section>
      )}
    </div>
  );
}

const KATALOG = [
  { key: 'gold_medal', label: 'Juara 1', emoji: '🥇', desc: 'Peringkat 1 pada periode KPI' },
  { key: 'silver_medal', label: 'Juara 2', emoji: '🥈', desc: 'Peringkat 2 pada periode KPI' },
  { key: 'bronze_medal', label: 'Juara 3', emoji: '🥉', desc: 'Peringkat 3 pada periode KPI' },
  { key: 'perfect_score', label: 'Nilai sempurna', emoji: '⭐', desc: 'KPI final ≥ 95' },
  { key: 'grade_a', label: 'Grade A', emoji: '💎', desc: 'KPI grade A (91–100)' },
  { key: 'most_improved', label: 'Paling meningkat', emoji: '📈', desc: 'Kenaikan skor terbesar dari periode sebelumnya' },
  { key: 'consistent_top', label: 'Konsisten terbaik', emoji: '🔥', desc: 'Masuk 3 besar pada 3 periode berturut-turut atau lebih' },
  { key: 'goal_crusher', label: 'Pencapai target', emoji: '🎯', desc: 'Semua target KPI tercapai' },
  { key: 'top_performer', label: 'Kinerja puncak', emoji: '💪', desc: 'KPI final ≥ 90' },
];

// ─── Utama ────────────────────────────────────────────────────────────────────
export default function KPIGamificationTab({ token, periods = [], isHR = true }) {
  const [activeTab, setActiveTab] = useState('leaderboard');
  const [selectedPeriodId, setSelectedPeriodId] = useState('overall');
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const headers = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const finishedPeriods = periods.filter(p => ['finalized', 'closed'].includes(p.status));

  const loadLeaderboard = useCallback(async () => {
    setLoading(true);
    try {
      if (selectedPeriodId === 'overall') {
        const r = await axios.get(`${B}/api/dewi/kpi/leaderboard`, { headers });
        const data = r.data.leaderboard || [];
        setLeaderboard(data.map(e => ({ ...e, score: e.avg_score, delta: null, grade: null, badges: [] })));
      } else {
        const r = await axios.get(`${B}/api/dewi/kpi/leaderboard/${selectedPeriodId}`, { headers });
        setLeaderboard(r.data.leaderboard || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [selectedPeriodId, headers]);

  useEffect(() => { loadLeaderboard(); }, [loadLeaderboard]);

  const seedDemo = async () => {
    setSeeding(true);
    try {
      const r = await axios.post(`${B}/api/dewi/kpi/gamification/seed-demo`, {}, { headers });
      toast.success(r.data.message || 'Data contoh dimuat');
      await loadLeaderboard();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Gagal memuat data contoh');
    } finally { setSeeding(false); }
  };

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <TabsList>
          <TabsTrigger value="leaderboard">Peringkat</TabsTrigger>
          {isHR && <TabsTrigger value="summary">Ringkasan</TabsTrigger>}
          <TabsTrigger value="badges">Katalog lencana</TabsTrigger>
        </TabsList>
        {isHR && (
          <Button variant="outline" size="sm" onClick={seedDemo} disabled={seeding} title="Buat periode contoh, hasil KPI, dan lencana">
            {seeding ? 'Menyiapkan data…' : 'Muat contoh data KPI'}
          </Button>
        )}
      </div>

      <TabsContent value="leaderboard" className="mt-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <SmartNativeSelect value={selectedPeriodId} onChange={e => setSelectedPeriodId(e.target.value)} className="w-56" aria-label="Periode">
              <option value="overall">Sepanjang waktu (rata-rata)</option>
              {finishedPeriods.map(p => <option key={p.period_id || p.id} value={p.period_id || p.id}>{p.title || p.name}</option>)}
            </SmartNativeSelect>
            <Button variant="outline" size="icon" onClick={loadLeaderboard} disabled={loading} title="Muat ulang peringkat" aria-label="Muat ulang peringkat">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
          </div>
          <TombolUnduh namaBerkas="peringkat-kpi" namaLembar="Peringkat" baris={leaderboard} testId="kpi-unduh-peringkat"
            kolom={[
              { label: 'Peringkat', nilai: (e) => e.rank }, { label: 'Karyawan', nilai: (e) => e.employee_name },
              { label: 'Kode', nilai: (e) => e.employee_code || '' }, { label: 'Departemen', nilai: (e) => e.department || '' },
              { label: 'Skor', nilai: (e) => e.score }, { label: 'Perubahan', nilai: (e) => (e.delta ?? '') },
              { label: 'Grade', nilai: (e) => e.grade || '' }, { label: 'Lencana', nilai: (e) => (e.badges || []).map(b => b.badge_label).join(', ') },
            ]} />
        </div>
        {loading && leaderboard.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">Memuat peringkat…</p>
          : leaderboard.length === 0 ? (
            <EmptyState title="Belum ada data peringkat"
              description={isHR ? 'Peringkat muncul setelah hasil KPI dihitung. Bisa juga coba dengan "Muat contoh data KPI".' : 'Peringkat muncul setelah hasil KPI diterbitkan.'} />
          ) : <LeaderboardTable entries={leaderboard} />}
      </TabsContent>

      {isHR && (
        <TabsContent value="summary" className="mt-0"><GamificationSummaryPanel token={token} /></TabsContent>
      )}

      <TabsContent value="badges" className="mt-0">
        <TabelData baris={KATALOG} kunci={(b) => b.key} testId="kpi-badge-catalog"
          kolom={[
            { kunci: 'lencana', label: 'Lencana', hp: 'judul', isi: (b) => <BadgeChip badge={{ badge_emoji: b.emoji, badge_label: b.label, badge_desc: b.desc }} /> },
            { kunci: 'syarat', label: 'Cara meraih', isi: (b) => <span className="text-sm text-muted-foreground">{b.desc}</span> },
          ]} />
      </TabsContent>
    </Tabs>
  );
}

export { AchievementPanel };
