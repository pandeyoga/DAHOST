import { Fragment, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import FilterChips from '@/components/ui/filter-chips';
import { RefreshCw, Save, BookOpen, AlertCircle, CheckCircle2, AlertTriangle, Search } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { EmptyState, Notice } from './moduleAtoms';
import PageLayout from './layout/PageLayout';
import ImportExportToolbar from './ImportExportToolbar';

// 2026-11-02 (S2-H): label event/peran dari SATU sumber backend (GET /posting-profiles/meta) — dulu hanya
// 10 dari 37 event & 26 peran berlabel di layar ini. Cadangan lokal dipakai bila meta gagal dimuat.
const FALLBACK_EVENT_LABELS = {
  ar_invoice: 'Faktur penjualan (AR)', ap_invoice: 'Faktur pemasok (AP)', expense: 'Beban operasional',
  payroll_finalize: 'Finalisasi payroll', petty_cash_expense: 'Pengeluaran kas kecil',
};
const humanize = (k) => (k || '').replace(/_/g, ' ');

// Status akun yang ditunjuk peran: ok / missing / inactive / group — dulu kode yang hilang/nonaktif
// tampil sebagai "— Tidak dipetakan —" lalu simpan ditolak tanpa menunjuk peran yang salah.
function codeStatus(code, byCode) {
  if (!code) return { kind: 'empty' };
  const a = byCode.get(code);
  if (!a) return { kind: 'missing', text: `${code} — tidak ada di Bagan Akun` };
  if (a.active === false) return { kind: 'inactive', text: `${code} — ${a.name} (nonaktif)` };
  if (a.is_group) return { kind: 'group', text: `${code} — ${a.name} (akun grup, tidak bisa diposting)` };
  return { kind: 'ok' };
}

/**
 * Jurnal otomatis per transaksi (Pengaturan Keuangan › Pemetaan akun otomatis; juga menu Profil Posting).
 * 2026-11-05 (PANDUAN_UI G1/G11): cetakan PageLayout — cari & pil "Bermasalah" di toolbar, unduh/impor & muat
 * ulang di kanan. Keterangan profil dari server (berbahasa Inggris: "AP Invoice → Dr … / Cr AP") dan nama modul
 * program tidak lagi ditampilkan; peran tiap akun sudah berlabel Indonesia.
 */
export default function RahazaPostingProfilesModule({ token }) {
  const [profiles, setProfiles] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState('');
  const [error, setError] = useState('');
  const [badRoles, setBadRoles] = useState({}); // { event_type: Set(role) } dari galat simpan
  const [info, setInfo] = useState('');
  const [edits, setEdits] = useState({}); // { event_type: { role: code, ... } }
  const [search, setSearch] = useState('');
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [showAll, setShowAll] = useState(false); // KU1: "Tampilkan semua akun" (tanpa saring jenis per peran)
  const [focus, setFocus] = useState('');
  const cardRefs = useRef({});

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [rp, ra, rm] = await Promise.all([
        fetch('/api/rahaza/posting-profiles', { headers }),
        fetch('/api/rahaza/coa/accounts?active_only=false', { headers }),
        fetch('/api/rahaza/posting-profiles/meta', { headers }),
      ]);
      if (!rp.ok) { setError(`Gagal memuat profil jurnal otomatis (HTTP ${rp.status})`); return; }
      if (!ra.ok) { setError(`Gagal memuat Bagan Akun (HTTP ${ra.status})`); return; }
      setProfiles(await rp.json());
      setAccounts(await ra.json());
      if (rm.ok) setMeta(await rm.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  useEffect(() => { fetchData(); }, [fetchData]);

  // tautan dari laci "Keterikatan akun" di Bagan Akun → sorot event yang dimaksud
  useEffect(() => {
    if (loading || !profiles.length) return;
    let et = '';
    try { et = sessionStorage.getItem('pp_focus_event') || ''; sessionStorage.removeItem('pp_focus_event'); } catch { /* noop */ }
    if (!et) return;
    setFocus(et);
    setTimeout(() => cardRefs.current[et]?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  }, [loading, profiles]);

  const byCode = useMemo(() => new Map(accounts.map((a) => [a.code, a])), [accounts]);
  const leafAccounts = useMemo(() => accounts.filter((a) => !a.is_group && a.active !== false), [accounts]);
  const eventLabel = (et) => meta?.events?.[et] || FALLBACK_EVENT_LABELS[et] || humanize(et);
  const roleLabel = (et, role) => meta?.roles_by_event?.[`${et}.${role}`] || meta?.roles?.[role] || humanize(role);
  const consumersOf = (et, role) => (meta?.consumers?.[`${et}.${role}`] || []).filter((c) => !c.reads_profile);
  // 2026-11-07 (Tahap 6, KU1): pilihan akun per peran disaring JENISnya (kas/bank, piutang, hutang, pendapatan,
  // beban/HPP, …). Daftar kode per jenis dihitung server dengan aturan yang sama dengan validasi simpan
  // (GET /meta → role_families + family_codes); meta gagal dimuat → tanpa saringan.
  const familySets = useMemo(() => Object.fromEntries(
    Object.entries(meta?.family_codes || {}).map(([f, codes]) => [f, new Set(codes)])), [meta]);
  const familyOf = (et, role) => meta?.role_families?.[`${et}.${role}`] || '';
  const fitsRole = (et, role, code) => {
    const set = familySets[familyOf(et, role)];
    return !set || !code || !byCode.get(code) || set.has(code);
  };

  const getValue = (event_type, role, fallback) => {
    const ed = edits[event_type] || {};
    return Object.prototype.hasOwnProperty.call(ed, role) ? ed[role] : (fallback || '');
  };

  const problems = useMemo(() => {
    const out = [];
    profiles.forEach((p) => Object.entries(p.mapping || {}).forEach(([role, code]) => {
      const st = codeStatus(code, byCode);
      if (st.kind !== 'ok' && st.kind !== 'empty') out.push({ et: p.event_type, role, code, st });
    }));
    return out;
  }, [profiles, byCode]);
  const problemEvents = useMemo(() => new Set(problems.map((x) => x.et)), [problems]);

  const saveProfile = async (event_type) => {
    setSaving(event_type); setError(''); setInfo('');
    const original = profiles.find((p) => p.event_type === event_type) || {};
    const merged = { ...(original.mapping || {}), ...(edits[event_type] || {}) };
    const clean = {};
    Object.entries(merged).forEach(([k, v]) => { if ((v || '').trim()) clean[k] = v.trim(); });
    // peran yang SENGAJA diisi akun di luar jenisnya (lewat "Tampilkan semua akun") — server menolak yang lain
    const offTypeOk = Object.entries(edits[event_type] || {})
      .filter(([role, code]) => code && !fitsRole(event_type, role, code)).map(([role]) => role);
    const r = await fetch(`/api/rahaza/posting-profiles/${event_type}`, {
      method: 'PUT', headers, body: JSON.stringify({ mapping: clean, off_type_ok: offTypeOk }),
    });
    setSaving('');
    if (!r.ok) {
      const t = await r.text();
      let msg = t;
      try { const j = JSON.parse(t); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* teks mentah */ }
      const roles = new Set([...msg.matchAll(/\[([a-z0-9_]+)\]/g)].map((m) => m[1]));
      setBadRoles((b) => ({ ...b, [event_type]: roles }));
      setError(`Gagal menyimpan "${eventLabel(event_type)}": ${msg}`);
      return;
    }
    setInfo(`Pengaturan "${eventLabel(event_type)}" disimpan.`);
    setBadRoles((b) => ({ ...b, [event_type]: undefined }));
    setEdits((e) => ({ ...e, [event_type]: undefined }));
    fetchData();
  };

  const handleEdit = (event_type, role, code) => {
    setEdits((e) => ({ ...e, [event_type]: { ...(e[event_type] || {}), [role]: code } }));
  };

  const ql = search.trim().toLowerCase();
  const shown = profiles.filter((p) => {
    if (onlyProblems && !problemEvents.has(p.event_type)) return false;
    if (!ql) return true;
    const hay = [p.event_type, eventLabel(p.event_type), p.description,
      ...Object.entries(p.mapping || {}).flatMap(([r, c]) => [r, roleLabel(p.event_type, r), c, byCode.get(c)?.name])];
    return hay.some((s) => (s || '').toLowerCase().includes(ql));
  });

  const scrollTo = (et) => { setFocus(et); cardRefs.current[et]?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };

  return (
    <PageLayout
      testId="posting-profiles-page"
      title="Jurnal otomatis per transaksi"
      subtitle="Akun debit/kredit tiap jenis transaksi. Akun yang hilang, nonaktif, atau grup ditandai merah."
      filters={<>
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari transaksi, peran, atau kode akun…" className="pl-8 h-9" aria-label="Cari jurnal otomatis" data-testid="pp-search" />
        </div>
        <FilterChips value={onlyProblems ? 'problems' : 'all'} onChange={(k) => setOnlyProblems(k === 'problems')} testId="pp-filter" ariaLabel="Penyaring masalah"
          options={[{ key: 'all', label: 'Semua', count: profiles.length }, { key: 'problems', label: 'Bermasalah', count: problemEvents.size }]} />
        <label className="flex items-center gap-2 text-sm text-foreground/80 h-9" htmlFor="pp-show-all"
          title="Pilihan akun tiap peran disaring sesuai jenisnya (kas/bank, piutang, hutang, pendapatan, beban/HPP). Nyalakan untuk melihat semua akun rinci.">
          <Switch id="pp-show-all" checked={showAll} onCheckedChange={setShowAll} data-testid="pp-show-all" />
          Tampilkan semua akun
        </label>
      </>}
      tools={<>
        <ImportExportToolbar collectionKey="posting_profiles" label="Profil jurnal otomatis" onImported={fetchData} size="default" />
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="pp-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      </>}
      summary={<>
        {problems.length > 0 && (
          <Notice tone="danger" icon={AlertTriangle} testId="pp-problems"
            title={`${problems.length} peran menunjuk akun yang bermasalah — jurnal otomatisnya akan gagal`}>
            <ul className="mt-1 space-y-0.5 text-sm">
              {problems.slice(0, 8).map((x) => (
                <li key={`${x.et}.${x.role}`}>
                  <Button variant="link" size="sm" className="h-auto p-0 text-foreground text-left whitespace-normal" onClick={() => scrollTo(x.et)}>
                    {eventLabel(x.et)} › {roleLabel(x.et, x.role)}: <span className="text-[hsl(var(--danger-text))]">{x.st.text}</span>
                  </Button>
                </li>
              ))}
              {problems.length > 8 && <li>+{problems.length - 8} lagi (pilih "Bermasalah")</li>}
            </ul>
          </Notice>
        )}
        {error && <Notice tone="danger" icon={AlertCircle}><span className="break-words">{error}</span></Notice>}
        {info && <Notice tone="success" icon={CheckCircle2}>{info}</Notice>}
      </>}
    >
      {loading ? (
        <Skeleton className="h-40" />
      ) : profiles.length === 0 ? (
        <GlassCard className="p-0">
          <EmptyState icon={BookOpen} title="Belum ada pengaturan jurnal otomatis"
            description="Minta admin menjalankan “Pasang profil jurnal otomatis bawaan” di Adm. Sistem › Perawatan Data Keuangan." />
        </GlassCard>
      ) : shown.length === 0 ? (
        <GlassCard className="p-0">
          <EmptyState icon={Search} title="Tidak ada yang cocok" description="Ubah pencarian atau pilih Semua." />
        </GlassCard>
      ) : (
        // 2026-11-08 (Standar UI/UX v2, keluhan owner "kartu berulang"): satu TABEL berkelompok — baris kelompok =
        // jenis transaksi + tombol Simpan, baris di bawahnya = peran debit/kredit + pilihan akun (lebar tetap, bukan
        // selebar layar). Dulu 46 kartu besar dengan pilihan selebar setengah layar.
        <GlassCard className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="pp-table">
              <thead>
                <tr>
                  <th className="text-left">Transaksi · peran</th>
                  <th className="text-left">Akun</th>
                  <th className="text-right w-28"><span className="sr-only">Simpan</span></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => {
                  const mapping = p.mapping || {};
                  const roles = Object.keys(mapping);
                  const hasEdits = !!edits[p.event_type];
                  const bad = badRoles[p.event_type] || new Set();
                  return (
                    <Fragment key={p.event_type}>
                      <tr ref={(el) => { cardRefs.current[p.event_type] = el; }} data-testid={`pp-card-${p.event_type}`}
                        className={`bg-muted/40 ${focus === p.event_type ? 'ring-2 ring-inset ring-primary' : ''}`}>
                        <td colSpan={2} className="font-semibold text-foreground">
                          {eventLabel(p.event_type)}
                          {problemEvents.has(p.event_type) && <span className="ml-2 text-xs font-normal text-[hsl(var(--danger-text))]">ada akun bermasalah</span>}
                          {p.active === false && <span className="ml-2 text-xs font-normal text-muted-foreground">nonaktif</span>}
                        </td>
                        <td className="text-right">
                          {/* PANDUAN_UI G3: hanya kelompok yang diubah yang memberi tombol Simpan hijau */}
                          <Button size="sm" variant={hasEdits ? 'success' : 'outline'} onClick={() => saveProfile(p.event_type)} disabled={!hasEdits || saving === p.event_type}
                            data-testid={`pp-save-${p.event_type}`}>
                            <Save className="w-4 h-4" />
                            {saving === p.event_type ? 'Menyimpan…' : 'Simpan'}
                          </Button>
                        </td>
                      </tr>
                      {roles.map((role) => {
                        const value = getValue(p.event_type, role, mapping[role]);
                        const st = codeStatus(value, byCode);
                        const red = (st.kind !== 'ok' && st.kind !== 'empty') || bad.has(role);
                        const pending = consumersOf(p.event_type, role);
                        const fam = familyOf(p.event_type, role);
                        const famLabel = meta?.families?.[fam] || '';
                        const famSet = familySets[fam];
                        // KU1: nilai tersimpan/terpilih di luar jenis tetap tampil, ditandai (tidak hilang dari pilihan)
                        const offType = st.kind === 'ok' && !fitsRole(p.event_type, role, value);
                        const options = (showAll || !famSet) ? leafAccounts : leafAccounts.filter((a) => famSet.has(a.code));
                        const offTypeAcc = offType && !options.some((a) => a.code === value) ? byCode.get(value) : null;
                        return (
                          <tr key={role} data-testid={`pp-row-${p.event_type}-${role}`} data-role={role} data-family={fam || undefined}>
                            <td className="!pl-8 align-top">
                              <span className="text-foreground">{roleLabel(p.event_type, role)}</span>
                              {famLabel && <span className="block text-xs text-muted-foreground">akun {famLabel}</span>}
                            </td>
                            <td className="align-top">
                              <SmartNativeSelect
                                value={value}
                                onChange={(e) => handleEdit(p.event_type, role, e.target.value)}
                                className={`w-full md:w-[420px] h-9 ${red ? 'border-[hsl(var(--destructive))] ring-1 ring-[hsl(var(--destructive)/0.4)]' : offType ? 'border-[hsl(var(--warning))]' : ''}`}
                                data-testid={`pp-select-${p.event_type}-${role}`}
                                aria-label={`${eventLabel(p.event_type)} › ${roleLabel(p.event_type, role)}`}
                                aria-invalid={red}
                              >
                                <option value="">— Tidak dipetakan —</option>
                                {st.kind !== 'ok' && st.kind !== 'empty' && <option value={value}>{`⚠ ${st.text}`}</option>}
                                {offTypeAcc && <option value={value}>{`${offTypeAcc.code} — ${offTypeAcc.name} (di luar jenis yang disarankan)`}</option>}
                                {options.map((a) => (
                                  <option key={a.code} value={a.code}>{`${a.code} — ${a.name}`}</option>
                                ))}
                              </SmartNativeSelect>
                              {red && (
                                <p className="text-xs text-[hsl(var(--danger-text))] mt-1" role="alert" data-testid={`pp-bad-${p.event_type}-${role}`}>
                                  {st.text || 'Ditolak server — lihat pesan di atas.'} Pilih akun rinci yang aktif.
                                </p>
                              )}
                              {offType && !red && (
                                <p className="text-xs text-[hsl(var(--warning-text))] mt-1" data-testid={`pp-offtype-${p.event_type}-${role}`}>
                                  Akun ini di luar jenis yang disarankan untuk peran ini (akun {famLabel}). Periksa lagi bila tidak disengaja.
                                </p>
                              )}
                              {pending.length > 0 && (
                                <p className="text-xs text-[hsl(var(--warning-text))] mt-1" data-testid={`pp-pending-${p.event_type}-${role}`}
                                  data-sources={pending.map((c) => c.source).join(', ')}>
                                  Akun ini masih ditetapkan di program ({pending[0].code}) — perubahan di sini baru berlaku setelah program diperbarui.
                                </p>
                              )}
                            </td>
                            <td />
                          </tr>
                        );
                      })}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}
    </PageLayout>
  );
}
