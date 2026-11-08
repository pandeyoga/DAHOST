/**
 * ShiftSchedulerModule — Portal SDM › Shift › Jadwal otomatis & Pola jadwal.
 *
 * Standar UI/UX v2 (keputusan owner 8 Nov 2026): cetakan PageLayout (dulu kepala sendiri dengan ikon gradien +
 * tab buatan di dalam tab hub). Di hub Shift tiap bagian jadi tab hub sendiri (`bagian`); tanpa `bagian`
 * (menu lama "hr-shift-scheduler") → pil penyaring. Kartu berulang → TabelData + unduh Excel/CSV,
 * detail jadwal = popup, form = FormPopup, tanggal = DatePicker, istilah Inggris → Indonesia.
 * Data yang dikirim ke server tidak berubah. Daftar jadwal memuat sampai 500 (dulu batas bawaan API 20).
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, Trash2, Eye, Send, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/ui/checkbox';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import PageLayout from '../layout/PageLayout';
import { EmptyState, StatusBadge } from '../moduleAtoms';
import { useHrMasters, useActiveEmployees, useDepartmentFilterOptions } from './hrPickers';

const BE = process.env.REACT_APP_BACKEND_URL;
const STATUS_JADWAL = { draft: { label: 'Draf', tone: 'muted' }, published: { label: 'Terbit', tone: 'success' } };
const statusJadwal = (s) => STATUS_JADWAL[s] || { label: 'Lainnya', tone: 'default' };
const tgl = (v) => (v ? formatTanggalID(String(v).slice(0, 10)) : '');
const periode = (s) => `${tgl(s.start_date) || '…'} – ${tgl(s.end_date) || '…'}`;
const TEMPLATE_KOSONG = { name: '', start_time: '08:00', end_time: '16:00', required_skills: [], min_employees: 1, max_employees: 5 };

/**
 * @param bagian  'schedules' | 'templates' — dipakai hub Shift (satu tab hub per bagian).
 */
export default function ShiftSchedulerModule({ token, bagian }) {
  const [tabSendiri, setTabSendiri] = useState('schedules');
  const activeTab = bagian || tabSendiri;
  const [schedules, setSchedules] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [selectedSchedule, setSelectedSchedule] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [galat, setGalat] = useState('');

  // Template dialog
  const [showTemplateDialog, setShowTemplateDialog] = useState(false);
  const [templateForm, setTemplateForm] = useState(TEMPLATE_KOSONG);

  // Generate dialog
  const [showGenerateDialog, setShowGenerateDialog] = useState(false);
  const [generateForm, setGenerateForm] = useState({
    start_date: '',
    end_date: '',
    department: '',
    shift_templates: [],
    constraints: {
      max_hours_per_week: 48,
      min_rest_hours: 12,
      prefer_consecutive_days: true,
      balance_workload: true
    }
  });
  const setConstraint = (k, v) => setGenerateForm((f) => ({ ...f, constraints: { ...f.constraints, [k]: v } }));

  const headers = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  // Tahap 5 (2026-11-07): departemen dari master Struktur Organisasi + departemen karyawan. Dulu daftar tetap
  // berbahasa Inggris (Production/Warehouse/QC/Finishing) yang tidak cocok dengan data karyawan → jadwal kosong.
  const { units } = useHrMasters(token, { positions: false, shifts: false });
  const { employees: activeEmployees } = useActiveEmployees(token);
  const deptOptions = useDepartmentFilterOptions(units, activeEmployees);

  const fetchSchedules = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/schedules?limit=500`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setSchedules(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat jadwal: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const fetchTemplates = useCallback(async () => {
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/templates`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setTemplates(data?.data || []);
    } catch (e) {
      toast.error(`Gagal memuat pola jadwal: ${e.message}`);
    }
  }, [headers]);

  useEffect(() => {
    fetchSchedules();
    fetchTemplates();
  }, [fetchSchedules, fetchTemplates]);

  const bukaTemplate = () => { setGalat(''); setTemplateForm(TEMPLATE_KOSONG); setShowTemplateDialog(true); };
  const bukaGenerate = () => { setGalat(''); setShowGenerateDialog(true); };

  const handleCreateTemplate = async () => {
    if (!templateForm.name || !templateForm.start_time || !templateForm.end_time) {
      setGalat('Nama, jam mulai, dan jam selesai wajib diisi.');
      return;
    }
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/templates`, {
        method: 'POST',
        headers,
        body: JSON.stringify(templateForm)
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Pola jadwal dibuat');
      setShowTemplateDialog(false);
      setTemplateForm(TEMPLATE_KOSONG);
      fetchTemplates();
    } catch (e) {
      setGalat(`Gagal membuat pola jadwal: ${e.message}`);
    }
  };

  const handleDeleteTemplate = async (t) => {
    if (!(await confirmDialog({ title: `Hapus pola ${t.name}?`, body: 'Pola tidak bisa dipilih lagi saat membuat jadwal otomatis.', confirmLabel: 'Hapus', danger: true }))) return;
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/templates/${t.id}`, {
        method: 'DELETE',
        headers
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Pola jadwal dihapus');
      fetchTemplates();
    } catch (e) {
      toast.error(`Gagal menghapus pola jadwal: ${e.message}`);
    }
  };

  const handleGenerateSchedule = async () => {
    if (!generateForm.start_date || !generateForm.end_date || generateForm.shift_templates.length === 0) {
      setGalat('Isi tanggal mulai, tanggal selesai, dan pilih minimal 1 pola shift.');
      return;
    }
    setGenerating(true); setGalat('');
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/generate`, {
        method: 'POST',
        headers,
        body: JSON.stringify(generateForm)
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      toast.success('Jadwal dibuat sebagai draf');
      setShowGenerateDialog(false);
      fetchSchedules();
      setTabSendiri('schedules');
    } catch (e) {
      setGalat(`Gagal membuat jadwal: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const handlePublishSchedule = async (scheduleId) => {
    if (!(await confirmDialog({ title: 'Terbitkan jadwal ini?', body: 'Karyawan akan bisa melihat jadwal mereka.', confirmLabel: 'Terbitkan' }))) return;
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/schedules/${scheduleId}/publish`, {
        method: 'PATCH',
        headers
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast.success('Jadwal diterbitkan');
      setSelectedSchedule(null);
      fetchSchedules();
    } catch (e) {
      toast.error(`Gagal menerbitkan: ${e.message}`);
    }
  };

  const handleViewSchedule = async (scheduleId) => {
    try {
      const r = await fetch(`${BE}/api/hr/shift-scheduler/schedules/${scheduleId}`, { headers });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setSelectedSchedule(data?.data);
    } catch (e) {
      toast.error(`Gagal memuat rincian: ${e.message}`);
    }
  };

  // ─── Tabel ──────────────────────────────────────────────────────────────────
  const kolomJadwal = [
    { kunci: 'periode', label: 'Periode', hp: 'judul', isi: (s) => <span className="font-medium text-foreground">{periode(s)}</span> },
    { kunci: 'dept', label: 'Departemen', hp: 'keterangan', isi: (s) => s.department || 'Semua departemen' },
    { kunci: 'shift', label: 'Jumlah shift', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.metadata?.total_shifts ?? '—'}</span> },
    { kunci: 'jam', label: 'Rata-rata jam/karyawan', rata: 'kanan', isi: (s) => <span className="tabular-nums">{s.metadata?.average_hours_per_employee ?? '—'}</span> },
    { kunci: 'status', label: 'Status', isi: (s) => { const t = statusJadwal(s.status); return <StatusBadge status={s.status} label={t.label} tone={t.tone} />; } },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (s) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => handleViewSchedule(s.id)}><Eye />Lihat</Button>
        {s.status === 'draft' && (
          <Button size="sm" variant="outline" onClick={() => handlePublishSchedule(s.id)}><Send />Terbitkan</Button>
        )}
      </div>) },
  ];
  const unduhJadwal = [
    { label: 'Mulai', nilai: (s) => tgl(s.start_date) },
    { label: 'Selesai', nilai: (s) => tgl(s.end_date) },
    { label: 'Departemen', nilai: (s) => s.department || 'Semua departemen' },
    { label: 'Jumlah shift', nilai: (s) => s.metadata?.total_shifts ?? '' },
    { label: 'Rata-rata jam per karyawan', nilai: (s) => s.metadata?.average_hours_per_employee ?? '' },
    { label: 'Status', nilai: (s) => statusJadwal(s.status).label },
  ];

  const kolomPola = [
    { kunci: 'nama', label: 'Nama pola', hp: 'judul', isi: (t) => <span className="font-medium text-foreground">{t.name}</span> },
    { kunci: 'jam', label: 'Jam', hp: 'keterangan', isi: (t) => <span className="tabular-nums">{t.start_time}–{t.end_time}</span> },
    { kunci: 'orang', label: 'Karyawan per shift', rata: 'kanan', isi: (t) => <span className="tabular-nums">{t.min_employees}–{t.max_employees}</span> },
    { kunci: 'keahlian', label: 'Keahlian wajib', isi: (t) => (t.required_skills?.length ? t.required_skills.join(', ') : '—') },
    { kunci: 'aksi', label: '', rata: 'kanan', hp: 'aksi', isi: (t) => (
      <Button size="icon-sm" variant="ghost" onClick={() => handleDeleteTemplate(t)} aria-label="Hapus pola" title="Hapus pola">
        <Trash2 />
      </Button>) },
  ];
  const unduhPola = [
    { label: 'Nama pola', nilai: (t) => t.name },
    { label: 'Jam mulai', nilai: (t) => t.start_time },
    { label: 'Jam selesai', nilai: (t) => t.end_time },
    { label: 'Karyawan minimal', nilai: (t) => Number(t.min_employees ?? 0) },
    { label: 'Karyawan maksimal', nilai: (t) => Number(t.max_employees ?? 0) },
    { label: 'Keahlian wajib', nilai: (t) => (t.required_skills || []).join(', ') },
  ];

  const kolomRincian = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (x) => <span className="font-medium text-foreground">{x.employee_name}</span> },
    { kunci: 'dept', label: 'Departemen', isi: (x) => x.department || '—' },
    { kunci: 'tanggal', label: 'Tanggal', isi: (x) => tgl(x.date) || '—' },
    { kunci: 'shift', label: 'Shift', isi: (x) => x.shift_name || '—' },
    { kunci: 'jam', label: 'Jam', isi: (x) => <span className="tabular-nums">{x.start_time}–{x.end_time}</span> },
  ];

  const pil = !bagian && (
    <FilterChips value={tabSendiri} onChange={setTabSendiri} hideWhenEmpty={false} testId="scheduler-bagian"
      options={[{ key: 'schedules', label: 'Jadwal', count: schedules.length }, { key: 'templates', label: 'Pola jadwal', count: templates.length }]} />
  );

  return (
    <PageLayout testId="shift-scheduler-module" title="Jadwal shift otomatis"
      subtitle="Buat jadwal shift beberapa hari sekaligus dari pola shift, lalu terbitkan ke karyawan."
      actions={activeTab === 'schedules'
        ? <Button onClick={bukaGenerate} data-testid="scheduler-generate"><Plus />Buat jadwal otomatis</Button>
        : <Button onClick={bukaTemplate} data-testid="scheduler-template-add"><Plus />Pola baru</Button>}
      filters={pil}
      tools={<>
        {activeTab === 'schedules'
          ? <TombolUnduh namaBerkas="jadwal-shift" namaLembar="Jadwal" baris={schedules} kolom={unduhJadwal} testId="scheduler-unduh" />
          : <TombolUnduh namaBerkas="pola-jadwal-shift" namaLembar="Pola jadwal" baris={templates} kolom={unduhPola} testId="scheduler-template-unduh" />}
        <Button variant="outline" size="icon" onClick={() => { fetchSchedules(); fetchTemplates(); }} disabled={loading}
          title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>

      {activeTab === 'schedules' && (loading && schedules.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat jadwal…</p>
      ) : (
        <TabelData kolom={kolomJadwal} baris={schedules} testId="scheduler-table" onKlikBaris={(s) => handleViewSchedule(s.id)}
          kosong={<EmptyState title="Belum ada jadwal"
            description={templates.length ? 'Klik Buat jadwal otomatis untuk menyusun jadwal dari pola shift.' : 'Buat pola jadwal dulu di tab Pola jadwal, lalu buat jadwal otomatis.'} />} />
      ))}

      {activeTab === 'templates' && (
        <TabelData kolom={kolomPola} baris={templates} testId="scheduler-template-table"
          kosong={<EmptyState title="Belum ada pola jadwal"
            description="Pola berisi jam shift dan jumlah karyawan per shift, dipakai saat membuat jadwal otomatis."
            action={<Button onClick={bukaTemplate}><Plus />Pola baru</Button>} />} />
      )}

      {/* Form pola jadwal */}
      <FormPopup open={showTemplateDialog} onClose={() => setShowTemplateDialog(false)} ukuran="pendek" testId="scheduler-template-form"
        judul="Pola jadwal baru" keterangan="Dipakai saat membuat jadwal otomatis."
        onSimpan={handleCreateTemplate} galat={galat} labelSimpan="Buat pola">
        <Isian label="Nama pola" wajib htmlFor="tpl-name">
          <Input id="tpl-name" placeholder="Contoh: Shift pagi, Shift malam" value={templateForm.name}
            onChange={e => setTemplateForm({ ...templateForm, name: e.target.value })} />
        </Isian>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Jam mulai" wajib htmlFor="tpl-start">
            <Input id="tpl-start" type="time" value={templateForm.start_time}
              onChange={e => setTemplateForm({ ...templateForm, start_time: e.target.value })} />
          </Isian>
          <Isian label="Jam selesai" wajib htmlFor="tpl-end">
            <Input id="tpl-end" type="time" value={templateForm.end_time}
              onChange={e => setTemplateForm({ ...templateForm, end_time: e.target.value })} />
          </Isian>
          <Isian label="Karyawan minimal" htmlFor="tpl-min">
            <Input id="tpl-min" type="number" min="1" value={templateForm.min_employees}
              onChange={e => setTemplateForm({ ...templateForm, min_employees: parseInt(e.target.value) })} />
          </Isian>
          <Isian label="Karyawan maksimal" htmlFor="tpl-max">
            <Input id="tpl-max" type="number" min="1" value={templateForm.max_employees}
              onChange={e => setTemplateForm({ ...templateForm, max_employees: parseInt(e.target.value) })} />
          </Isian>
        </div>
      </FormPopup>

      {/* Form buat jadwal otomatis */}
      <FormPopup open={showGenerateDialog} onClose={() => setShowGenerateDialog(false)} ukuran="panjang" testId="scheduler-generate-form"
        judul="Buat jadwal shift otomatis" keterangan="Jadwal disimpan sebagai draf; terbitkan setelah diperiksa."
        onSimpan={handleGenerateSchedule} menyimpan={generating} galat={galat} labelSimpan="Buat jadwal">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Tanggal mulai" wajib>
            <DatePicker value={generateForm.start_date} onChange={v => setGenerateForm({ ...generateForm, start_date: v })} testId="sched-gen-start" />
          </Isian>
          <Isian label="Tanggal selesai" wajib>
            <DatePicker value={generateForm.end_date} min={generateForm.start_date || undefined}
              onChange={v => setGenerateForm({ ...generateForm, end_date: v })} testId="sched-gen-end" />
          </Isian>
        </div>
        <Isian label="Departemen" petunjuk="Kosong = semua departemen.">
          <SmartNativeSelect value={generateForm.department || ''} onChange={e => setGenerateForm({ ...generateForm, department: e.target.value })}
            data-testid="sched-gen-department" className="w-full">
            <option value="">Semua departemen</option>
            {deptOptions.map(d => <option key={d.value} value={d.value}>{d.legacy ? d.value : d.label}</option>)}
          </SmartNativeSelect>
        </Isian>
        <Isian label="Pola shift" wajib petunjuk={templates.length ? 'Pilih minimal 1.' : 'Belum ada pola — buat di tab Pola jadwal.'}>
          <div className="max-h-40 space-y-2 overflow-y-auto rounded-md border border-[var(--glass-border)] p-3">
            {templates.map(template => (
              <label key={template.id} className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
                <Checkbox checked={generateForm.shift_templates.includes(template.id)}
                  onCheckedChange={(v) => {
                    const newTemplates = v
                      ? [...generateForm.shift_templates, template.id]
                      : generateForm.shift_templates.filter(t => t !== template.id);
                    setGenerateForm({ ...generateForm, shift_templates: newTemplates });
                  }} />
                {template.name} ({template.start_time}–{template.end_time})
              </label>
            ))}
            {templates.length === 0 && <EmptyState title="Belum ada pola jadwal" className="py-4" />}
          </div>
        </Isian>
        <p className="text-base font-semibold text-foreground">Batasan</p>
        <label className="flex items-center justify-between gap-3 text-sm text-foreground">
          Seimbangkan beban kerja antarkaryawan
          <Switch checked={generateForm.constraints.balance_workload} onCheckedChange={v => setConstraint('balance_workload', v)} />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm text-foreground">
          Utamakan hari kerja berurutan
          <Switch checked={generateForm.constraints.prefer_consecutive_days} onCheckedChange={v => setConstraint('prefer_consecutive_days', v)} />
        </label>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Isian label="Maksimal jam per minggu" htmlFor="gen-max-hours">
            <Input id="gen-max-hours" type="number" value={generateForm.constraints.max_hours_per_week}
              onChange={e => setConstraint('max_hours_per_week', parseInt(e.target.value))} />
          </Isian>
          <Isian label="Minimal jam istirahat antarshift" htmlFor="gen-min-rest">
            <Input id="gen-min-rest" type="number" value={generateForm.constraints.min_rest_hours}
              onChange={e => setConstraint('min_rest_hours', parseInt(e.target.value))} />
          </Isian>
        </div>
      </FormPopup>

      {/* Rincian jadwal (popup) */}
      {selectedSchedule && (
        <DetailPopup open onClose={() => setSelectedSchedule(null)} testId="scheduler-detail"
          judul={`Jadwal ${periode(selectedSchedule)}`}
          status={(() => { const t = statusJadwal(selectedSchedule.status); return <StatusBadge status={selectedSchedule.status} label={t.label} tone={t.tone} />; })()}
          aksi={<>
            {selectedSchedule.shifts?.length > 0 && (
              <TombolUnduh namaBerkas={`jadwal-shift-${String(selectedSchedule.start_date || '').slice(0, 10)}`} namaLembar="Jadwal"
                baris={selectedSchedule.shifts} testId="scheduler-detail-unduh"
                kolom={[
                  { label: 'Karyawan', nilai: (x) => x.employee_name },
                  { label: 'Departemen', nilai: (x) => x.department || '' },
                  { label: 'Tanggal', nilai: (x) => tgl(x.date) },
                  { label: 'Shift', nilai: (x) => x.shift_name || '' },
                  { label: 'Jam mulai', nilai: (x) => x.start_time },
                  { label: 'Jam selesai', nilai: (x) => x.end_time },
                ]} />
            )}
            {selectedSchedule.status === 'draft' && (
              <Button size="sm" variant="success" onClick={() => handlePublishSchedule(selectedSchedule.id)}><Send />Terbitkan</Button>
            )}
          </>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Periode">{periode(selectedSchedule)}</BarisDetail>
            <BarisDetail label="Departemen">{selectedSchedule.department || 'Semua departemen'}</BarisDetail>
            <BarisDetail label="Jumlah shift">{selectedSchedule.shifts?.length ?? 0}</BarisDetail>
          </dl>
          <TabelData kolom={kolomRincian} baris={selectedSchedule.shifts || []} kunci={(x) => x.id} testId="scheduler-detail-table"
            kosong={<EmptyState title="Jadwal ini belum berisi shift" className="py-6" />} />
        </DetailPopup>
      )}
    </PageLayout>
  );
}
