import { useState, useEffect, useCallback } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { RefreshCw, Save, Eye, AlertCircle, CheckCircle2, Landmark } from 'lucide-react';
import { GlassCard } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import PageLayout from './layout/PageLayout';

// 2026-11-02 (K35) — penomoran akun pendapatan per toko (entity `store_revenue`).
const STORE_REV_FORMATS = [
  { value: '{prefix}{seq}', label: '4-111x — pola lama (maks. 9 toko per platform)' },
  { value: '{parent}-{seq:02d}', label: '4-1110-01 — urut 2 digit (maks. 99)' },
  { value: '{parent}-{seq:03d}', label: '4-1110-001 — urut 3 digit (maks. 999)' },
  { value: '{parent}-{store_code}', label: '4-1110-SHP-09 — sub-akun ber-kode toko' },
];
const STORE_REV_PLATFORMS = [['shopee', 'Shopee'], ['tiktok', 'TikTok'], ['tokopedia', 'Tokopedia']];
// Label layar per jenis pihak (label server memakai istilah Inggris: "Supplier … (AP)", "Channel … (AR)").
const ENTITY_LABEL = {
  cmt_vendor: { label: 'Vendor CMT — hutang', who: 'vendor CMT' },
  supplier: { label: 'Pemasok bahan/aksesori — hutang', who: 'pemasok' },
  customer: { label: 'Pelanggan — piutang', who: 'pelanggan' },
  channel: { label: 'Toko online — piutang', who: 'toko online' },
  maklon_client: { label: 'Klien maklon — piutang', who: 'klien maklon' },
  maklon_revenue: { label: 'Klien maklon — akun pendapatan', who: 'klien maklon' },
  bank: { label: 'Bank / rekening kas', who: 'rekening kas/bank' },
  store_revenue: { label: 'Toko online — akun pendapatan per toko' },
};

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
          <div className="font-semibold text-sm text-foreground">{ENTITY_LABEL.store_revenue.label}</div>
          <div className="text-xs text-muted-foreground">
            Dipakai saat toko marketplace baru dibuat. Toko lama tidak diubah.
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Format nomor akun</label>
          <SmartNativeSelect value={fmt} onChange={(e) => onChange('code_format', e.target.value)}
            searchable={false} className="w-full h-9" data-testid="coa-auto-store-format">
            {STORE_REV_FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
          </SmartNativeSelect>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={runPreview} data-testid="coa-auto-store-preview">
            <Eye className="w-4 h-4" /> Nomor berikutnya (Shopee)
          </Button>
          {preview && (
            <span className="text-xs tabular-nums" data-testid="coa-auto-store-preview-result">
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
              className="w-full h-9" data-testid={`coa-auto-store-group-${p}`}>
              <option value="">Bawaan</option>
              {revenueGroups.map((a) => <option key={a.code} value={a.code}>{a.code} — {a.name}</option>)}
            </SmartNativeSelect>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

/**
 * Akun per pemasok/pelanggan/toko (Pengaturan Keuangan › Pemetaan akun otomatis).
 * Phase 5 — Auto-Create COA Subledger: Finance dapat menyalakan/mematikan akun otomatis per jenis pihak dan
 * memilih akun induk (kontrol). Akun turunan dibuat di bawah induk sehingga buku besar menampilkan saldo per pihak.
 * 2026-11-05 (PANDUAN_UI G1/G11): cetakan PageLayout; nama koleksi & kolom basis data tidak lagi ditampilkan.
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
      if (!sRes.ok) throw new Error('Gagal memuat pengaturan');
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

  return (
    <PageLayout
      testId="coa-auto-module"
      title="Akun per pemasok, pelanggan, dan toko"
      subtitle="Akun turunan dibuat otomatis di bawah akun kontrol, sehingga buku besar menampilkan saldo per pihak."
      actions={
        <Button onClick={save} disabled={saving || loading || !settings} data-testid="coa-auto-save">
          <Save className="w-4 h-4" /> {saving ? 'Menyimpan…' : 'Simpan pengaturan'}
        </Button>
      }
      tools={
        <Button title="Muat ulang" aria-label="Muat ulang" size="icon" variant="outline" onClick={fetchData} data-testid="coa-auto-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
      }
      summary={<>
        {error && (
          <div className="flex items-center gap-2 text-sm text-[hsl(var(--destructive))]" role="alert" data-testid="coa-auto-error">
            <AlertCircle className="w-4 h-4" /> {error}
          </div>
        )}
        {info && (
          <div className="flex items-center gap-2 text-sm text-[hsl(var(--success))]" data-testid="coa-auto-info">
            <CheckCircle2 className="w-4 h-4" /> {info}
          </div>
        )}
      </>}
      footer={!loading && settings && (
        <p className="text-xs text-muted-foreground">
          Akun turunan dibuat di bawah akun induk (mis. 2-1100 Hutang Usaha untuk vendor CMT/pemasok, 1-1301 Piutang untuk
          pelanggan, 1-220 untuk toko online, 1-1200 untuk bank/kas). Saat faktur pembelian/penjualan dicatat, jurnal memakai
          akun per pihak; bila fitur nonaktif atau akunnya belum ada, jurnal memakai akun induk. Aman dijalankan berulang.
        </p>
      )}
    >
      {loading ? (
        <Skeleton className="h-40" data-testid="coa-auto-loading" />
      ) : settings && Object.entries(settings.entity_types).map(([key, cfg]) => {
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
                  <div className="font-semibold text-sm text-foreground">{ENTITY_LABEL[key]?.label || cfg.label || key.replace(/_/g, ' ')}</div>
                  <div className="text-xs text-muted-foreground">
                    Akun baru dibuat di bawah akun induk saat {ENTITY_LABEL[key]?.who || 'data'} baru ditambahkan.
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
                <span className={cfg.enabled ? 'text-[hsl(var(--success))] font-medium' : 'text-muted-foreground'}>
                  {cfg.enabled ? 'Aktif' : 'Nonaktif'}
                </span>
              </label>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Akun induk (kontrol)</label>
                <SmartNativeSelect
                  value={cfg.parent_code || ''}
                  onChange={(e) => patchEntity(key, 'parent_code', e.target.value)}
                  className="w-full h-9"
                  data-testid={`coa-auto-parent-${key}`}
                >
                  <option value="">Pilih akun</option>
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
    </PageLayout>
  );
}
