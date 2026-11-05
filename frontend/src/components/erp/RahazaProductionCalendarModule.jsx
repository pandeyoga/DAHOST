import { useState, useEffect, useCallback, useMemo } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Calendar, Plus, Trash2, ChevronLeft, ChevronRight, Calculator, RefreshCw } from 'lucide-react';
import { todayWIB, thisMonthWIB, thisYearWIB } from '@/lib/waktu';
import { Button } from '@/components/ui/button';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState, Notice } from './moduleAtoms';

const MONTHS = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'];
const DAYS_SHORT = ['Min','Sen','Sel','Rab','Kam','Jum','Sab'];

const TYPE_COLOR = {
  holiday: 'bg-[hsl(var(--destructive))] text-foreground',
  exception: 'bg-[hsl(var(--warning))] text-foreground',
  special: 'bg-[hsl(var(--primary))] text-foreground',
};
const TYPE_LABEL = { holiday: 'Hari Libur', exception: 'Pengecualian', special: 'Catatan Khusus' };
const TYPE_BADGE = {
  holiday: 'bg-[hsl(var(--destructive)/0.15)]  text-[hsl(var(--destructive))]  border-[hsl(var(--destructive)/0.35)] ',
  exception: 'bg-[hsl(var(--warning)/0.15)]  text-[hsl(var(--warning))]  border-[hsl(var(--warning)/0.35)] ',
  special: 'bg-[hsl(var(--primary)/0.15)]  text-[hsl(var(--primary))]  border-[hsl(var(--primary)/0.35)] ',
};

const BLANK = { date: '', name: '', type: 'holiday', notes: '' };

export default function RahazaProductionCalendarModule({ token }) {
  const [year, setYear] = useState(thisYearWIB);
  const [month, setMonth] = useState(() => Number(thisMonthWIB().slice(5, 7)));
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [workdayResult, setWorkdayResult] = useState(null);
  const [wdFrom, setWdFrom] = useState('');
  const [wdTo, setWdTo] = useState('');
  const [seeding, setSeeding] = useState(false);

  const hdrs = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/rahaza/production-calendar?year=${year}&month=${month}`, { headers: hdrs });
      if (res.ok) setEntries(await res.json());
    } finally {
      setLoading(false);
    }
  }, [year, month, hdrs]);

  useEffect(() => { load(); }, [load]);

  const entryMap = {};
  entries.forEach(e => { entryMap[e.date] = e; });

  // Build calendar days for current month
  const firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month, 0).getDate();
  const calendarCells = [];
  for (let i = 0; i < firstDay; i++) calendarCells.push(null);
  for (let d = 1; d <= daysInMonth; d++) calendarCells.push(d);

  const prevMonth = () => { if (month === 1) { setMonth(12); setYear(y => y - 1); } else setMonth(m => m - 1); };
  const nextMonth = () => { if (month === 12) { setMonth(1); setYear(y => y + 1); } else setMonth(m => m + 1); };

  const handleCreate = async () => {
    if (!form.date || !form.name) return setMsg({ type: 'error', text: 'Tanggal dan nama wajib diisi' });
    setSaving(true);
    try {
      const res = await fetch('/api/rahaza/production-calendar', {
        method: 'POST', headers: { ...hdrs, 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (res.ok) {
        setMsg({ type: 'success', text: 'Entri berhasil ditambahkan' });
        setShowForm(false);
        setForm(BLANK);
        await load();
      } else {
        const e = await res.json();
        setMsg({ type: 'error', text: e.detail || 'Gagal menyimpan' });
      }
    } finally {
      setSaving(false);
      setTimeout(() => setMsg(null), 4000);
    }
  };

  const handleDelete = async (id) => {
    if (!(await confirmDialog({ title: 'Hapus entri ini?', body: 'Entri kalender dihapus dari bulan ini.', confirmLabel: 'Hapus', danger: true }))) return;
    const res = await fetch(`/api/rahaza/production-calendar/${id}`, { method: 'DELETE', headers: hdrs });
    if (res.ok) { await load(); setMsg({ type: 'success', text: 'Entri dihapus' }); }
    setTimeout(() => setMsg(null), 3000);
  };

  const calcWorkdays = async () => {
    if (!wdFrom || !wdTo) return;
    const res = await fetch(`/api/rahaza/production-calendar/working-days?from_date=${wdFrom}&to_date=${wdTo}`, { headers: hdrs });
    if (res.ok) setWorkdayResult(await res.json());
  };

  const seedNational = async () => {
    setSeeding(true);
    try {
      const res = await fetch('/api/rahaza/production-calendar/seed-national', { method: 'POST', headers: hdrs });
      if (res.ok) {
        const d = await res.json();
        setMsg({ type: 'success', text: `${d.seeded} hari libur nasional 2026 ditambahkan` });
        await load();
      }
    } finally {
      setSeeding(false);
      setTimeout(() => setMsg(null), 4000);
    }
  };

  return (
    <div className="space-y-4" data-testid="production-calendar-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-semibold text-foreground">Kalender Produksi</h2>
          <p className="text-sm text-foreground/50 mt-0.5">Hari libur nasional & pengecualian produksi</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={seedNational} disabled={seeding}
            data-testid="seed-national-btn">
            <RefreshCw className={seeding ? 'animate-spin' : ''} />
            {seeding ? 'Memuat...' : 'Isi libur nasional 2026'}
          </Button>
          <Button onClick={() => setShowForm(v => !v)}
            data-testid="new-entry-btn">
            <Plus /> Tambah entri
          </Button>
        </div>
      </div>

      {/* Alert */}
      {msg && (
        <Notice tone={msg.type === 'success' ? 'success' : 'danger'} title={msg.text} />
      )}

      {/* Legend */}
      <div className="flex gap-3 flex-wrap">
        {Object.entries(TYPE_LABEL).map(([k, v]) => (
          <div key={k} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-sm ${k === 'holiday' ? 'bg-[hsl(var(--destructive))]' : k === 'exception' ? 'bg-[hsl(var(--warning))]' : 'bg-[hsl(var(--primary))]'}`} />
            <span className="text-xs text-foreground/60">{v}</span>
          </div>
        ))}
      </div>

      {/* Add Form */}
      {showForm && (
        <GlassCard className="p-4 space-y-4" data-testid="calendar-form">
          <h3 className="font-semibold text-foreground">Tambah Entri Kalender</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <label className="block text-xs font-medium text-foreground/60 mb-1">Tanggal</label>
              <GlassInput type="date" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                className="h-9"
                data-testid="cal-date" />
            </div>
            <div>
              <label className="block text-xs font-medium text-foreground/60 mb-1">Tipe</label>
              <SmartNativeSelect value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
                className="w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
                data-testid="cal-type">
                {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </SmartNativeSelect>
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-foreground/60 mb-1">Nama/Keterangan</label>
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="Contoh: Hari Raya Idul Fitri"
                className="w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
                data-testid="cal-name" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-foreground/60 mb-1">Catatan (opsional)</label>
            <input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              placeholder="Keterangan tambahan..."
              className="w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground"
              data-testid="cal-notes" />
          </div>
          <div className="flex gap-3 pt-1">
            <Button onClick={handleCreate} disabled={saving}
              data-testid="cal-submit-btn">
              {saving ? 'Menyimpan...' : 'Simpan'}
            </Button>
            <Button variant="outline" onClick={() => { setShowForm(false); setForm(BLANK); }}>
              Batal
            </Button>
          </div>
        </GlassCard>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Calendar */}
        <GlassCard className="xl:col-span-2 overflow-hidden">
          {/* Nav */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--glass-border)]">
            <Button variant="ghost" size="icon-sm" onClick={prevMonth} title="Bulan sebelumnya" aria-label="Bulan sebelumnya" data-testid="cal-prev">
              <ChevronLeft />
            </Button>
            <h3 className="font-semibold text-foreground">{MONTHS[month - 1]} {year}</h3>
            <Button variant="ghost" size="icon-sm" onClick={nextMonth} title="Bulan berikutnya" aria-label="Bulan berikutnya" data-testid="cal-next">
              <ChevronRight />
            </Button>
          </div>

          {/* Day headers */}
          <div className="grid grid-cols-7 border-b border-[var(--glass-border)]">
            {DAYS_SHORT.map(d => (
              <div key={d} className={`py-2 text-center text-xs font-semibold ${d === 'Min' ? 'text-[hsl(var(--destructive))] ' : 'text-foreground/50'}`}>{d}</div>
            ))}
          </div>

          {/* Days */}
          <div className="grid grid-cols-7">
            {calendarCells.map((day, idx) => {
              if (!day) return <div key={`empty-${idx}`} className="h-14 border-b border-r border-[var(--glass-border)]" />;
              const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
              const entry = entryMap[dateStr];
              const isSunday = new Date(year, month - 1, day).getDay() === 0;
              const isToday = dateStr === todayWIB();
              return (
                <div key={day}
                  className={`h-14 p-1 border-b border-r border-[var(--glass-border)] transition-colors relative
                    ${isToday ? 'bg-[hsl(var(--primary)/0.05)]' : ''}
                    ${isSunday ? 'bg-[hsl(var(--destructive)/0.15)] ' : ''}`}>
                  <div className={`text-xs font-medium w-6 h-6 rounded-full flex items-center justify-center mx-auto
                    ${isToday ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : isSunday ? 'text-[hsl(var(--destructive))] ' : 'text-foreground/70'}`}>
                    {day}
                  </div>
                  {entry && (
                    <div className={`mt-0.5 px-1 py-0.5 rounded text-[9px] leading-tight truncate ${TYPE_COLOR[entry.type] || 'bg-foreground/20 text-foreground'}`}
                      title={entry.name}>
                      {entry.name}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {loading && (
            <div className="text-center py-4 text-foreground/40 text-sm">Memuat...</div>
          )}
        </GlassCard>

        {/* Right Panel */}
        <div className="space-y-4">
          {/* Working Days Calculator */}
          <GlassCard className="p-4 space-y-4">
            <div className="flex items-center gap-2">
              <Calculator className="w-4 h-4 text-[hsl(var(--primary))]" />
              <h3 className="font-semibold text-foreground text-sm">Kalkulator Hari Kerja</h3>
            </div>
            <div className="space-y-2">
              <div>
                <label className="block text-xs text-foreground/50 mb-1">Dari</label>
                <GlassInput type="date" value={wdFrom} onChange={e => setWdFrom(e.target.value)}
                  className="h-9"
                  data-testid="wd-from" />
              </div>
              <div>
                <label className="block text-xs text-foreground/50 mb-1">Sampai</label>
                <GlassInput type="date" value={wdTo} onChange={e => setWdTo(e.target.value)}
                  className="h-9"
                  data-testid="wd-to" />
              </div>
              <Button variant="outline" onClick={calcWorkdays} className="w-full"
                data-testid="calc-workdays-btn">
                Hitung
              </Button>
            </div>
            {workdayResult && (
              <div className="p-3 rounded-lg bg-[var(--card-surface)] space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-foreground/50">Total hari kalender</span>
                  <span className="tabular-nums text-foreground">{workdayResult.total_calendar_days}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-foreground/50">Hari libur</span>
                  <span className="tabular-nums text-[hsl(var(--destructive))] ">{workdayResult.holidays}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-foreground/50">Akhir pekan</span>
                  <span className="tabular-nums text-[hsl(var(--warning))] ">{workdayResult.weekends_excluded}</span>
                </div>
                <div className="flex justify-between border-t border-[var(--glass-border)] pt-1.5 mt-1.5">
                  <span className="font-semibold text-foreground">Hari kerja efektif</span>
                  <span className="tabular-nums font-bold text-[hsl(var(--success))] ">{workdayResult.working_days}</span>
                </div>
              </div>
            )}
          </GlassCard>

          {/* Month Entries List */}
          <GlassCard className="p-4">
            <h3 className="font-semibold text-foreground text-sm mb-3">
              {MONTHS[month - 1]} {year} · {entries.length} entri
            </h3>
            {entries.length === 0 ? (
              <EmptyState icon={Calendar} className="py-4" title="Tidak ada entri bulan ini"
                description="Klik Tambah entri untuk mencatat hari libur atau pengecualian." />
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto">
                {entries.map(e => (
                  <div key={e.id} className="flex items-start gap-2" data-testid={`cal-entry-${e.id}`}>
                    <div className="text-right shrink-0 w-6">
                      <p className="text-xs font-bold text-foreground">{e.day}</p>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-foreground truncate">{e.name}</p>
                      <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] border ${TYPE_BADGE[e.type]}`}>{TYPE_LABEL[e.type]}</span>
                    </div>
                    {e.created_by !== 'system' && (
                      <Button variant="ghost" size="icon-sm" onClick={() => handleDelete(e.id)}
                        className="shrink-0 text-foreground/30 hover:text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.15)]"
                        data-testid={`del-entry-${e.id}`} title="Hapus" aria-label="Hapus">
                        <Trash2 />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
