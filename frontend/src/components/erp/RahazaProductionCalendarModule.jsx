/**
 * RahazaProductionCalendarModule — "Kalender libur" (Portal SDM, id `hr-holiday-calendar`).
 *
 * Tahap 9 (7 Nov 2026, keputusan owner): Master Proses (Portal Produksi) dihapus; kalender libur PINDAH KE SDM
 * karena dipakai menghitung hari cuti, pembagi gaji harian, dan absensi. Tetap SATU sumber: koleksi
 * `rahaza_production_calendar`, dibaca backend lewat `core.workdays.holidays_between` (cuti, payroll, jadwal) —
 * tidak ada kalender kedua. Tulis hanya peran SDM (+ owner/manager/admin).
 *
 * Tampilan: cetakan PageLayout + tabel per tahun (cari, jenis, halaman), tampilan bulan sebagai pilihan
 * (ViewToggle). Standar UI/UX v2 (8 Nov 2026): entri baru/ubah = FormPopup, kalkulator hari kerja = popup
 * (DetailPanel dengan onClose), tanggal = DatePicker, daftar = TabelData (kartu ringkas di HP), alat di ujung
 * baris penyaring supaya kepala tidak meluber di HP (dulu tombol "Entri baru" terdorong keluar layar).
 *
 *   GET/POST /api/rahaza/production-calendar · PUT/DELETE /api/rahaza/production-calendar/{id}
 *   POST /api/rahaza/production-calendar/seed-national?year= · GET …/working-days
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { CalendarDays, Calculator, ChevronLeft, ChevronRight, Pencil, Plus, RefreshCw, Search, Table2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { GlassCard } from '@/components/ui/glass';
import TabelData from '@/components/ui/tabel-data';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import ViewToggle from '@/components/ui/view-toggle';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiDelete, apiFetch, apiGet, apiPost, apiPut } from '../../lib/api';
import { todayWIB, thisMonthWIB, thisYearWIB } from '@/lib/waktu';
import { formatDateID } from '@/lib/format';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import { EmptyState, Notice, StatusBadge } from './moduleAtoms';
import ImportExportToolbar from './ImportExportToolbar';

const MONTHS = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const DAYS = ['Minggu', 'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu'];
const DAYS_SHORT = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab'];
const TYPE_LABEL = { holiday: 'Hari libur', exception: 'Hari kerja pengganti', special: 'Acara khusus' };
const TYPE_TONE = { holiday: 'danger', exception: 'warning', special: 'primary' };
const KIND_LABEL = { libur_nasional: 'Libur nasional', cuti_bersama: 'Cuti bersama' };
const VIEWS = [
  { key: 'table', label: 'Tampilan tabel', icon: Table2 },
  { key: 'month', label: 'Tampilan bulan', icon: CalendarDays },
];
const BLANK = { date: '', name: '', type: 'holiday', notes: '' };
const typeLabel = (e) => KIND_LABEL[e.kind] || TYPE_LABEL[e.type] || e.type;
const weekdayOf = (iso) => DAYS[new Date(`${iso}T00:00:00`).getDay()];
// cuti bersama bersifat fakultatif bagi swasta → boleh dihapus bila pabrik tetap bekerja
const deletable = (e) => e.created_by !== 'system' || e.kind === 'cuti_bersama';

function EntryForm({ entry, onClose, onSaved }) {
  const isEdit = !!entry?.id;
  const [form, setForm] = useState(() => ({ ...BLANK, ...(entry || {}) }));
  const [busy, setBusy] = useState(false);
  const [galat, setGalat] = useState('');
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target ? e.target.value : e }));
  const save = async () => {
    if (!form.date || !form.name.trim()) { setGalat('Tanggal dan nama wajib diisi.'); return; }
    setBusy(true); setGalat('');
    try {
      if (isEdit) await apiPut(`/rahaza/production-calendar/${entry.id}`, { name: form.name.trim(), type: form.type, notes: form.notes });
      else await apiPost('/rahaza/production-calendar', { date: form.date, name: form.name.trim(), type: form.type, notes: form.notes });
      toast.success(isEdit ? 'Entri kalender diperbarui' : 'Entri kalender ditambahkan');
      onSaved(form.date);
    } catch (e) { setGalat(e.message || 'Gagal menyimpan'); }
    finally { setBusy(false); }
  };
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="calendar-form" onSimpan={save} menyimpan={busy} galat={galat}
      judul={isEdit ? `Ubah entri ${formatDateID(entry.date)}` : 'Entri kalender baru'}
      keterangan="Hari libur mengurangi hari kerja: hari cuti, pembagi gaji harian, dan absensi ikut berubah."
      labelSimpan={isEdit ? 'Simpan perubahan' : 'Simpan'}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Isian label="Tanggal" wajib petunjuk={isEdit ? 'Tanggal tidak bisa diubah; hapus lalu buat entri baru.' : undefined}>
          <DatePicker value={form.date} onChange={set('date')} disabled={isEdit} bolehKosong={false} testId="cal-date" />
        </Isian>
        <Isian label="Jenis">
          <SmartNativeSelect value={form.type} onChange={set('type')} className="w-full" searchable={false} data-testid="cal-type" aria-label="Jenis">
            {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </SmartNativeSelect>
        </Isian>
      </div>
      <Isian label="Nama / keterangan" wajib htmlFor="cal-name">
        <Input id="cal-name" value={form.name} onChange={set('name')} placeholder="mis. Libur perusahaan" data-testid="cal-name" />
      </Isian>
      <Isian label="Catatan" htmlFor="cal-notes">
        <Input id="cal-notes" value={form.notes} onChange={set('notes')} data-testid="cal-notes" />
      </Isian>
    </FormPopup>
  );
}

function WorkdayCalculator({ onClose }) {
  const [from, setFrom] = useState(todayWIB());
  const [to, setTo] = useState(todayWIB());
  const [res, setRes] = useState(null);
  const calc = async () => {
    if (!from || !to) return;
    try { setRes(await apiGet(`/rahaza/production-calendar/working-days?from_date=${from}&to_date=${to}`)); }
    catch (e) { toast.error(e.message || 'Gagal menghitung'); }
  };
  return (
    <DetailPanel testId="calendar-workdays" onClose={onClose} title="Hitung hari kerja"
      description="Hari kerja = hari kalender dikurangi libur mingguan (Pengaturan Payroll) dan hari libur di kalender ini.">
      <div className="flex flex-wrap items-end gap-3">
        <Isian label="Dari" className="w-full sm:w-48"><DatePicker value={from} onChange={setFrom} bolehKosong={false} testId="wd-from" /></Isian>
        <Isian label="Sampai" className="w-full sm:w-48"><DatePicker value={to} onChange={setTo} min={from || undefined} bolehKosong={false} testId="wd-to" /></Isian>
        <Button variant="outline" onClick={calc} data-testid="calc-workdays-btn"><Calculator />Hitung</Button>
      </div>
      {res && (
        <p className="text-sm" data-testid="calc-workdays-result">
          <span className="font-semibold tabular-nums">{res.working_days} hari kerja</span> dari {res.total_calendar_days} hari kalender
          {' '}· {res.holidays} hari libur · {res.weekends_excluded} libur mingguan ({res.work_days_per_week} hari kerja per minggu).
        </p>
      )}
    </DetailPanel>
  );
}

function MonthView({ year, month, setMonth, setYear, entries }) {
  const entryMap = useMemo(() => Object.fromEntries(entries.map((e) => [e.date, e])), [entries]);
  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells = [...Array(firstDay).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];
  const today = todayWIB();
  const prev = () => { if (month === 1) { setMonth(12); setYear((y) => y - 1); } else setMonth((m) => m - 1); };
  const next = () => { if (month === 12) { setMonth(1); setYear((y) => y + 1); } else setMonth((m) => m + 1); };
  return (
    <GlassCard className="p-0 overflow-hidden" data-testid="calendar-month-view">
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--glass-border)]">
        <Button variant="outline" size="icon" onClick={prev} title="Bulan sebelumnya" aria-label="Bulan sebelumnya" data-testid="cal-prev"><ChevronLeft className="w-4 h-4" /></Button>
        <p className="font-semibold text-foreground">{MONTHS[month - 1]} {year}</p>
        <Button variant="outline" size="icon" onClick={next} title="Bulan berikutnya" aria-label="Bulan berikutnya" data-testid="cal-next"><ChevronRight className="w-4 h-4" /></Button>
      </div>
      <div className="grid grid-cols-7 border-b border-[var(--glass-border)]">
        {DAYS_SHORT.map((d) => <p key={d} className={`py-2 text-center text-xs font-semibold ${d === 'Min' ? 'text-[hsl(var(--danger-text))]' : 'text-muted-foreground'}`}>{d}</p>)}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((day, idx) => {
          if (!day) return <span key={`e-${idx}`} className="h-16 border-b border-r border-[var(--glass-border)]" />;
          const iso = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          const e = entryMap[iso];
          const sunday = new Date(year, month - 1, day).getDay() === 0;
          return (
            <div key={iso} className={`h-16 p-1 border-b border-r border-[var(--glass-border)] ${iso === today ? 'bg-[hsl(var(--primary)/0.06)]' : ''}`}>
              <p className={`text-xs font-medium text-center ${sunday ? 'text-[hsl(var(--danger-text))]' : 'text-foreground'}`}>{day}</p>
              {e && <p className={`mt-0.5 truncate text-xs leading-tight ${e.type === 'holiday' ? 'text-[hsl(var(--danger-text))]' : e.type === 'exception' ? 'text-[hsl(var(--warning-text))]' : 'text-[hsl(var(--primary))]'}`} title={e.name}>{e.name}</p>}
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}

export default function RahazaProductionCalendarModule() {
  const [year, setYear] = useState(thisYearWIB);
  const [month, setMonth] = useState(() => Number(thisMonthWIB().slice(5, 7)));
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [type, setType] = useState('');
  const [search, setSearch] = useState('');
  const [view, setView] = useState('table');
  const [panel, setPanel] = useState(null); // {mode:'new'|'edit', entry} | {mode:'calc'}
  const [seeding, setSeeding] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { const d = await apiGet(`/rahaza/production-calendar?year=${year}`); setEntries(Array.isArray(d) ? d : []); }
    catch (e) { setError(e.message || 'Gagal memuat kalender'); setEntries([]); }
    finally { setLoading(false); }
  }, [year]);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => ({
    all: entries.length, holiday: entries.filter((e) => e.type === 'holiday').length,
    exception: entries.filter((e) => e.type === 'exception').length, special: entries.filter((e) => e.type === 'special').length,
  }), [entries]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entries.filter((e) => (!type || e.type === type) && (!q || `${e.name} ${e.notes || ''}`.toLowerCase().includes(q)));
  }, [entries, type, search]);
  const { page, setPage, totalPages, total, paged, pageSize } = useClientPagination(filtered, 25);
  const years = useMemo(() => { const y = thisYearWIB(); return [y - 1, y, y + 1, y + 2]; }, []);

  // 2026-11-06 (pola P5): preset per tahun (tahun yang sedang dilihat). Tahun tanpa data dijelaskan di layar.
  const seedNational = async () => {
    setSeeding(true);
    try {
      const res = await apiFetch(`/rahaza/production-calendar/seed-national?year=${year}`, { method: 'POST' });
      const d = await res.json().catch(() => ({}));
      if (res.ok) {
        const extra = d.perkiraan ? ` ${d.perkiraan} tanggal mengikuti kalender keagamaan (perkiraan, cek SKB).` : '';
        setMsg({ tone: 'success', text: `${d.seeded} hari libur nasional & cuti bersama ${year} ditambahkan, ${d.skipped} sudah ada.${extra}` });
        await load();
      } else {
        setMsg({ tone: 'danger', text: d.detail || `Gagal mengisi libur nasional ${year}` });
      }
    } finally { setSeeding(false); }
  };
  const remove = async (e) => {
    if (!(await confirmDialog({ title: `Hapus "${e.name}" (${formatDateID(e.date)})?`,
      body: 'Tanggal ini kembali dihitung hari kerja untuk cuti, gaji harian, dan absensi.', confirmLabel: 'Hapus entri', danger: true }))) return;
    try { await apiDelete(`/rahaza/production-calendar/${e.id}`); toast.success('Entri kalender dihapus'); await load(); }
    catch (err) { toast.error(err.message || 'Gagal menghapus'); }
  };

  const catatan = (e) => String(e.notes || '').replace(/\s*·\s*Perkiraan, cek SKB.*$/, '');
  const kolom = [
    { kunci: 'tanggal', label: 'Tanggal', hp: 'judul', isi: (e) => (
      <span className="md:whitespace-nowrap">{formatDateID(e.date)}<span className="text-muted-foreground md:hidden"> · {weekdayOf(e.date)}</span></span>) },
    { kunci: 'hari', label: 'Hari', hp: false, isi: (e) => <span className="text-muted-foreground">{weekdayOf(e.date)}</span> },
    { kunci: 'nama', label: 'Nama', hp: 'keterangan', isi: (e) => <span className="font-medium text-foreground">{e.name}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (e) => <StatusBadge status={e.type} label={typeLabel(e)} tone={TYPE_TONE[e.type] || 'default'} /> },
    { kunci: 'catatan', label: 'Catatan', isi: (e) => (
      <div className="text-xs text-muted-foreground md:max-w-[22rem]">
        {e.perkiraan && <span className="block text-[hsl(var(--warning-text))]">Perkiraan, cek SKB</span>}
        <span className="block truncate" title={e.notes || ''}>{catatan(e) || (e.perkiraan ? '' : '—')}</span>
      </div>) },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (e) => (
      <div className="flex items-center justify-end gap-1 whitespace-nowrap">
        <Button variant="ghost" size="icon-sm" onClick={() => setPanel({ mode: 'edit', entry: e })} title="Ubah" aria-label="Ubah"
          data-testid={`edit-entry-${e.id}`}><Pencil /></Button>
        {deletable(e) && (
          <Button variant="ghost" size="icon-sm" onClick={() => remove(e)} title="Hapus" aria-label="Hapus"
            data-testid={`del-entry-${e.id}`}><Trash2 /></Button>
        )}
      </div>) },
  ];

  let detail = null;
  if (panel?.mode === 'calc') detail = <WorkdayCalculator onClose={() => setPanel(null)} />;
  else if (panel) {
    detail = <EntryForm entry={panel.entry} onClose={() => setPanel(null)}
      onSaved={async (iso) => { setPanel(null); const y = Number(String(iso).slice(0, 4)); if (y && y !== year) setYear(y); else await load(); }} />;
  }

  return (
    <PageLayout testId="production-calendar-page" title="Kalender libur"
      subtitle="Hari libur untuk hitung cuti, gaji harian, dan absensi."
      actions={<>
        <Button variant="outline" onClick={seedNational} disabled={seeding} data-testid="seed-national-btn">
          <RefreshCw className={seeding ? 'animate-spin' : ''} />{`Isi libur nasional ${year}`}
        </Button>
        <Button onClick={() => setPanel({ mode: 'new', entry: null })} data-testid="new-entry-btn"><Plus />Entri baru</Button>
      </>}
      filters={<>
        <SmartNativeSelect value={String(year)} onChange={(e) => setYear(Number(e.target.value))} className="h-9 w-28" searchable={false}
          data-testid="cal-year" aria-label="Tahun">
          {years.map((y) => <option key={y} value={String(y)}>{y}</option>)}
        </SmartNativeSelect>
        {view === 'table' && (
          <>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari nama libur" className="pl-8" data-testid="cal-search" />
            </div>
            <FilterChips value={type} onChange={setType} testId="cal-type-filter" ariaLabel="Jenis entri"
              options={[{ key: '', label: 'Semua', count: counts.all }, { key: 'holiday', label: 'Hari libur', count: counts.holiday },
                { key: 'exception', label: 'Hari kerja pengganti', count: counts.exception }, { key: 'special', label: 'Acara khusus', count: counts.special }]} />
          </>
        )}
        {/* Alat di ujung baris penyaring (bukan slot `tools`): di HP slot `tools` menyempitkan kotak cari. */}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          <Button variant="outline" onClick={() => setPanel({ mode: 'calc' })} data-testid="calc-open-btn"><Calculator />Hitung hari kerja</Button>
          <ImportExportToolbar collectionKey="holidays" label="Kalender libur" onImported={load} />
          <ViewToggle value={view} onChange={setView} options={VIEWS} testId="cal-view" />
        </div>
      </>}
      summary={<>
        {error && <Notice tone="danger" title="Gagal memuat kalender">{error}</Notice>}
        {msg && <Notice tone={msg.tone} title={msg.text} testId="cal-msg" />}
      </>}
      detail={detail}
      footer={view === 'table' && filtered.length > pageSize && <PaginationLite page={page} totalPages={totalPages} total={total} pageSize={pageSize} onPageChange={setPage} />}>
      {view === 'month' ? (
        <MonthView year={year} month={month} setMonth={setMonth} setYear={setYear} entries={entries} />
      ) : (
        loading && !entries.length ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Memuat kalender…</p>
        ) : (
          <TabelData kolom={kolom} baris={paged} testId="calendar-table"
            kosong={<EmptyState icon={CalendarDays} title={entries.length ? 'Tidak ada entri yang cocok' : `Belum ada entri kalender ${year}`}
              description={entries.length ? 'Ubah kata pencarian atau penyaring jenis.' : `Klik "Isi libur nasional ${year}" atau tambahkan entri sendiri.`} />} />
        )
      )}
    </PageLayout>
  );
}
