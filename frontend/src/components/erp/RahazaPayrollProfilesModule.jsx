/**
 * Profil gaji (tab di hub Penggajian) — skema & tarif tiap karyawan.
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout, penyaring satu baris (cari + pil skema berangka — pengganti
 * 5 kartu angka yang mengulang hitungan yang sama), daftar = TabelData (kartu ringkas di HP) + unduh Excel/CSV,
 * form = FormPopup standar, pemilih tanggal seragam. API, isian, dan data yang dikirim TIDAK berubah.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { Ban, Pencil, Plus, RefreshCw, Search, Trash2, Users } from 'lucide-react';
import { toast } from 'sonner';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { apiDelete } from '@/lib/api';
import { hapusMaster } from '@/lib/hapusMaster';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import FilterChips from '@/components/ui/filter-chips';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker, { formatTanggalID } from '@/components/ui/date-picker';
import PaginationLite, { useClientPagination } from '@/components/ui/pagination-lite';
import { MoneyInput } from '@/components/ui/money-input';
import { formatRupiah } from '@/lib/format';
import PageLayout from './layout/PageLayout';
import { EmptyState, Notice } from './moduleAtoms';
import ImportExportToolbar from './ImportExportToolbar';
import { EmployeeSelect } from './hr/hrPickers';

const SCHEMES = [
  { code: 'monthly', label: 'Bulanan', satuan: 'bulan' },
  { code: 'weekly', label: 'Mingguan', satuan: 'minggu' },
  { code: 'hourly', label: 'Borongan jam', satuan: 'jam' },
  { code: 'pcs', label: 'Borongan pcs', satuan: 'pcs' },
];
const SCHEME_META = Object.fromEntries(SCHEMES.map(s => [s.code, s]));
const skemaLabel = (code) => SCHEME_META[code]?.label || 'Bulanan';
const overrideLabel = (p) => ((p.pcs_process_rates || []).length > 0 ? `${p.pcs_process_rates.length} proses` : '—');

// 2026-11-07 (HR2): isian "tipe periode / hari mulai minggu / tanggal mulai bulan" DISEMBUNYIKAN — tidak dipakai
// menghitung gaji (periode gaji ikut proses payroll). Nilai yang sudah tersimpan tidak dikirim ulang, jadi tidak
// berubah (server membiarkannya bila tidak dikirim).

export default function RahazaPayrollProfilesModule({ token }) {
  const [profiles, setProfiles] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [processes, setProcesses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [skema, setSkema] = useState('');
  const [cari, setCari] = useState('');

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [p, e, pr] = await Promise.all([
        fetch('/api/rahaza/payroll-profiles', { headers }).then(r => r.json()),
        // 2026-11-07 (Tahap 5): dulu tanpa limit → batas bawaan API 50 baris; karyawan ke-51 dst. tidak bisa dipilih
        fetch('/api/rahaza/employees?active_only=true&limit=500', { headers }).then(r => r.json()),
        fetch('/api/rahaza/processes', { headers }).then(r => r.json()),
      ]);
      setProfiles(Array.isArray(p) ? p : []);
      setEmployees(Array.isArray(e) ? e : (e.items || e.rows || []));
      setProcesses(Array.isArray(pr) ? pr : []);
    } catch { setError('Gagal memuat data'); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const save = async (body) => {
    setFormError('');
    setSaving(true);
    try {
      const r = await fetch('/api/rahaza/payroll-profiles', { method: 'POST', headers, body: JSON.stringify(body) });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setFormError(typeof d.detail === 'string' ? d.detail : `Gagal simpan (HTTP ${r.status})`);
        return;
      }
      toast.success('Profil gaji disimpan');
      setEditing(null); fetchAll();
    } finally { setSaving(false); }
  };

  // 10 Nov 2026 (owner: "master data bisa dihapus"): tombol "Hapus" dulu hanya menonaktifkan. Kini hapus permanen bila
  // karyawannya belum pernah digaji; bila sudah, server menjawab 409 dan dialog kedua menawarkan Nonaktifkan.
  const del = async (p) => {
    setError('');
    const hasil = await hapusMaster({
      jenis: 'profil gaji', nama: `${p.employee_code || ''} ${p.employee_name || ''}`.trim(),
      hapus: () => apiDelete(`/api/rahaza/payroll-profiles/${p.id}?hard=true`),
      nonaktifkan: p.active === false ? null : () => apiDelete(`/api/rahaza/payroll-profiles/${p.id}`),
    });
    if (hasil) fetchAll();
  };
  const nonaktifkan = async (p) => {
    if (!(await confirmDialog({
      title: `Nonaktifkan profil gaji ${p.employee_name || p.employee_code || ''}?`,
      body: 'Karyawan ini tidak ikut proses gaji berikutnya sampai profilnya dibuat lagi. Riwayat gaji tetap tersimpan.',
      confirmLabel: 'Nonaktifkan', danger: true,
    }))) return;
    try { await apiDelete(`/api/rahaza/payroll-profiles/${p.id}`); toast.success('Profil gaji dinonaktifkan'); fetchAll(); }
    catch (e) { toast.error(e.message || 'Gagal menonaktifkan profil gaji'); }
  };

  const empsWithoutProfile = employees.filter(e => e.active && !profiles.some(p => p.employee_id === e.id));

  const opsiSkema = [
    { key: '', label: 'Semua', count: profiles.length },
    ...SCHEMES.map(s => ({ key: s.code, label: s.label, count: profiles.filter(p => p.pay_scheme === s.code).length }))
      .filter(o => o.count > 0 || o.key === skema),
  ];
  const q = cari.trim().toLowerCase();
  const baris = useMemo(() => profiles
    .filter(p => !skema || p.pay_scheme === skema)
    .filter(p => !q || `${p.employee_code || ''} ${p.employee_name || ''}`.toLowerCase().includes(q)),
  [profiles, skema, q]);
  const { page, setPage, totalPages, total, paged } = useClientPagination(baris, 10);

  const bukaBaru = () => { setFormError(''); setEditing({ employee_id: '', pay_scheme: 'monthly', base_rate: 0, overtime_rate: 0, pcs_process_rates: [] }); };
  const bukaUbah = (p) => { setFormError(''); setEditing({ ...p }); };

  const kolom = [
    { kunci: 'karyawan', label: 'Karyawan', hp: 'judul', isi: (p) => (
      <div className="min-w-0">
        <p className="font-medium text-foreground">{p.employee_name || '—'}</p>
        <p className="text-xs text-muted-foreground">{p.employee_code}</p>
      </div>) },
    { kunci: 'skema', label: 'Skema', isi: (p) => <span className="text-sm">{skemaLabel(p.pay_scheme)}</span> },
    { kunci: 'dasar', label: 'Tarif dasar', rata: 'kanan', isi: (p) => (
      <span className="tabular-nums">{formatRupiah(p.base_rate || 0)}<span className="text-xs text-muted-foreground"> /{SCHEME_META[p.pay_scheme]?.satuan || 'bulan'}</span></span>) },
    { kunci: 'lembur', label: 'Tarif lembur', rata: 'kanan', isi: (p) => <span className="tabular-nums">{formatRupiah(p.overtime_rate || 0)}<span className="text-xs text-muted-foreground"> /jam</span></span> },
    { kunci: 'proses', label: 'Tarif per proses', isi: (p) => <span className="text-sm text-muted-foreground">{overrideLabel(p)}</span> },
    { kunci: 'aksi', label: 'Aksi', rata: 'kanan', hp: 'aksi', isi: (p) => (
      <div className="flex items-center justify-end gap-1">
        <Button size="sm" variant="outline" onClick={() => bukaUbah(p)} data-testid={`pp-edit-${p.employee_code}`}><Pencil />Ubah</Button>
        <Button size="icon-sm" variant="ghost" onClick={() => nonaktifkan(p)} title="Nonaktifkan" aria-label={`Nonaktifkan profil ${p.employee_name || ''}`}
          data-testid={`pp-off-${p.employee_code}`}><Ban /></Button>
        <Button size="icon-sm" variant="ghost" onClick={() => del(p)} title="Hapus" aria-label={`Hapus profil ${p.employee_name || ''}`}
          data-testid={`pp-del-${p.employee_code}`}><Trash2 /></Button>
      </div>) },
  ];

  return (
    <PageLayout testId="rahaza-payroll-profiles-page" title="Profil gaji"
      subtitle="Skema gaji dan tarif tiap karyawan; tiap karyawan boleh punya skema berbeda."
      actions={<Button onClick={bukaBaru} data-testid="pp-add"><Plus />Tambah profil</Button>}
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari kode atau nama"
            className="pl-8" data-testid="pp-search" />
        </div>
        <FilterChips options={opsiSkema} value={skema} onChange={setSkema} testId="pp-scheme" ariaLabel="Skema gaji" />
      </>}
      tools={<div className="flex max-w-[calc(100vw-2rem)] flex-wrap items-center justify-end gap-2">
        <ImportExportToolbar collectionKey="payroll_profiles" label="Profil gaji karyawan" onImported={fetchAll}
          size="default" caption="format impor" importLabel="Impor profil" />
        <TombolUnduh namaBerkas="profil-gaji" namaLembar="Profil gaji" baris={baris} testId="pp-unduh"
          kolom={[
            { label: 'Kode karyawan', nilai: (p) => p.employee_code || '' },
            { label: 'Nama', nilai: (p) => p.employee_name || '' },
            { label: 'Skema', nilai: (p) => skemaLabel(p.pay_scheme) },
            { label: 'Tarif dasar (Rp)', nilai: (p) => Number(p.base_rate || 0) },
            { label: 'Satuan tarif dasar', nilai: (p) => SCHEME_META[p.pay_scheme]?.satuan || 'bulan' },
            { label: 'Tarif lembur per jam (Rp)', nilai: (p) => Number(p.overtime_rate || 0) },
            { label: 'Tarif per proses', nilai: overrideLabel },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchAll} disabled={loading} title="Muat ulang" aria-label="Muat ulang"
          data-testid="pp-refresh"><RefreshCw className={loading ? 'animate-spin' : ''} /></Button>
      </div>}
      footer={baris.length > 10 && <PaginationLite page={page} totalPages={totalPages} total={total} onPageChange={setPage} />}
    >
      {error && <Notice tone="danger" title={error} testId="pp-error" />}
      {empsWithoutProfile.length > 0 && (
        <Notice tone="warning" icon={Users} testId="pp-missing"
          title={`${empsWithoutProfile.length} karyawan aktif belum punya profil gaji.`}>
          Gaji mereka tidak ikut dihitung saat proses gaji. Tekan “Tambah profil”.
        </Notice>
      )}

      {loading && profiles.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat profil gaji…</p>
      ) : (
        <TabelData kolom={kolom} baris={paged} onKlikBaris={bukaUbah} testId="pp-table"
          kosong={<EmptyState title={profiles.length ? 'Tidak ada profil yang cocok' : 'Belum ada profil gaji'}
            description={profiles.length ? 'Ubah saringan atau kata pencarian.' : 'Tekan “Tambah profil” untuk mengatur skema dan tarif karyawan.'}
            action={!profiles.length && <Button onClick={bukaBaru}><Plus />Tambah profil</Button>} />} />
      )}

      <ProfileEditor
        open={editing !== null}
        profile={editing}
        employees={employees}
        processes={processes}
        isNew={!editing?.id}
        takenIds={profiles.map(p => p.employee_id)}
        saving={saving}
        galat={formError}
        onClose={() => setEditing(null)}
        onSave={save}
      />
    </PageLayout>
  );
}

function ProfileEditor({ open, profile, employees, processes, isNew, takenIds = [], saving, galat, onClose, onSave }) {
  const [state, setState] = useState(profile || {});
  const [cek, setCek] = useState('');
  useEffect(() => { setState(profile || {}); setCek(''); }, [profile]);
  const update = (k, v) => setState(s => ({ ...s, [k]: v }));

  const addProcRate = () => {
    setState(s => ({ ...s, pcs_process_rates: [...(s.pcs_process_rates || []), { process_id: '', process_code: '', rate: 0 }] }));
  };
  const removeProcRate = (i) => setState(s => ({ ...s, pcs_process_rates: s.pcs_process_rates.filter((_, idx) => idx !== i) }));
  const updateProcRate = (i, k, v) => setState(s => ({ ...s, pcs_process_rates: s.pcs_process_rates.map((r, idx) => idx === i ? { ...r, [k]: v } : r) }));

  const submit = () => {
    if (!state.employee_id) { setCek('Pilih karyawan dulu.'); return; }
    setCek('');
    onSave({
      employee_id: state.employee_id,
      pay_scheme: state.pay_scheme,
      base_rate: Number(state.base_rate) || 0,
      overtime_rate: Number(state.overtime_rate) || 0,
      pcs_process_rates: (state.pcs_process_rates || []).filter(r => r.process_id),
      notes: state.notes || '',
      // 2026-11-06 (Tahap 2): tarif baru berlaku mulai tanggal ini (versi tarif); kosong = koreksi tarif sekarang.
      effective_from: state.effective_from || undefined,
    });
  };

  const satuan = SCHEME_META[state.pay_scheme]?.satuan || 'bulan';
  return (
    <FormPopup open={open} onClose={onClose} ukuran="pendek" onSimpan={submit} menyimpan={saving}
      judul={isNew ? 'Tambah profil gaji' : 'Ubah profil gaji'}
      keterangan={isNew ? 'Karyawan yang sudah punya profil tidak ditawarkan lagi.' : `${state.employee_code || ''} ${state.employee_name || ''}`.trim()}
      galat={cek || galat} testId="pp-form">
      <Isian label="Karyawan" wajib>
        {/* Tahap 5: karyawan yang sudah punya profil tidak ditawarkan lagi saat "Tambah" (dulu menimpa profilnya diam-diam) */}
        <EmployeeSelect employees={employees} value={state.employee_id || ''} onChange={v => update('employee_id', v)}
          disabled={!isNew} exclude={isNew ? takenIds : []} testId="pp-edit-employee" />
      </Isian>
      <Isian label="Skema gaji">
        <SmartNativeSelect value={state.pay_scheme || 'monthly'} onChange={e => update('pay_scheme', e.target.value)} searchable={false}
          data-testid="pp-edit-scheme">
          {SCHEMES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
        </SmartNativeSelect>
      </Isian>
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label={`Tarif dasar (Rp per ${satuan})`}>
          <MoneyInput value={state.base_rate || 0} onChange={e => update('base_rate', e.target.value)} data-testid="pp-edit-base-rate" />
        </Isian>
        <Isian label="Tarif lembur (Rp per jam)" petunjuk="0 = memakai aturan cadangan di Pengaturan.">
          <MoneyInput value={state.overtime_rate || 0} onChange={e => update('overtime_rate', e.target.value)} data-testid="pp-edit-ot-rate" />
        </Isian>
      </div>
      {!isNew && (
        <Isian label="Tarif baru berlaku mulai (opsional)"
          petunjuk="Kosong = memperbaiki tarif yang berlaku sekarang. Diisi = kenaikan mulai tanggal itu; gaji bulan itu dihitung prorata.">
          <DatePicker value={state.effective_from || ''} onChange={v => update('effective_from', v)} placeholder="Tarif sekarang"
            testId="pp-edit-effective-from" />
        </Isian>
      )}
      {(state.rate_versions || []).length > 1 && (
        <p className="text-xs text-muted-foreground" data-testid="pp-edit-versions">
          Riwayat tarif: {state.rate_versions.map(v => `${v.effective_from ? `mulai ${formatTanggalID(v.effective_from) || v.effective_from}` : 'awal'} ${formatRupiah(v.base_rate || 0)}`).join(' · ')}
        </p>
      )}

      {state.pay_scheme === 'pcs' && (
        <Isian label="Tarif khusus per proses (opsional)" petunjuk="Tanpa tarif khusus, tarif dasar berlaku untuk semua proses.">
          <div className="space-y-2">
            {(state.pcs_process_rates || []).map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <SmartNativeSelect value={r.process_id} onChange={e => {
                    const p = processes.find(x => x.id === e.target.value);
                    updateProcRate(i, 'process_id', e.target.value);
                    if (p) updateProcRate(i, 'process_code', p.code);
                  }}>
                    <option value="">Pilih proses</option>
                    {processes.map(p => <option key={p.id} value={p.id}>{`${p.code} · ${p.name}`}</option>)}
                  </SmartNativeSelect>
                </div>
                <MoneyInput placeholder="Rp per pcs" value={r.rate} onChange={e => updateProcRate(i, 'rate', Number(e.target.value))} className="w-32" />
                <Button type="button" variant="ghost" size="icon" onClick={() => removeProcRate(i)} title="Hapus tarif proses" aria-label="Hapus tarif proses">
                  <Trash2 />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" onClick={addProcRate}><Plus />Tambah tarif proses</Button>
          </div>
        </Isian>
      )}
    </FormPopup>
  );
}
