/**
 * hrPickers — pilihan bersama untuk formulir SDM (Tahap 5, 2026-11-07).
 *
 * Owner: "banyak form salah" — di SDM pilihan karyawan tidak bisa dicari (Select Radix tanpa kotak cari),
 * memotong 100/200 baris pertama, memuat karyawan nonaktif, atau memakai batas bawaan API (50 baris);
 * departemen & jabatan berupa daftar tetap di kode, bukan dari master Struktur Organisasi.
 *
 *  - `EmployeeSelect`   : karyawan AKTIF, bisa dicari, label "kode · nama" (SmartNativeSelect).
 *  - `useActiveEmployees`: daftar karyawan aktif (limit 500 = batas API) untuk pemilih di atas.
 *  - `useHrMasters`     : unit organisasi (departemen), jabatan, dan shift aktif dari master-nya:
 *                          departemen = Struktur Organisasi › unit (`/api/dewi/org/units`, dicocokkan ke
 *                          `employee.department` lewat NAMA unit — sama dengan bagan & headcount),
 *                          jabatan = Struktur Organisasi › posisi (`/api/dewi/org/positions`, per unit),
 *                          shift = master shift (`/api/rahaza/shifts`).
 *  - `departmentOptions`/`positionOptions`: opsi pilihan + nilai lama yang belum ada di master tetap tampil
 *                          (ditandai), supaya data hasil impor tidak hilang diam-diam saat formulir dibuka.
 */
import { useEffect, useMemo, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';

const API = process.env.REACT_APP_BACKEND_URL || '';

const authHeaders = (token) => ({ Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` });
const rowsOf = (d, key) => (Array.isArray(d) ? d : (d?.[key] || d?.items || d?.rows || d?.data || []));

/** Karyawan aktif (maks 500 — batas `GET /api/rahaza/employees`). */
export function useActiveEmployees(token, { enabled = true } = {}) {
  const [employees, setEmployees] = useState([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!enabled) return undefined;
    let off = false;
    fetch(`${API}/api/rahaza/employees?active_only=true&limit=500`, { headers: authHeaders(token) })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => { if (!off) setEmployees(rowsOf(d, 'items')); })
      .catch(() => { if (!off) setEmployees([]); })
      .finally(() => { if (!off) setLoaded(true); });
    return () => { off = true; };
  }, [token, enabled]);
  return { employees, loaded };
}

export const employeeLabel = (e) => [e?.employee_code, e?.name].filter(Boolean).join(' · ') || e?.id || '';

/**
 * Pemilih karyawan yang bisa dicari. `employees` = daftar (aktif); karyawan terpilih yang sudah
 * nonaktif tetap ditampilkan supaya nilainya tidak "hilang".
 */
export function EmployeeSelect({
  employees = [], value = '', onChange, placeholder = '— Pilih karyawan —', allLabel,
  testId, className = '', disabled = false, exclude = [],
}) {
  const ex = new Set(exclude || []);
  const list = (employees || []).filter((e) => e && e.id && (!ex.has(e.id) || e.id === value));
  return (
    <SmartNativeSelect value={value || ''} onChange={(ev) => onChange(ev.target.value)} disabled={disabled}
      searchable={true} searchPlaceholder="Cari kode atau nama..." data-testid={testId}
      className={className || 'w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground'}>
      <option value="">{allLabel || placeholder}</option>
      {list.map((e) => <option key={e.id} value={e.id}>{employeeLabel(e)}{e.active === false ? ' (nonaktif)' : ''}</option>)}
    </SmartNativeSelect>
  );
}

/** Master unit organisasi, jabatan, dan shift aktif. */
export function useHrMasters(token, { units: wantUnits = true, positions: wantPos = true, shifts: wantShifts = true } = {}) {
  const [state, setState] = useState({ units: [], positions: [], shifts: [], loaded: false });
  useEffect(() => {
    let off = false;
    const h = { headers: authHeaders(token) };
    const get = (url, key) => fetch(`${API}${url}`, h).then((r) => (r.ok ? r.json() : [])).then((d) => rowsOf(d, key)).catch(() => []);
    Promise.all([
      wantUnits ? get('/api/dewi/org/units', 'units') : Promise.resolve([]),
      wantPos ? get('/api/dewi/org/positions', 'positions') : Promise.resolve([]),
      wantShifts ? get('/api/rahaza/shifts', 'items') : Promise.resolve([]),
    ]).then(([units, positions, shifts]) => {
      if (off) return;
      setState({
        units: units.filter((u) => u.is_active !== false),
        positions: positions.filter((p) => p.is_active !== false),
        shifts: shifts.filter((s) => s.active !== false),
        loaded: true,
      });
    });
    return () => { off = true; };
  }, [token, wantUnits, wantPos, wantShifts]);
  return state;
}

const UNIT_TYPE = { company: 'Perusahaan', division: 'Divisi', department: 'Departemen', team: 'Tim', section: 'Seksi' };

/** Opsi departemen: nama unit (nilai yang disimpan di `employee.department`). */
export function departmentOptions(units, current, extraValues = []) {
  const names = new Set();
  const opts = [];
  (units || []).forEach((u) => {
    if (!u.name || names.has(u.name)) return;
    names.add(u.name);
    opts.push({ value: u.name, label: `${u.code ? `${u.code} · ` : ''}${u.name}${UNIT_TYPE[u.type] && u.type !== 'department' ? ` (${UNIT_TYPE[u.type]})` : ''}`, unit: u });
  });
  [current, ...extraValues].forEach((v) => {
    if (v && !names.has(v)) { names.add(v); opts.push({ value: v, label: `${v} (belum ada di Struktur Organisasi)`, legacy: true }); }
  });
  return opts;
}

export function unitByName(units, name) {
  return (units || []).find((u) => u.name === name) || null;
}

/** Opsi jabatan untuk unit terpilih (jabatan tanpa unit ikut tampil). Nilai = judul jabatan. */
export function positionOptions(positions, unit, current) {
  const titles = new Set();
  const opts = [];
  (positions || [])
    .filter((p) => !unit || !p.unit_id || p.unit_id === unit.unit_id)
    .forEach((p) => {
      if (!p.title || titles.has(p.title)) return;
      titles.add(p.title);
      opts.push({ value: p.title, label: `${p.title}${p.unit_name && !unit ? ` · ${p.unit_name}` : ''}` });
    });
  if (current && !titles.has(current)) opts.push({ value: current, label: `${current} (belum ada di Struktur Organisasi)`, legacy: true });
  return opts;
}

export const shiftLabel = (s) => `${s.code ? `${s.code} · ` : ''}${s.name || ''}${s.start_time ? ` (${s.start_time}–${s.end_time || '?'})` : ''}`;

/** Daftar departemen untuk penyaring: master + nilai yang dipakai karyawan. */
export function useDepartmentFilterOptions(units, employees) {
  return useMemo(() => {
    const extra = [...new Set((employees || []).map((e) => e.department).filter(Boolean))];
    return departmentOptions(units, '', extra);
  }, [units, employees]);
}
