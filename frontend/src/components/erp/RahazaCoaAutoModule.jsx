import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { RefreshCw, Save, Eye, AlertCircle, CheckCircle2, Sparkles, Landmark } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { PageHeader } from './moduleAtoms';

// 2026-11-02 (K35) — penomoran akun pendapatan per toko (entity `store_revenue`).
const STORE_REV_FORMATS = [
  { value: '{prefix}{seq}', label: '4-111x — pola lama (maks. 9 toko per platform)' },
  { value: '{parent}-{seq:02d}', label: '4-1110-01 — urut 2 digit (maks. 99)' },
  { value: '{parent}-{seq:03d}', label: '4-1110-001 — urut 3 digit (maks. 999)' },
  { value: '{parent}-{store_code}', label: '4-1110-SHP-09 — sub-akun ber-kode toko' },
];
const STORE_REV_PLATFORMS = [['shopee', 'Shopee'], ['tiktok', 'TikTok'], ['tokopedia', 'Tokopedia']];

function StoreRevenueCard({ cfg, accounts, onChange, headers }) {
  const [preview, setPreview] = useState(null);
  const fmt = cfg.code_format || '{prefix}{seq}';
  const groups = cfg.parent_by_platform || {};
  const revenueGroups = accounts.filter((a) => (a.type || '').toUpperCase() === 'REVENUE');
  const runPreview = async () => {
    try {
      const r = await fetch(`/api/rahaza/coa-auto/store-revenue/preview?code_format=${encodeURIComponent(fmt)}&platform=shopee&store_code=SHP-XX`, { headers });
      setPreview(await r.json());
    } catch (e) { setPreview({ ok: false, error: e.message }); }
  };
  return (
    <GlassCard className="p-4 space-y-3" data-testid="coa-auto-card-store_revenue">
      <div className="flex items-center gap-2">
        <Landmark className="w-4 h-4 text-primary" />
        <div>
          <div className="font-semibold text-sm text-foreground">{cfg.label || 'Akun Pendapatan per Toko'}</div>
          <div className="text-xs text-muted-foreground">
            Dipakai saat toko marketplace BARU dibuat. Toko lama tidak diubah. Simpan kode ke: <code>coa_revenue_code</code>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Format Nomor Akun</label>
          <SmartNativeSelect value={fmt} onChange={(e) => onChange('code_format', e.target.value)}
            className="w-full h-9 rounded-lg border border-[var(--glass-border)] bg-background px-3 text-sm"
            data-testid="coa-auto-store-format">
            {STORE_REV_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </SmartNativeSelect>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={runPreview} className="h-9 border border-[var(--glass-border)]" data-testid="coa-auto-store-preview">
            <Eye className="w-3.5 h-3.5 mr-1.5" /> Nomor berikutnya (Shopee)
          </Button>
          {preview && (
            <span className="text-xs font-mono" data-testid="coa-auto-store-preview-result">
              {preview.ok ? preview.next_code : (preview.error || preview.detail || 'gagal')}
            </span>
          )}
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {STORE_REV_PLATFORMS.map(([p, label]) => (
          <div key={p}>
            <label className="text-xs text-muted-foreground mb-1 block">Kelompok {label}</label>
            <SmartNativeSelect value={groups[p] || ''}
              onChange={(e) => onChange('parent_by_platform', { ...groups, [p]: e.target.value })}
              className="w-full h-9 rounded-lg border border-[var(--glass-border)] bg-background px-3 text-sm"
              data-testid={`coa-auto-store-group-${p}`}>
              <option value="">— bawaan —</option>
              {revenueGroups.map((a) => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
            </SmartNativeSelect>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

/**
 * Phase 5 — Auto-Create COA Subledger (settings + backfill).
 * Finance dapat: aktif/matikan auto-akun per jenis entitas, pilih akun parent (kontrol),
 * dan menjalankan backfill untuk entitas lama. Akun subledger dibuat di bawah parent
 * sehingga GL menampilkan saldo per-entitas (mis. hutang per Vendor CMT).
 */
export default function RahazaCoaAutoModule({ token }) {
  const [settings, setSettings] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [sRes, aRes] = await Promise.all([
        fetch('/api/rahaza/coa-auto/settings', { headers }),
        fetch('/api/rahaza/coa/accounts?active_only=true', { headers }),
      ]);
      if (!sRes.ok) throw new Error('Gagal memuat settings');
      const s = await sRes.json();
      const a = aRes.ok ? await aRes.json() : [];
      setSettings(s);
      setAccounts(Array.isArray(a) ? a : (a.accounts || a.items || []));
    } catch (e) {
      setError(e.message || 'Gagal memuat data');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const patchEntity = (key, field, value) => {
    setSettings((prev) => ({
      ...prev,
      entity_types: {
        ...prev.entity_types,
        [key]: { ...prev.entity_types[key], [field]: value },
      },
    }));
  };

  const save = async () => {
    setSaving(true); setError(''); setInfo('');
    try {
      const payload = { entity_types: {} };
      Object.entries(settings.entity_types).forEach(([k, v]) => {
        payload.entity_types[k] = k === 'store_revenue'
          ? { code_format: v.code_format, parent_by_platform: v.parent_by_platform || {} }
          : { enabled: !!v.enabled, parent_code: v.parent_code };
      });
      const r = await fetch('/api/rahaza/coa-auto/settings', {
        method: 'PUT', headers, body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || 'Gagal menyimpan');
      setInfo('Pengaturan tersimpan.');
      setTimeout(() => setInfo(''), 3000);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const accountOptions = accounts
    .filter((a) => !a.is_group) // parent kontrol biasanya postable; tetap tampilkan semua non-group + group
    .concat(accounts.filter((a) => a.is_group));

  if (loading) {
    return <div className="p-6 text-sm text-muted-foreground" data-testid="coa-auto-loading">Memuat pengaturan auto-COA…</div>;
  }

  return (
    <div className="space-y-4" data-testid="coa-auto-module">
      <PageHeader
        icon={Sparkles}
        title="Auto Akun Subledger (COA)"
        subtitle="Otomatis buat akun COA per-entitas (Vendor CMT, Supplier, Pelanggan, Channel Online, Bank/Kas) di bawah akun kontrol. GL jadi bisa menampilkan saldo per-entitas (hutang/piutang/kas)."
        actions={
          <>
            <Button variant="ghost" onClick={fetchData} className="h-9 border border-[var(--glass-border)]" data-testid="coa-auto-refresh">
              <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Muat Ulang
            </Button>
            <Button onClick={save} disabled={saving} className="h-9" data-testid="coa-auto-save">
              <Save className="w-3.5 h-3.5 mr-1.5" /> {saving ? 'Menyimpan…' : 'Simpan Pengaturan'}
            </Button>
          </>
        }
      />

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-500 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2" data-testid="coa-auto-error">
          <AlertCircle className="w-4 h-4" /> {error}
        </div>
      )}
      {info && (
        <div className="flex items-center gap-2 text-sm text-emerald-600 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2" data-testid="coa-auto-info">
          <CheckCircle2 className="w-4 h-4" /> {info}
        </div>
      )}

      {settings && Object.entries(settings.entity_types).map(([key, cfg]) => {
        if (key === 'store_revenue') {
          return (
            <StoreRevenueCard key={key} cfg={cfg} accounts={accounts} headers={headers}
              onChange={(field, value) => patchEntity(key, field, value)} />
          );
        }
        return (
          <GlassCard key={key} className="p-4 space-y-3" data-testid={`coa-auto-card-${key}`}>
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <Landmark className="w-4 h-4 text-primary" />
                <div>
                  <div className="font-semibold text-sm text-foreground">{cfg.label || key}</div>
                  <div className="text-xs text-muted-foreground">
                    Koleksi: <code>{cfg.collection}</code> · Simpan kode ke: <code>{cfg.target_field}</code>
                  </div>
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer select-none" data-testid={`coa-auto-enabled-label-${key}`}>
                <input
                  type="checkbox"
                  checked={!!cfg.enabled}
                  onChange={(e) => patchEntity(key, 'enabled', e.target.checked)}
                  className="w-4 h-4 accent-[var(--primary)]"
                  data-testid={`coa-auto-enabled-${key}`}
                />
                <span className={cfg.enabled ? 'text-emerald-600 font-medium' : 'text-muted-foreground'}>
                  {cfg.enabled ? 'Aktif' : 'Nonaktif'}
                </span>
              </label>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Akun Parent (Kontrol)</label>
                <SmartNativeSelect
                  value={cfg.parent_code || ''}
                  onChange={(e) => patchEntity(key, 'parent_code', e.target.value)}
                  className="w-full h-9 rounded-lg border border-[var(--glass-border)] bg-background px-3 text-sm"
                  data-testid={`coa-auto-parent-${key}`}
                >
                  <option value="">— pilih akun —</option>
                  {accountOptions.map((a) => (
                    <option key={a.code} value={a.code}>{a.code} — {a.name}</option>
                  ))}
                </SmartNativeSelect>
              </div>
              <p className="text-[11px] text-muted-foreground">Akun untuk data lama dibuat admin di Adm. Sistem › Perawatan Data Keuangan.</p>
            </div>

          </GlassCard>
        );
      })}

      <p className="text-xs text-muted-foreground px-1">
        Catatan: akun subledger dibuat di bawah akun parent/kontrol (mis. <code>2-1100</code> Hutang Usaha untuk Vendor CMT/Supplier,
        <code>1-1301</code> Piutang untuk Pelanggan, <code>1-220</code> untuk Channel Online, <code>1-1200</code> untuk Bank/Kas).
        Saat mem-posting invoice (AP/AR), jurnal otomatis memakai akun per-entitas tersebut; jika fitur nonaktif atau
        akun belum ada, jurnal jatuh ke akun kontrol. Idempotent &amp; aman dijalankan berulang.
      </p>
    </div>
  );
}
