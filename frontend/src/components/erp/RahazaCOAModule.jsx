import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Plus, RefreshCw, Sparkles, Search, FolderTree, Table2, AlertTriangle, ExternalLink,
  CheckCircle2, XCircle, ChevronsDownUp, ChevronsUpDown, Loader2, Info, X,
} from 'lucide-react';
import { toast } from 'sonner';
import FilterChips from '@/components/ui/filter-chips';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import ViewToggle from '@/components/ui/view-toggle';
import PageLayout, { DetailPanel } from './layout/PageLayout';
import {
  TypeBadge, CoaTreeView, UsageBadge, RowActions, buildTree, TYPE_LABELS, TYPE_ORDER, NB_LABELS, LEVEL_META,
} from './RahazaCOATreeNode';
import ImportExportToolbar from './ImportExportToolbar';
import { Notice } from './moduleAtoms';

// 2026-11-02 (S2-H) — permintaan owner: "untuk Chart of akun itu tolong tandai mana yang terhubung atau
// tidak karena takutnya salah hapus … cek ui uxnya". Sumber keterikatan = backend core/coa_bindings
// (GET /accounts?with_usage, /accounts/{id}/usage, /integrity). Tidak ada layar pemetaan baru: rincian
// keterikatan menautkan ke layar pengaturan yang sudah ada (Profil Posting, Auto Akun, Pemetaan GL, …).

const CODE_RX = /^[1-7]-\d{4}(-[A-Z0-9]+)*$/;
const PREFIX_TYPES = {
  1: ['ASSET'], 2: ['LIABILITY'], 3: ['EQUITY'], 4: ['REVENUE', 'OTHER_INCOME'], 5: ['COGS'],
  6: ['EXPENSE', 'OTHER_EXPENSE'], 7: ['OTHER_INCOME', 'OTHER_EXPENSE'],
};
const DEBIT_TYPES = new Set(['ASSET', 'COGS', 'EXPENSE', 'OTHER_EXPENSE']);
const family = (t) => (['ASSET', 'LIABILITY', 'EQUITY'].includes(t) ? t : (['REVENUE', 'OTHER_INCOME'].includes(t) ? 'INCOME' : 'EXPENSE'));
const sameFamily = (a, b) => family(a) === family(b) || (['OTHER_INCOME', 'OTHER_EXPENSE'].includes(a) && ['OTHER_INCOME', 'OTHER_EXPENSE'].includes(b));
const normalBalance = (type, contra) => {
  const nb = DEBIT_TYPES.has(type) ? 'DEBIT' : 'CREDIT';
  return contra ? (nb === 'DEBIT' ? 'CREDIT' : 'DEBIT') : nb;
};

// Penanda yang bisa diatur pengguna (sama dengan routes/rahaza_coa.USER_FLAGS) + apa yang dihubungkannya.
const FLAG_DEFS = [
  { key: 'is_cash', label: 'Akun kas', hint: 'Masuk daftar kas & Arus Kas, otomatis dibuatkan Rekening Kas & Bank, bisa jadi rekening pencairan toko.' },
  { key: 'is_bank', label: 'Rekening bank / dompet digital', hint: 'Sama seperti akun kas: daftar kas, Arus Kas, Rekening Kas & Bank, rekening pencairan toko.' },
  { key: 'is_ar', label: 'Akun piutang', hint: 'Bisa dipilih sebagai piutang toko di Kelola Akun (Tautan Finance).' },
  { key: 'is_ap', label: 'Akun hutang', hint: 'Keterangan akun hutang.' },
  { key: 'is_sales', label: 'Penjualan toko', hint: 'Bisa dipilih sebagai akun pendapatan toko di Kelola Akun. Isi kanalnya.' },
  { key: 'is_fixed_asset', label: 'Aset tetap', hint: 'Kelompok arus kas bawaan: Investasi.' },
  { key: 'is_accum_dep', label: 'Akumulasi penyusutan', hint: 'Kelompok arus kas bawaan: Investasi. Biasanya juga akun kontra.' },
  { key: 'is_long_term', label: 'Liabilitas jangka panjang', hint: 'Kelompok arus kas bawaan: Pendanaan.' },
];
const INFO_FLAGS = {
  subledger: 'Sub-ledger relasi', legacy_of: 'Akun lama 3 digit', store_account_code: 'Akun toko',
  is_contra: 'Akun kontra', is_inventory_rm: 'Persediaan bahan', is_inventory_wip: 'Persediaan WIP',
  is_inventory_fg: 'Persediaan barang jadi', is_tax_input: 'PPN masukan', is_tax_output: 'PPN keluaran',
  is_tax_payable: 'Hutang pajak', is_tax_prepaid: 'Pajak dibayar dimuka', is_payroll_payable: 'Hutang gaji',
  is_bpjs_payable: 'Hutang BPJS', is_grni: 'Hutang belum ditagih (GRNI)', is_employee_advance: 'Uang muka karyawan',
  is_customer_advance: 'Uang muka pelanggan', is_capital: 'Modal', is_retained_earnings: 'Laba ditahan',
  is_current_earnings: 'Laba tahun berjalan', is_salary_expense: 'Beban gaji', is_depreciation: 'Beban penyusutan',
  is_general_expense: 'Beban umum', is_travel_expense: 'Beban perjalanan dinas', is_reimbursement: 'Reimburse',
  is_cogs_material: 'HPP bahan', is_cogs_labor: 'HPP tenaga kerja', is_cogs_overhead: 'HPP overhead',
  is_price_variance: 'Selisih harga beli', is_return_loss: 'Kerugian retur', is_interest_income: 'Pendapatan bunga',
  is_bank_charge: 'Biaya bank', is_service_fee: 'Biaya layanan', is_bad_debt_expense: 'Beban piutang tak tertagih',
  is_gain_on_disposal: 'Laba pelepasan aset', is_loss_on_disposal: 'Rugi pelepasan aset',
  is_employee_loan_receivable: 'Piutang kasbon', is_scrap_expense: 'Beban scrap', is_purchase_discount: 'Potongan pembelian',
};
const HIDDEN_FLAGS = new Set(['subledger_entity_type', 'subledger_entity_id', 'subledger_parent', 'deactivated_reason',
  'legacy_used_in_journal', 'channel']);
const flagLabel = (k, v) => {
  const f = FLAG_DEFS.find((d) => d.key === k);
  if (f) return f.label;
  const base = INFO_FLAGS[k] || k.replace(/^is_/, '').replace(/_/g, ' ');
  return typeof v === 'string' && v ? `${base}: ${v}` : base;
};
const flagLabels = (flags) => Object.entries(flags || {})
  .filter(([k, v]) => v && !HIDDEN_FLAGS.has(k))
  .map(([k, v]) => (k === 'is_sales' && flags.channel ? `Penjualan toko (${flags.channel})` : flagLabel(k, v)));

const FILTERS = [
  { key: 'aktif', label: 'Semua aktif' },
  { key: 'sistem', label: 'Terhubung sistem' },
  { key: 'struktur', label: 'Struktur / laporan' },
  { key: 'bebas', label: 'Tidak terhubung' },
  { key: 'grup', label: 'Grup' },
  { key: 'nonaktif', label: 'Nonaktif' },
  { key: 'semua', label: 'Semua' },
];
const passFilter = (a, f) => {
  const act = a.active !== false;
  const lv = a.usage?.level;
  switch (f) {
    case 'sistem': return act && lv === 'SISTEM';
    case 'struktur': return act && lv === 'STRUKTUR';
    case 'bebas': return act && (lv === 'BEBAS' || lv === 'SEED');
    case 'grup': return act && !!a.is_group;
    case 'nonaktif': return !act;
    case 'semua': return true;
    default: return act;
  }
};

const detailText = (j) => {
  const d = j && (j.detail ?? j.message);
  if (!d) return '';
  if (typeof d === 'string') return d;
  try { return JSON.stringify(d); } catch { return String(d); }
};

/** Saran kode berikutnya di bawah induk (mis. induk 6-2000 → 6-2950). */
export function suggestCode(parentCode, accounts) {
  const m = /^(\d)-(\d{4})$/.exec(parentCode || '');
  if (!m) return '';
  const taken = new Set(accounts.map((a) => a.code));
  const sibs = accounts.filter((a) => a.parent_code === parentCode && /^\d-\d{4}$/.test(a.code))
    .map((a) => parseInt(a.code.slice(2), 10)).filter((n) => !Number.isNaN(n));
  const p = parseInt(m[2], 10);
  let step = 1;
  let n;
  if (sibs.length) {
    step = sibs.every((x) => x % 10 === 0) ? 10 : 1;
    n = Math.max(...sibs) + step;
  } else {
    const digits = m[2].replace(/0+$/, '').length;
    step = 10 ** Math.max(0, 3 - digits);
    n = p + step;
  }
  for (let i = 0; i < 50 && n <= 9999; i += 1, n += step) {
    const code = `${m[1]}-${String(n).padStart(4, '0')}`;
    if (!taken.has(code)) return code;
  }
  return '';
}

function useApi(token) {
  return useCallback(async (method, url, body) => {
    const r = await fetch(url, {
      method,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let j = null;
    try { j = await r.json(); } catch { j = null; }
    if (!r.ok) throw new Error(detailText(j) || `HTTP ${r.status}`);
    return j;
  }, [token]);
}

// ───────────────────────────── Editor (dialog) ───────────────────────────────
function Field({ label, htmlFor, children, hint, error }) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="text-xs font-medium text-foreground/80">{label}</label>
      <div className="mt-1">{children}</div>
      {error && <p className="text-xs text-red-600 dark:text-red-400 mt-1" role="alert">{error}</p>}
      {!error && hint && <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>}
    </div>
  );
}

const selectCls = 'w-full h-9 rounded-[var(--radius-sm)] bg-[var(--card-surface)] border border-[var(--glass-border)] px-2 text-sm text-foreground disabled:opacity-60';

function AccountEditorDialog({ initial, accounts, api, onClose, onSaved }) {
  const isNew = !initial?.id;
  const [form, setForm] = useState(() => ({
    code: initial?.code || '', name: initial?.name || '', type: initial?.type || 'EXPENSE',
    parent_code: initial?.parent_code || '', is_group: !!initial?.is_group, active: initial?.active !== false,
    cash_flow_group: initial?.cash_flow_group || '', flags: { ...(initial?.flags || {}) },
  }));
  const [usage, setUsage] = useState(null);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState('');
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setFlag = (k, v) => setForm((f) => ({ ...f, flags: { ...f.flags, [k]: v } }));

  useEffect(() => {
    if (isNew) return;
    api('GET', `/api/rahaza/coa/accounts/${initial.id}/usage`).then(setUsage).catch(() => setUsage(null));
  }, [api, initial, isNew]);

  const actions = usage?.actions || {};
  const lockCode = !isNew && !(actions.change_code?.allowed);
  const lockType = !isNew && !(actions.change_type?.allowed);
  const groupAction = form.is_group === !!initial?.is_group ? null : (form.is_group ? 'make_group' : 'make_leaf');
  const groupLocked = !isNew && (initial?.is_group ? actions.make_leaf?.allowed === false : actions.make_group?.allowed === false);
  const deactLocked = !isNew && initial?.active !== false && actions.deactivate?.allowed === false;

  const code = (form.code || '').trim().toUpperCase();
  const prefixTypes = PREFIX_TYPES[code[0]] || TYPE_ORDER;
  const codeError = !code ? 'Kode wajib diisi.' : (!CODE_RX.test(code) && (isNew || !lockCode)
    ? 'Pola: angka 1–7, "-", 4 digit (mis. 6-2950); akhiran sub-akun boleh (1-1303-SHP-09).' : '');
  const typeError = CODE_RX.test(code) && !prefixTypes.includes(form.type)
    ? `Kode berawalan ${code[0]}- untuk tipe ${prefixTypes.map((t) => TYPE_LABELS[t]).join(' / ')}.` : '';
  const nameError = !form.name.trim() ? 'Nama wajib diisi.' : '';
  const dup = isNew && accounts.some((a) => a.code === code) ? `Kode ${code} sudah ada.` : '';

  // induk: akun grup aktif sekeluarga tipe, bukan diri sendiri/turunannya
  const descendants = useMemo(() => {
    const s = new Set();
    if (isNew) return s;
    const kids = new Map();
    accounts.forEach((a) => { if (a.parent_code) kids.set(a.parent_code, [...(kids.get(a.parent_code) || []), a.code]); });
    const st = [initial.code];
    while (st.length) { const c = st.pop(); if (s.has(c)) continue; s.add(c); (kids.get(c) || []).forEach((k) => st.push(k)); }
    return s;
  }, [accounts, initial, isNew]);
  const parentOptions = useMemo(() => accounts
    .filter((a) => a.is_group && a.active !== false && sameFamily(a.type, form.type) && !descendants.has(a.code))
    .sort((a, b) => a.code.localeCompare(b.code)), [accounts, form.type, descendants]);
  const curParent = accounts.find((a) => a.code === form.parent_code);
  const parentIsControl = curParent && !curParent.is_group;
  const parentError = form.parent_code && !curParent ? `Induk ${form.parent_code} tidak ada.`
    : (curParent && !sameFamily(curParent.type, form.type) ? `Induk bertipe ${TYPE_LABELS[curParent.type]} — tidak cocok.` : '');
  const suggestion = isNew && form.parent_code ? suggestCode(form.parent_code, accounts) : '';

  const contra = !!form.flags.is_contra;
  const nb = normalBalance(form.type, contra);
  const looksContra = !contra && /akum|cadangan|retur|diskon|potongan|prive/i.test(form.name);
  const infoFlags = Object.entries(form.flags).filter(([k, v]) => v && !HIDDEN_FLAGS.has(k) && !FLAG_DEFS.some((d) => d.key === k) && k !== 'is_contra');

  const invalid = !!(codeError || typeError || nameError || dup || parentError);

  const onCode = (v) => {
    const up = v.toUpperCase();
    setForm((f) => {
      const allowed = PREFIX_TYPES[up[0]];
      return { ...f, code: up, type: allowed && !allowed.includes(f.type) ? allowed[0] : f.type };
    });
  };

  const save = async () => {
    setSaving(true); setServerError('');
    const flags = {};
    FLAG_DEFS.forEach((d) => { flags[d.key] = !!form.flags[d.key]; });
    flags.is_contra = contra;
    flags.channel = form.flags.is_sales ? (form.flags.channel || '') : '';
    const body = {
      code, name: form.name.trim(), type: form.type, parent_code: form.parent_code || null,
      is_group: form.is_group, cash_flow_group: form.cash_flow_group || '', flags,
      ...(isNew ? {} : { active: form.active }),
    };
    try {
      const out = await api(isNew ? 'POST' : 'PUT', isNew ? '/api/rahaza/coa/accounts' : `/api/rahaza/coa/accounts/${initial.id}`, body);
      toast.success(isNew ? `Akun ${out.code} dibuat.` : `Akun ${out.code} disimpan.`);
      onSaved();
    } catch (e) {
      setServerError(e.message);
    } finally { setSaving(false); }
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-2xl w-[calc(100vw-1.5rem)] max-h-[90vh] overflow-y-auto p-4 sm:p-6" data-testid="coa-editor">
        <DialogHeader>
          <DialogTitle>{isNew ? 'Tambah akun' : `Ubah akun ${initial.code}`}</DialogTitle>
          <DialogDescription>
            {isNew ? 'Kode, tipe, dan induk divalidasi seperti di server.'
              : (usage ? `${LEVEL_META[usage.summary?.level]?.label || ''}${usage.summary?.count ? ` · ${usage.summary.count} keterikatan` : ''} — bagian yang terkunci menyebut alasannya.` : 'Memuat keterikatan…')}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Kode akun *" htmlFor="coa-code" error={codeError || dup}
            hint={lockCode ? `Terkunci: ${(actions.change_code?.reasons || ['akun sudah dirujuk'])[0]}` : (suggestion ? '' : 'Contoh: 6-2950')}>
            <GlassInput id="coa-code" value={form.code} onChange={(e) => onCode(e.target.value)} disabled={lockCode}
              placeholder="6-2950" autoComplete="off" className="font-mono" data-testid="coa-input-code" />
            {suggestion && !form.code && (
              <button type="button" className="text-[11px] text-primary mt-1 underline" onClick={() => onCode(suggestion)} data-testid="coa-code-suggest">
                Pakai saran: {suggestion}
              </button>
            )}
          </Field>
          <Field label="Nama akun *" htmlFor="coa-name" error={nameError}>
            <GlassInput id="coa-name" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Beban Kebersihan" data-testid="coa-input-name" />
          </Field>
          <Field label="Tipe *" htmlFor="coa-type" error={typeError}
            hint={lockType ? `Terkunci: ${(actions.change_type?.reasons || ['akun sudah dipakai'])[0]}` : 'Tipe mengikuti awalan kode.'}>
            <select id="coa-type" value={form.type} onChange={(e) => set('type', e.target.value)} disabled={lockType}
              className={selectCls} data-testid="coa-input-type">
              {TYPE_ORDER.map((t) => <option key={t} value={t} disabled={CODE_RX.test(code) && !prefixTypes.includes(t)}>{TYPE_LABELS[t]}</option>)}
            </select>
          </Field>
          <Field label="Akun induk" htmlFor="coa-parent" error={parentError}
            hint={parentIsControl ? 'Induk = akun kontrol sub-ledger (dibuat Auto Akun).' : 'Hanya akun grup aktif dengan tipe sekeluarga.'}>
            <SmartNativeSelect id="coa-parent" value={form.parent_code || ''} onChange={(e) => set('parent_code', e.target.value)}
              className="h-9 text-sm" data-testid="coa-input-parent">
              <option value="">— Tanpa induk (akar) —</option>
              {parentIsControl && <option value={curParent.code}>{`${curParent.code} ${curParent.name} (kontrol sub-ledger)`}</option>}
              {parentOptions.map((a) => <option key={a.code} value={a.code}>{`${a.code} ${a.name}`}</option>)}
            </SmartNativeSelect>
          </Field>
          <div className="sm:col-span-2 rounded-md border border-[var(--glass-border)] p-3 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">Saldo normal: <span data-testid="coa-normal-balance">{NB_LABELS[nb]}</span>{contra && ' (akun kontra)'}</p>
              <p className="text-[11px] text-muted-foreground">
                Akun kontra (akumulasi penyusutan, cadangan piutang, retur/diskon penjualan, prive) bersaldo normal kebalikan tipenya.
              </p>
              {looksContra && <p className="text-[11px] text-amber-700 dark:text-amber-300 mt-1">Nama ini biasanya akun kontra — nyalakan saklar di kanan bila benar.</p>}
            </div>
            <label className="flex items-center gap-2 shrink-0 text-xs">
              <Switch checked={contra} onCheckedChange={(v) => setFlag('is_contra', v)} aria-label="Akun kontra" data-testid="coa-input-contra" />
              Kontra
            </label>
          </div>
          <Field label="Kelompok arus kas" htmlFor="coa-cfg" hint="Dipakai Laporan Arus Kas “Per Akun”.">
            <select id="coa-cfg" value={form.cash_flow_group || ''} onChange={(e) => set('cash_flow_group', e.target.value)} className={selectCls} data-testid="coa-input-cfgroup">
              <option value="">— bawaan dari kode akun —</option>
              <option value="OPR">Operasi</option>
              <option value="INV">Investasi</option>
              <option value="PND">Pendanaan</option>
            </select>
          </Field>
          <div className="space-y-2">
            <label className={`flex items-start gap-2 text-sm ${groupLocked ? 'opacity-70' : ''}`}>
              <Switch checked={form.is_group} onCheckedChange={(v) => set('is_group', v)} disabled={groupLocked} aria-label="Akun grup" data-testid="coa-input-isgroup" />
              <span>Akun grup (header) <span className="block text-[11px] text-muted-foreground">Hanya pengelompok — tidak bisa menerima jurnal.</span></span>
            </label>
            {groupLocked && (
              <p className="text-[11px] text-amber-700 dark:text-amber-300" data-testid="coa-isgroup-warning">
                Terkunci: {((initial?.is_group ? actions.make_leaf : actions.make_group)?.reasons || []).slice(0, 2).join('; ')}
              </p>
            )}
            {groupAction && !groupLocked && <p className="text-[11px] text-muted-foreground">Server memeriksa ulang saat simpan.</p>}
            {!isNew && (
              <>
                <label className={`flex items-start gap-2 text-sm ${deactLocked ? 'opacity-70' : ''}`}>
                  <Switch checked={form.active} onCheckedChange={(v) => set('active', v)} disabled={deactLocked} aria-label="Akun aktif" data-testid="coa-input-active" />
                  <span>Aktif <span className="block text-[11px] text-muted-foreground">Akun nonaktif hilang dari pilihan akun; riwayat tetap.</span></span>
                </label>
                {deactLocked && <p className="text-[11px] text-amber-700 dark:text-amber-300">Tidak bisa dinonaktifkan: {(actions.deactivate?.reasons || []).slice(0, 2).join('; ')}</p>}
              </>
            )}
          </div>
          <fieldset className="sm:col-span-2 rounded-md border border-[var(--glass-border)] p-3">
            <legend className="text-xs font-medium px-1">Penanda — menghubungkan akun ke daftar/validator</legend>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {FLAG_DEFS.map((d) => (
                <label key={d.key} className="flex items-start gap-2 text-sm" title={d.hint}>
                  <input type="checkbox" className="mt-1 h-4 w-4" checked={!!form.flags[d.key]} onChange={(e) => setFlag(d.key, e.target.checked)} data-testid={`coa-flag-${d.key}`} />
                  <span className="min-w-0">{d.label}<span className="block text-[11px] text-muted-foreground">{d.hint}</span></span>
                </label>
              ))}
            </div>
            {form.flags.is_sales && (
              <div className="mt-2 max-w-xs">
                <Field label="Kanal penjualan" htmlFor="coa-channel">
                  <select id="coa-channel" value={form.flags.channel || ''} onChange={(e) => setFlag('channel', e.target.value)} className={selectCls}>
                    <option value="">— pilih —</option>
                    <option value="shopee">Shopee</option>
                    <option value="tiktok">TikTok</option>
                    <option value="tokopedia">Tokopedia</option>
                    <option value="lazada">Lazada</option>
                  </select>
                </Field>
              </div>
            )}
            {infoFlags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1" aria-label="Penanda sistem (tidak bisa diubah di sini)">
                {infoFlags.map(([k, v]) => (
                  <span key={k} className="text-[10px] px-1.5 py-0.5 rounded border border-foreground/15 text-muted-foreground">{flagLabel(k, v)}</span>
                ))}
              </div>
            )}
          </fieldset>
        </div>
        {serverError && (
          <Notice tone="danger" icon={AlertTriangle} testId="coa-editor-error">{serverError}</Notice>
        )}
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} data-testid="coa-editor-cancel">Batal</Button>
          <Button onClick={save} disabled={invalid || saving} data-testid="coa-editor-save">
            {saving && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}Simpan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ───────────────────────────── Laci keterikatan ──────────────────────────────
const ACTION_ROWS = [
  ['delete', 'Hapus permanen'], ['deactivate', 'Nonaktifkan'], ['make_group', 'Jadikan grup'],
  ['make_leaf', 'Jadikan akun rinci'], ['change_type', 'Ubah tipe'], ['change_code', 'Ubah kode'],
];

// 2026-11-04 (PANDUAN_UI G11, arahan owner): keterikatan ditulis dalam bahasa staf. API tetap mengirim label &
// alamat teknis (dipakai pemeriksa/tes); layar menerjemahkan dan TIDAK menampilkan alamat program
// (`rahaza_coa_auto_settings…`, `routes.coa_auto.DEFAULT_ENTITY_TYPES…`).
const GROUP_TEXT = {
  profil: 'Dipakai jurnal otomatis', toko: 'Dipakai toko online', rekening: 'Dipakai rekening kas & bank',
  peta_channel: 'Peta akun channel lama (masih dibaca faktur)', auto_coa: 'Akun induk untuk akun otomatis',
  entitas: 'Akun milik pemasok, vendor, atau pelanggan', subledger: 'Akun otomatis milik relasi',
  pemetaan_gl: 'Dipakai kategori klaim / kas kecil', kas_kecil: 'Dipakai dana kas kecil', kategori_aset: 'Dipakai kategori aset',
  aset_tetap: 'Dipakai aset tetap', anggaran: 'Dipakai anggaran', kode_posting: 'Dipakai langsung saat sistem mencatat jurnal',
  kode_sinkron: 'Dipakai saat sistem membuat akun otomatis', kode_cadangan: 'Akun pengganti bila pengaturan kosong',
  kode_laporan: 'Dibaca laporan', jurnal: 'Sudah dipakai di jurnal', jurnal_draft: 'Dipakai di jurnal draf', anak: 'Punya akun anak',
  flag: 'Penanda akun', sinkron_toko: 'Akun pendapatan toko (diatur otomatis)', seed: 'Akun bawaan sistem',
};
const ENTITY_TEXT = { cmt_vendor: 'vendor CMT', supplier: 'pemasok', customer: 'pelanggan', channel: 'toko online',
  maklon_client: 'klien maklon', maklon_revenue: 'pendapatan klien maklon', bank: 'rekening bank' };
const TECH_TEXT_RX = /\b[a-z][a-z0-9]*_[a-z0-9_]+\b|\b[a-z_]+\.[a-z_.]+\b|\[\(/;
export function humanBinding(label) {
  let t = String(label || '').trim();
  const auto = t.match(/^Auto Akun\s*›\s*(.+?):\s*induk sub-ledger$/i);
  if (auto) return `Akun induk untuk ${auto[1].replace(/\s*\((AR|AP)\)/g, '').replace(/\s+—\s+/g, ' — ').toLowerCase()}. Saat data baru dibuat, sistem membuat akun anak di bawah akun ini.`;
  if (/^Auto Akun:\s*induk bawaan sub-ledger$/i.test(t)) return 'Akun induk bawaan untuk akun yang dibuat otomatis.';
  const sub = t.match(/^Sub-ledger (\w+)(?: \(relasi [\w-]+\))?$/i);
  if (sub) return `Akun otomatis milik ${ENTITY_TEXT[sub[1]] || sub[1].replace(/_/g, ' ')}.`;
  t = t.replace(/:\s*induk sub-ledger\b/gi, ': akun induk untuk akun otomatis')
    .replace(/sub-ledger/gi, 'akun anak otomatis').replace(/\s*\((AR|AP)\)/g, '')
    .replace(/\(posted\)/gi, '(terjurnal)').replace(/\bposted\b/gi, 'terjurnal').replace(/\(Cr\)/g, '(kredit)').replace(/\(Dr\)/g, '(debit)')
    .replace(/^Auto Akun\s*[›:]\s*/i, '');
  return t;
}
const humanDetail = (d) => (d && !/^\d+$/.test(d) && !TECH_TEXT_RX.test(d) ? d : '');
const LEVEL_TEXT = {
  BEBAS: () => 'Tidak dipakai di mana pun — aman dihapus.',
  SEED: () => 'Akun bawaan sistem: tidak bisa dihapus permanen (akan dibuat ulang), tapi boleh dinonaktifkan.',
  STRUKTUR: () => 'Dipakai sebagai induk akun lain atau dibaca laporan.',
  SISTEM: (n) => `Dipakai sistem di ${n} tempat. Ubah dulu pengaturannya di layar terkait sebelum menghapus atau menonaktifkan.`,
};

// 2026-11-04 (PANDUAN_UI G13): keterikatan dibuka DI HALAMAN (panel lebar di atas pohon akun) — dulu laci samping
// yang sempit; tautan "Buka …" menghimpit teks sampai terpotong per huruf.
function UsagePanel({ acc, api, onClose, onEdit, onDelete, onReactivate, openScreen }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (!acc) return;
    setData(null); setErr('');
    api('GET', `/api/rahaza/coa/accounts/${acc.id}/usage`).then(setData).catch((e) => setErr(e.message));
  }, [acc, api]);
  const s = data?.summary;
  return (
    <DetailPanel
      testId="coa-usage-sheet"
      title={<span className="flex items-center gap-2 flex-wrap"><span>{acc.code} · {acc.name}</span><TypeBadge type={acc.type} />
        {acc.active === false && <span className="text-[10px] px-1.5 py-0.5 rounded border border-foreground/20">nonaktif</span>}</span>}
      description={data ? `${data.level_label}${s.count ? ` · ${s.count} keterikatan` : ''}` : 'Memuat keterikatan…'}
      onClose={onClose}
      actions={data && <>
        <Button variant="outline" onClick={() => onEdit(acc)}>Ubah</Button>
        {acc.active === false
          ? <Button onClick={() => onReactivate(acc)} data-testid="coa-usage-reactivate">Aktifkan lagi</Button>
          : <Button variant="outline" onClick={() => onDelete(acc)}>
            {data.actions.delete.allowed ? 'Hapus permanen' : (data.actions.deactivate.allowed ? 'Nonaktifkan' : 'Kenapa terkunci?')}
          </Button>}
      </>}
    >
      {!data && !err && <div className="py-6 grid place-items-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>}
      {err && <p className="text-sm text-[hsl(var(--destructive))]">{err}</p>}
      {data && (
        <div className="space-y-4">
          <div className={`rounded-md border p-3 text-sm ${LEVEL_META[s.level]?.cls || ''}`} data-testid="coa-usage-level">
            <p>{(LEVEL_TEXT[s.level] || (() => ''))(s.count)}</p>
            {(s.journal_lines > 0 || s.draft_entries > 0) && (
              <p className="text-xs mt-1">{s.journal_lines} baris jurnal terjurnal · {s.draft_entries} jurnal draf</p>
            )}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {data.groups.map((g) => (
              <section key={g.kind} aria-label={GROUP_TEXT[g.kind] || g.label}>
                <p className="text-sm font-semibold text-foreground flex items-center gap-2">
                  <span className={`inline-block w-2 h-2 rounded-full ${g.level === 'SISTEM' ? 'bg-[hsl(var(--destructive))]' : g.level === 'STRUKTUR' ? 'bg-[hsl(var(--warning))]' : 'bg-foreground/30'}`} />
                  {GROUP_TEXT[g.kind] || humanBinding(g.label)} <span className="font-normal text-muted-foreground">({g.items.length})</span>
                </p>
                <ul className="mt-1.5 space-y-1.5">
                  {g.items.slice(0, 30).map((it, i) => (
                    <li key={`${g.kind}-${i}`} className="text-sm border-l-2 border-[var(--glass-border)] pl-3">
                      <p className="break-words">{humanBinding(it.label)}{it.active === false ? ' (tidak aktif)' : ''}</p>
                      {humanDetail(it.detail) && <p className="text-xs text-muted-foreground">{humanDetail(it.detail)}</p>}
                      {it.screen?.module && (
                        <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => openScreen(it.screen, it.ref_id)}>
                          <ExternalLink className="w-3.5 h-3.5" />Buka {it.screen.label}
                        </Button>
                      )}
                    </li>
                  ))}
                  {g.items.length > 30 && <li className="text-xs text-muted-foreground pl-3">+{g.items.length - 30} lagi</li>}
                </ul>
              </section>
            ))}
          </div>
          <section aria-label="Aksi yang tersedia">
            <p className="text-sm font-semibold text-foreground">Yang boleh dilakukan pada akun ini</p>
            <ul className="mt-1.5 grid gap-1 sm:grid-cols-2">
              {ACTION_ROWS.map(([k, label]) => {
                const a = data.actions[k] || {};
                return (
                  <li key={k} className="text-sm flex items-start gap-2">
                    {a.allowed ? <CheckCircle2 className="w-4 h-4 text-[hsl(var(--success))] shrink-0 mt-0.5" /> : <XCircle className="w-4 h-4 text-muted-foreground shrink-0 mt-0.5" />}
                    <span className="min-w-0"><span className={a.allowed ? '' : 'text-muted-foreground'}>{label}</span>
                      {!a.allowed && a.reasons?.length > 0 && <span className="block text-xs text-muted-foreground break-words">{a.reasons.slice(0, 3).map(humanBinding).join('; ')}{a.reasons.length > 3 ? ` (+${a.reasons.length - 3})` : ''}</span>}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      )}
    </DetailPanel>
  );
}

// ───────────────────────────── Konfirmasi hapus / nonaktif ───────────────────
function DeleteDialog({ acc, api, onClose, onDone, openUsage }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (!acc) return;
    setData(null); setErr('');
    api('GET', `/api/rahaza/coa/accounts/${acc.id}/usage`).then(setData).catch((e) => setErr(e.message));
  }, [acc, api]);
  const act = data?.actions || {};
  const mode = act.delete?.allowed ? 'delete' : (act.deactivate?.allowed ? 'deactivate' : 'locked');
  const run = async () => {
    setBusy(true); setErr('');
    try {
      if (mode === 'delete') {
        await api('DELETE', `/api/rahaza/coa/accounts/${acc.id}`);
        toast.success(`Akun ${acc.code} dihapus permanen.`);
      } else {
        await api('PUT', `/api/rahaza/coa/accounts/${acc.id}`, { active: false });
        toast.success(`Akun ${acc.code} dinonaktifkan — bisa diaktifkan lagi dari filter "Nonaktif".`);
      }
      onDone();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={!!acc} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md w-[calc(100vw-1.5rem)] max-h-[90vh] overflow-y-auto p-4 sm:p-6" data-testid="coa-delete-dialog">
        <DialogHeader>
          <DialogTitle>
            {!data ? 'Memeriksa keterikatan…' : mode === 'delete' ? 'Hapus permanen?' : mode === 'deactivate' ? 'Tidak bisa dihapus — nonaktifkan?' : 'Akun terkunci'}
          </DialogTitle>
          <DialogDescription>{acc?.code} · {acc?.name}</DialogDescription>
        </DialogHeader>
        {!data && !err && <div className="py-6 grid place-items-center"><Loader2 className="w-5 h-5 animate-spin" /></div>}
        {data && mode === 'delete' && (
          <p className="text-sm">Akun ini <b>tidak terhubung</b> ke posting, konfigurasi, jurnal, maupun akun anak. Penghapusan <b>permanen</b> dan tidak bisa dibatalkan.</p>
        )}
        {data && mode !== 'delete' && (
          <div className="space-y-2 text-sm">
            <p>Akun ini tidak bisa dihapus permanen karena:</p>
            <ul className="list-disc pl-5 space-y-0.5 text-[13px]">
              {(act.delete?.reasons || []).slice(0, 6).map((r, i) => <li key={i} className="break-words">{r}</li>)}
              {(act.delete?.reasons || []).length > 6 && <li>+{act.delete.reasons.length - 6} lagi</li>}
            </ul>
            {mode === 'deactivate' && <Notice tone="warning">Anda bisa <b>menonaktifkannya</b>: akun hilang dari pilihan akun, riwayat jurnal & rujukan tetap utuh, dan bisa diaktifkan lagi kapan saja.</Notice>}
            {mode === 'locked' && (
              <Notice tone="danger" title="Menonaktifkan pun belum bisa:">
                <ul className="list-disc pl-5 text-[13px]">{(act.deactivate?.reasons || []).slice(0, 5).map((r, i) => <li key={i} className="break-words">{r}</li>)}</ul>
                <p className="text-[12px] mt-1">Ganti dulu rujukannya di layar terkait (lihat rincian keterikatan).</p>
              </Notice>
            )}
          </div>
        )}
        {err && <p className="text-sm text-[hsl(var(--destructive))]" role="alert">{err}</p>}
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose}>Batal</Button>
          {data && mode === 'locked' && <Button onClick={() => { onClose(); openUsage(acc); }}>Lihat keterikatan</Button>}
          {data && mode !== 'locked' && (
            <Button variant={mode === 'delete' ? 'destructive' : 'default'} disabled={busy} onClick={run} data-testid="coa-delete-confirm">
              {busy && <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />}{mode === 'delete' ? 'Hapus permanen' : 'Nonaktifkan'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ───────────────────────────── Banner integritas ─────────────────────────────
function IntegrityBanner({ data, openScreen }) {
  const [open, setOpen] = useState(false);
  if (!data) return null;
  const rows = [
    ...(data.dangling_refs || []).map((r) => ({ ...r, what: 'tidak ada di Bagan Akun' })),
    ...(data.inactive_targets || []).map((r) => ({ ...r, what: 'nonaktif' })),
    ...(data.group_targets || []).map((r) => ({ ...r, what: 'akun grup (tidak bisa diposting)' })),
  ];
  const warn = (data.fallback_warnings || []).length;
  const skipped = (data.sync_skipped || []).length;
  if (!rows.length && !warn && !skipped) return null;
  return (
    <Notice tone={rows.length ? 'danger' : 'warning'} icon={AlertTriangle} testId="coa-integrity-banner"
      title={rows.length ? `${rows.length} akun dirujuk konfigurasi tetapi bermasalah` : 'Catatan integritas Bagan Akun'}>
      <p className="text-xs text-muted-foreground">
        {[warn && `${warn} kode cadangan akan terpakai karena peran profil kosong`, skipped && `${skipped} akun dilewati sinkron toko (buatan/ubahan pengguna)`].filter(Boolean).join(' · ') || 'Posting otomatis ke akun ini akan gagal sampai rujukannya diperbaiki.'}
      </p>
      <Button variant="link" size="sm" className="h-auto p-0 text-xs mt-1" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        {open ? 'Sembunyikan rincian' : 'Lihat rincian'}
      </Button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {rows.map((r) => (
            <li key={`${r.code}-${r.what}`} className="rounded border border-[var(--glass-border)] p-2">
              <p><span className="font-mono">{r.code}</span> {r.name || ''} — <b>{r.what}</b></p>
              <p className="text-[11px] text-muted-foreground break-words">{(r.refs || []).slice(0, 3).join(' · ')}</p>
              {(r.screens || []).slice(0, 2).map((s) => (
                <Button key={s.label} variant="link" size="sm" onClick={() => openScreen(s)} className="h-auto p-0 text-[11px] mr-3">Buka {s.label}</Button>
              ))}
            </li>
          ))}
          {(data.fallback_warnings || []).map((w) => (
            <li key={`fb-${w.role}-${w.code}`} className="rounded border border-[hsl(var(--warning)/0.3)] p-2 text-[12px]">
              Peran <span className="font-mono">{w.role}</span> kosong → program memakai <span className="font-mono">{w.code}</span> {w.name || ''} ({w.label}).
              <Button variant="link" size="sm" onClick={() => openScreen({ module: 'fin-settings-hub', tab: 'mapping', view: 'posting', label: 'Pemetaan akun otomatis' }, w.role.split('.')[0])} className="h-auto p-0 text-[12px] ml-2">Isi di Pemetaan akun otomatis</Button>
            </li>
          ))}
          {(data.sync_skipped || []).map((x) => (
            <li key={`sk-${x.code}`} className="rounded border border-foreground/15 p-2 text-[12px]">
              <span className="font-mono">{x.code}</span> {x.name} — tidak dinonaktifkan sinkron toko: {x.reason}
            </li>
          ))}
        </ul>
      )}
    </Notice>
  );
}

// ───────────────────────────── Tabel / kartu ─────────────────────────────────
function AccountCards({ list, q, onEdit, onDelete, onReactivate, onUsage }) {
  if (!list.length) return <div className="py-8 text-center text-sm text-muted-foreground">Tidak ada akun yang cocok.</div>;
  return (
    <>
      <ul className="md:hidden space-y-2" aria-label="Daftar akun">
        {list.map((a) => (
          <li key={a.code} className={`rounded-md border border-[var(--glass-border)] p-2.5 ${a.active === false ? 'opacity-60' : ''}`} data-testid={`coa-card-${a.code}`}>
            <div className="flex items-start gap-2 min-w-0">
              <div className="min-w-0 flex-1">
                <p className="font-mono text-xs text-foreground/75 truncate">{a.code}</p>
                <p className={`text-sm break-words ${a.is_group ? 'font-semibold' : ''}`}>{a.name}</p>
              </div>
              <RowActions acc={a} code={a.code} onEdit={onEdit} onDelete={onDelete} onReactivate={onReactivate} />
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <TypeBadge type={a.type} />
              <span className="text-[10px] text-muted-foreground">{NB_LABELS[a.normal_balance] || a.normal_balance}</span>
              {a.is_group && <span className="text-[10px] text-muted-foreground">grup</span>}
              {a.active === false && <span className="text-[10px] px-1.5 rounded border border-foreground/20">nonaktif</span>}
              <UsageBadge usage={a.usage} onClick={() => onUsage(a)} testId={`coa-usage-card-${a.code}`} />
            </div>
          </li>
        ))}
      </ul>
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-[var(--card-surface)] backdrop-blur-sm z-[1]">
            <tr className="text-left text-[11px] text-muted-foreground border-b border-[var(--glass-border)]">
              <th className="py-2 px-2 font-medium">Kode</th>
              <th className="py-2 px-2 font-medium">Nama</th>
              <th className="py-2 px-2 font-medium">Tipe</th>
              <th className="py-2 px-2 font-medium">Induk</th>
              <th className="py-2 px-2 font-medium">Saldo normal</th>
              <th className="py-2 px-2 font-medium">Penanda</th>
              <th className="py-2 px-2 font-medium">Keterikatan</th>
              <th className="py-2 px-2 font-medium text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {list.map((a) => {
              const fl = flagLabels(a.flags);
              return (
                <tr key={a.code} className={`border-b border-[var(--glass-border)] hover:bg-foreground/5 ${a.active === false ? 'opacity-60' : ''}`} data-testid={`coa-flat-${a.code}`}>
                  <td className="py-1.5 px-2 font-mono text-xs whitespace-nowrap">{a.code}</td>
                  <td className="py-1.5 px-2 min-w-[12rem]">{a.name}{a.is_group && <span className="text-[10px] text-muted-foreground ml-1">(grup)</span>}{a.active === false && <span className="text-[10px] text-muted-foreground ml-1">(nonaktif)</span>}</td>
                  <td className="py-1.5 px-2"><TypeBadge type={a.type} /></td>
                  <td className="py-1.5 px-2 font-mono text-xs text-muted-foreground">{a.parent_code || '—'}</td>
                  <td className="py-1.5 px-2 text-xs">{NB_LABELS[a.normal_balance] || a.normal_balance}{a.flags?.is_contra ? ' · kontra' : ''}</td>
                  <td className="py-1.5 px-2 text-[11px] text-muted-foreground" title={fl.join(', ')}>{fl.slice(0, 2).join(', ')}{fl.length > 2 ? ` +${fl.length - 2}` : ''}{!fl.length && '—'}</td>
                  <td className="py-1.5 px-2"><UsageBadge usage={a.usage} onClick={() => onUsage(a)} testId={`coa-usage-flat-${a.code}`} /></td>
                  <td className="py-1.5 px-2"><div className="flex justify-end"><RowActions acc={a} code={a.code} onEdit={onEdit} onDelete={onDelete} onReactivate={onReactivate} /></div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {q && <p className="sr-only">Hasil pencarian untuk {q}</p>}
    </>
  );
}

// ───────────────────────────── Modul utama ───────────────────────────────────
export default function RahazaCOAModule({ token, onNavigate }) {
  const api = useApi(token);
  const [accounts, setAccounts] = useState([]);
  const [integrity, setIntegrity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('aktif');
  const [typeFilter, setTypeFilter] = useState('');
  const [view, setView] = useState('tree');
  const [editing, setEditing] = useState(null);
  const [usageAcc, setUsageAcc] = useState(null);
  const [delAcc, setDelAcc] = useState(null);
  const [open, setOpen] = useState(new Set());
  const [openInit, setOpenInit] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true); setLoadError('');
    try {
      const [l, integ] = await Promise.all([
        api('GET', '/api/rahaza/coa/accounts?active_only=false&with_usage=true'),
        api('GET', '/api/rahaza/coa/integrity').catch(() => null),
      ]);
      setAccounts(Array.isArray(l) ? l : []);
      setIntegrity(integ);
    } catch (e) {
      setLoadError(e.message);
    } finally { setLoading(false); }
  }, [api]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const byCode = useMemo(() => new Map(accounts.map((a) => [a.code, a])), [accounts]);
  const tree = useMemo(() => buildTree(accounts), [accounts]);
  const defaultOpen = useMemo(() => {
    const s = new Set();
    const st = tree.map((n) => [n, 0]);
    while (st.length) {
      const [n, d] = st.pop();
      if (d < 2 && n.children.length) { s.add(n.code); n.children.forEach((c) => st.push([c, d + 1])); }
    }
    return s;
  }, [tree]);
  useEffect(() => { if (!openInit && accounts.length) { setOpen(defaultOpen); setOpenInit(true); } }, [accounts, defaultOpen, openInit]);

  const q = search.trim();
  const ql = q.toLowerCase();
  const matched = useMemo(() => new Set(accounts.filter((a) => {
    if (!passFilter(a, filter)) return false;
    if (typeFilter && a.type !== typeFilter) return false;
    if (!ql) return true;
    const hay = [a.code, a.name, TYPE_LABELS[a.type], ...flagLabels(a.flags), ...((a.usage && a.usage.labels) || [])];
    return hay.some((s) => (s || '').toLowerCase().includes(ql));
  }).map((a) => a.code)), [accounts, filter, typeFilter, ql]);
  // pencarian/filter TETAP dalam pohon: tampilkan yang cocok + leluhurnya
  const visible = useMemo(() => {
    const s = new Set(matched);
    matched.forEach((c) => {
      let p = byCode.get(c)?.parent_code;
      let hops = 0;
      while (p && byCode.has(p) && hops < 30) { s.add(p); p = byCode.get(p).parent_code; hops += 1; }
    });
    return s;
  }, [matched, byCode]);
  const filtering = !!q || filter !== 'aktif' || !!typeFilter;
  const prevFiltering = useRef(false);
  useEffect(() => {
    // saat mencari/memfilter: buka semua leluhur hasil; saat filter dilepas: kembali ke susunan bawaan
    if (filtering) setOpen(new Set(visible));
    else if (prevFiltering.current) setOpen(defaultOpen);
    prevFiltering.current = filtering;
  }, [filtering, visible, defaultOpen]);

  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, accounts.filter((a) => passFilter(a, f.key)).length])), [accounts]);
  const flatList = useMemo(() => accounts.filter((a) => matched.has(a.code)), [accounts, matched]);

  const openScreen = useCallback((scr, refId) => {
    if (!scr?.module) return;
    if (scr.view === 'posting' && refId) { try { sessionStorage.setItem('pp_focus_event', refId); } catch { /* noop */ } }
    // 2026-11-04: Bagan Akun & pemetaan sama-sama di Pengaturan Keuangan; tampilan di dalam tab
    // "Pemetaan akun otomatis" dipilih lewat petunjuk ini (dibaca AccountMappingModule).
    if (scr.view) { try { sessionStorage.setItem('account_mapping_view', scr.view); } catch { /* noop */ } }
    setUsageAcc(null); setDelAcc(null);
    setTimeout(() => {
      if (scr.module === 'fin-settings-hub' && scr.tab) {
        const trig = document.querySelector(`[data-testid="hub-tab-${scr.tab}"]`);
        if (trig) {
          trig.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
          trig.focus();
          return;
        }
      }
      if (typeof onNavigate === 'function') onNavigate(scr.module, scr.tab ? { tab: scr.tab } : {});
      else toast.info(`Buka layar: ${scr.label}`);
    }, 0);
  }, [onNavigate]);

  const reactivate = async (acc) => {
    try {
      await api('PUT', `/api/rahaza/coa/accounts/${acc.id}`, { active: true });
      toast.success(`Akun ${acc.code} aktif lagi.`);
      setUsageAcc(null);
      fetchData();
    } catch (e) { toast.error(e.message); }
  };

  const doSeed = async () => {
    try {
      const j = await api('POST', '/api/rahaza/coa/seed');
      toast.success(`Template dipasang: ${j.inserted} akun baru, ${j.skipped} sudah ada.`);
      fetchData();
    } catch (e) { toast.error(e.message); }
  };

  const sys = accounts.filter((a) => a.active !== false && a.usage?.level === 'SISTEM').length;
  const free = accounts.filter((a) => a.active !== false && a.usage?.level === 'BEBAS').length;
  const inactive = accounts.filter((a) => a.active === false).length;

  // PANDUAN_UI G1/G6 (2026-11-04): cetakan PageLayout — cari, tipe, dan pil keterikatan di toolbar kiri; pohon/tabel,
  // buka/tutup semua, muat ulang, impor/unduh di kanan; ringkasan satu baris. Dulu semuanya bertumpuk di dalam kartu.
  return (
    <PageLayout
      testId="rahaza-coa-page"
      title="Bagan Akun"
      subtitle="Lencana menandai akun yang dipakai sistem — klik akun untuk melihat dipakai di mana sebelum mengubah atau menghapus."
      actions={(
        <Button onClick={() => setEditing({})} data-testid="coa-add">
          <Plus className="w-4 h-4" />Tambah akun
        </Button>
      )}
      filters={<>
        <div className="relative w-72 max-w-full">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
          <GlassInput value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Cari kode, nama, penanda, keterikatan…"
            className="pl-8 pr-8 h-9" aria-label="Cari akun" data-testid="coa-search" />
          {search && (
            <Button variant="ghost" size="icon-sm" onClick={() => setSearch('')} className="absolute right-1 top-1/2 -translate-y-1/2" aria-label="Hapus pencarian" title="Hapus pencarian">
              <X className="w-4 h-4" />
            </Button>
          )}
        </div>
        <SmartNativeSelect value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="h-9 w-44" aria-label="Filter tipe" data-testid="coa-type-filter" searchable={false}>
          <option value="">Semua tipe</option>
          {TYPE_ORDER.map((t) => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
        </SmartNativeSelect>
        <FilterChips value={filter} onChange={setFilter} testId="coa-filter" ariaLabel="Filter keterikatan" hideWhenEmpty={false}
          options={FILTERS.map((f) => ({ key: f.key, label: f.label, count: counts[f.key] ?? 0 }))} />
      </>}
      tools={<>
        {view === 'tree' && (
          <>
            <Button variant="outline" size="icon" onClick={() => setOpen(new Set(accounts.map((a) => a.code)))} aria-label="Buka semua" title="Buka semua">
              <ChevronsUpDown className="w-4 h-4" />
            </Button>
            <Button variant="outline" size="icon" onClick={() => setOpen(new Set())} aria-label="Tutup semua" title="Tutup semua">
              <ChevronsDownUp className="w-4 h-4" />
            </Button>
          </>
        )}
        <ViewToggle value={view} onChange={setView} testId="coa-view"
          options={[{ key: 'tree', label: 'Tampilan pohon', icon: FolderTree }, { key: 'flat', label: 'Tampilan tabel', icon: Table2 }]} />
        <Button variant="outline" size="icon" onClick={fetchData} aria-label="Muat ulang" title="Muat ulang" data-testid="coa-refresh">
          <RefreshCw className="w-4 h-4" />
        </Button>
        <ImportExportToolbar collectionKey="coa_accounts" label="Bagan Akun" onImported={fetchData} />
      </>}
      summary={<>
        <IntegrityBanner data={integrity} openScreen={openScreen} />
        <p className="text-sm text-muted-foreground" data-testid="coa-summary">
          <span className="font-semibold text-foreground">{accounts.length - inactive}</span> aktif ·{' '}
          <span className="text-[hsl(var(--destructive))] font-medium">{sys} dipakai sistem</span> · {free} bebas · {inactive} nonaktif
          {filtering && <> · <span className="text-foreground">{matched.size} cocok</span></>}
          <span className="ml-2 inline-flex items-center gap-1 text-xs" title="Dipakai sistem = tidak bisa dihapus · Struktur = induk/penanda laporan · Bawaan = akun sistem (bisa dinonaktifkan) · Bebas = aman dihapus">
            <Info className="w-3.5 h-3.5" aria-hidden="true" />arti lencana
          </span>
        </p>
      </>}
      detail={usageAcc && (
        <UsagePanel acc={usageAcc} api={api} onClose={() => setUsageAcc(null)} openScreen={openScreen}
          onEdit={(a) => { setUsageAcc(null); setEditing(a); }} onDelete={(a) => { setUsageAcc(null); setDelAcc(a); }} onReactivate={reactivate} />
      )}
    >
      <GlassCard className="p-3 sm:p-4 min-w-0">
        <div>
          {loading && <div className="py-12 grid place-items-center text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin" /></div>}
          {!loading && loadError && <p className="py-6 text-center text-sm text-red-600 dark:text-red-400">{loadError}</p>}
          {!loading && !loadError && accounts.length === 0 && (
            <div className="py-12 text-center space-y-3">
              <div className="text-muted-foreground">Bagan Akun masih kosong.</div>
              <Button onClick={doSeed} data-testid="coa-seed-empty"><Sparkles className="w-4 h-4 mr-1.5" />Pasang template PSAK garmen</Button>
            </div>
          )}
          {!loading && accounts.length > 0 && view === 'tree' && (
            <CoaTreeView tree={tree} open={open} setOpen={setOpen} visible={visible} matched={filtering ? matched : undefined} q={q}
              onEdit={setEditing} onDelete={setDelAcc} onReactivate={reactivate} onUsage={setUsageAcc} />
          )}
          {!loading && accounts.length > 0 && view === 'flat' && (
            <AccountCards list={flatList} q={q} onEdit={setEditing} onDelete={setDelAcc} onReactivate={reactivate} onUsage={setUsageAcc} />
          )}
        </div>
      </GlassCard>

      {editing && (
        <AccountEditorDialog initial={editing.id ? editing : null} accounts={accounts} api={api}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); fetchData(); }} />
      )}
      <DeleteDialog acc={delAcc} api={api} onClose={() => setDelAcc(null)} openUsage={setUsageAcc}
        onDone={() => { setDelAcc(null); fetchData(); }} />
    </PageLayout>
  );
}
