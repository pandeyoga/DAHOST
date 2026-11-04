import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { RefreshCw, Save, Settings2, BookOpen, AlertCircle, CheckCircle2, AlertTriangle, Search } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader } from './moduleAtoms';
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
  if (!a) return { kind: 'missing', text: `${code} — TIDAK ADA di Bagan Akun` };
  if (a.active === false) return { kind: 'inactive', text: `${code} — ${a.name} (NONAKTIF)` };
  if (a.is_group) return { kind: 'group', text: `${code} — ${a.name} (akun GRUP, tidak bisa diposting)` };
  return { kind: 'ok' };
}

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
      if (!rp.ok) { setError(`Gagal memuat profil posting (HTTP ${rp.status})`); return; }
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
    const r = await fetch(`/api/rahaza/posting-profiles/${event_type}`, {
      method: 'PUT', headers, body: JSON.stringify({ mapping: clean }),
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
    setInfo(`Profil "${eventLabel(event_type)}" disimpan.`);
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

  return (
    <div className="space-y-4 min-w-0" data-testid="posting-profiles-page">
      <PageHeader
        icon={Settings2}
        eyebrow="Portal Keuangan · Master Akuntansi"
        title="Profil Posting"
        subtitle="Akun yang dipakai jurnal otomatis per jenis transaksi. Akun yang hilang/nonaktif/grup ditandai merah."
        actions={(
          <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="pp-refresh" aria-label="Muat ulang">
            <RefreshCw className="w-4 h-4 sm:mr-1.5" /><span className="hidden sm:inline"></span>
          </Button>
        )}
      />

      {problems.length > 0 && (
        <GlassCard className="p-3 border-red-500/50" data-testid="pp-problems">
          <div className="flex items-start gap-2 text-sm">
            <AlertTriangle className="w-5 h-5 text-red-600 shrink-0" />
            <div className="min-w-0">
              <p className="font-semibold">{problems.length} peran menunjuk akun yang bermasalah — posting otomatis akan gagal</p>
              <ul className="mt-1 space-y-0.5 text-xs">
                {problems.slice(0, 8).map((x) => (
                  <li key={`${x.et}.${x.role}`}>
                    <button type="button" className="text-left hover:underline" onClick={() => { setFocus(x.et); cardRefs.current[x.et]?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>
                      {eventLabel(x.et)} › {roleLabel(x.et, x.role)}: <span className="text-red-700 dark:text-red-300">{x.st.text}</span>
                    </button>
                  </li>
                ))}
                {problems.length > 8 && <li>+{problems.length - 8} lagi (centang "Hanya yang bermasalah")</li>}
              </ul>
            </div>
          </div>
        </GlassCard>
      )}
      {error && (
        <GlassCard className="p-3 border-[hsl(var(--destructive))]">
          <div className="flex items-start gap-2 text-sm text-[hsl(var(--destructive))]" role="alert">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /> <span className="break-words">{error}</span>
          </div>
        </GlassCard>
      )}
      {info && (
        <GlassCard className="p-3">
          <div className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="w-4 h-4" /> {info}
          </div>
        </GlassCard>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[12rem]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari transaksi, peran, atau kode akun…" className="pl-8 h-10" aria-label="Cari profil posting" />
        </div>
        <label className="flex items-center gap-2 text-xs h-10">
          <input type="checkbox" className="h-4 w-4" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />
          Hanya yang bermasalah
        </label>
        <div className="flex flex-wrap gap-2">
          <ImportExportToolbar collectionKey="posting_profiles" label="Profil Posting" onImported={fetchData} />
        </div>
      </div>

      {loading ? (
        <GlassCard className="p-16 text-center text-muted-foreground">Memuat…</GlassCard>
      ) : profiles.length === 0 ? (
        <GlassCard className="p-12 text-center">
          <BookOpen className="w-10 h-10 mx-auto mb-2 opacity-40" />
          <p className="text-muted-foreground">Belum ada profil jurnal otomatis. Minta admin menjalankan
            “Pasang profil jurnal otomatis bawaan” di Adm. Sistem › Perawatan Data Keuangan.</p>
        </GlassCard>
      ) : (
        <div className="space-y-4">
          {shown.length === 0 && <p className="text-sm text-muted-foreground text-center py-6">Tidak ada profil yang cocok.</p>}
          {shown.map((p) => {
            const mapping = p.mapping || {};
            const roles = Object.keys(mapping);
            const hasEdits = !!edits[p.event_type];
            const bad = badRoles[p.event_type] || new Set();
            return (
              <div key={p.event_type} ref={(el) => { cardRefs.current[p.event_type] = el; }}>
                <GlassCard className={`p-4 sm:p-5 ${focus === p.event_type ? 'ring-2 ring-primary' : ''} ${problemEvents.has(p.event_type) ? 'border-red-500/40' : ''}`} data-testid={`pp-card-${p.event_type}`}>
                  <div className="flex items-start justify-between mb-3 flex-wrap gap-2">
                    <div className="min-w-0">
                      <h3 className="font-semibold text-foreground text-sm sm:text-base">{eventLabel(p.event_type)}</h3>
                      {p.active === false && <p className="text-[11px] text-muted-foreground">Profil nonaktif</p>}
                      {p.description && <p className="text-xs text-muted-foreground mt-1">{p.description}</p>}
                    </div>
                    {/* PANDUAN_UI G3: hanya kartu yang diubah yang memberi tombol utama */}
                    <Button size="sm" variant={hasEdits ? 'default' : 'outline'} onClick={() => saveProfile(p.event_type)} disabled={!hasEdits || saving === p.event_type}
                      data-testid={`pp-save-${p.event_type}`}>
                      <Save className="w-4 h-4 mr-1.5" />
                      {saving === p.event_type ? 'Menyimpan…' : 'Simpan'}
                    </Button>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {roles.map((role) => {
                      const value = getValue(p.event_type, role, mapping[role]);
                      const st = codeStatus(value, byCode);
                      const red = (st.kind !== 'ok' && st.kind !== 'empty') || bad.has(role);
                      const pending = consumersOf(p.event_type, role);
                      return (
                        <div key={role} data-testid={`pp-row-${p.event_type}-${role}`} className="min-w-0" title={`Kode peran: ${role}`}>
                          <label className="text-xs font-medium text-foreground/80 block">
                            {roleLabel(p.event_type, role)}

                          </label>
                          <SmartNativeSelect
                            value={value}
                            onChange={(e) => handleEdit(p.event_type, role, e.target.value)}
                            className={`w-full h-9 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border px-2 text-sm text-foreground ${red ? 'border-red-500 ring-1 ring-red-500/40' : 'border-[var(--glass-border)]'}`}
                            data-testid={`pp-select-${p.event_type}-${role}`}
                            aria-invalid={red}
                          >
                            <option value="">— Tidak dipetakan —</option>
                            {st.kind !== 'ok' && st.kind !== 'empty' && <option value={value}>{`⚠ ${st.text}`}</option>}
                            {leafAccounts.map((a) => (
                              <option key={a.code} value={a.code}>{`${a.code} — ${a.name}`}</option>
                            ))}
                          </SmartNativeSelect>
                          {red && (
                            <p className="text-[11px] text-red-700 dark:text-red-300 mt-1" role="alert" data-testid={`pp-bad-${p.event_type}-${role}`}>
                              {st.text || 'Ditolak server — lihat pesan di atas.'} Pilih akun rinci yang aktif.
                            </p>
                          )}
                          {pending.length > 0 && (
                            <p className="text-[11px] text-amber-700 dark:text-amber-300 mt-1" data-testid={`pp-pending-${p.event_type}-${role}`}>
                              Masih dibaca dari kode program ({pending.map((c) => c.source).join(', ')} = {pending[0].code}) — perubahan di sini berlaku setelah modul itu membaca profil.
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </GlassCard>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
