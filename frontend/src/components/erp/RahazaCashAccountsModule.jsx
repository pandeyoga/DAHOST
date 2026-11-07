import { Fragment, useState, useEffect, useCallback, useMemo } from 'react';
import { Plus, RefreshCw, Wallet, AlertTriangle, MoreHorizontal } from 'lucide-react';
import { GlassCard, GlassInput } from '@/components/ui/glass';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import TombolUnduh from '@/components/ui/tombol-unduh';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import { EmptyState, Notice } from './moduleAtoms';
import PageLayout, { DetailPanel, RowDetail, RowToggle } from './layout/PageLayout';
import JournalLinesInline from './finance/JournalLinesInline';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import { JOURNAL_SOURCE_LABELS, journalSourceLabel } from '@/lib/financeLabels';

// Jenis mutasi: label Indonesia dari peta sumber jurnal bila kodenya dikenal (server kadang mengirim label Inggris,
// mis. "Petty Cash Expense").
const jenisMutasi = (m) => (JOURNAL_SOURCE_LABELS[m.category] ? journalSourceLabel(m.category) : (m.category_label || journalSourceLabel(m.category)));
import { formatRupiah, formatDateID, formatNumber } from '@/lib/format';
import PaginationLite from '@/components/ui/pagination-lite';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { toast } from 'sonner';
import { CV_DA, CV_SMU, cvLabel, ownerLabel, useCv } from '@/lib/entitas';

const fmt = formatRupiah;

const MUT_PAGE = 50;
const WALLET_RX = /gopay|\bdana\b|shopeepay|ovo|flazz|linkaja|e-?wallet/i;

/** Kelompok rekening untuk tabel: Kas · per bank · Dompet digital · Lainnya (PANDUAN_UI G5). */
function groupOf(a) {
  if (a.type === 'cash') return 'Kas';
  if (WALLET_RX.test(`${a.name} ${a.bank_name || ''}`)) return 'Dompet digital';
  const b = (a.bank_name || '').trim() || (a.name.match(/^Bank\s+\w+/i) || [''])[0];
  return b ? b.replace(/^bank\s+/i, 'Bank ') : 'Lainnya';
}
/** "Bank BCA – CV Dekka Karya Utama" di kelompok "Bank BCA" cukup ditulis "CV Dekka Karya Utama". */
const shortName = (a, grp) => {
  const n = a.name.replace(new RegExp(`^${grp.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*[–-]\\s*`, 'i'), '');
  return n && n !== a.name ? n : a.name;
};

/**
 * Rekening & Mutasi (menu Keuangan › Kas & Bank).
 * 2026-11-04 (audit Keuangan): Kas Kecil = rekening kas biasa di sini; mutasi per halaman dari yang terbaru.
 * 2026-11-04 (PANDUAN_UI G5): satu tabel berkelompok (Kas · bank · dompet digital) — dulu satu kartu besar
 * per rekening. Ubah/nonaktifkan lewat menu ⋯.
 * 2026-11-04 (PANDUAN_UI G13, arahan owner): memakai cetakan PageLayout. Mutasi dibuka DI HALAMAN di atas
 * tabel (dulu panel samping yang sempit — kolom Saldo terpotong); nomor jurnal dibuka di bawah barisnya.
 */
export default function RahazaCashAccountsModule({ token }) {
  const [accounts, setAccounts] = useState([]);
  const [movements, setMovements] = useState([]);
  const [selected, setSelected] = useState(null);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showIdle, setShowIdle] = useState(false);
  const [mutPage, setMutPage] = useState(1);
  const [openJe, setOpenJe] = useState(null);
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  // Tahap 8 (dua CV): daftar disaring backend per CV terpilih (header X-CV); rekening baru = milik CV terpilih.
  const cvCtx = useCv();
  const defaultOwner = cvCtx && (cvCtx.cv === CV_DA || cvCtx.cv === CV_SMU) ? cvCtx.cv : CV_DA;

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/rahaza/cash-accounts', { headers });
      if (r.ok) setAccounts(await r.json());
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);

  // K19: daftar mutasi DITURUNKAN DARI BUKU BESAR (baris jurnal akun rekening). Mutasi tercatat lama hanya metadata.
  const [mutInfo, setMutInfo] = useState(null);
  const fetchMovements = async (account_id, page = 1) => {
    setMovements([]); setMutInfo(null); setMutPage(page); setOpenJe(null);
    const r = await fetch(`/api/rahaza/finance/reports/cash-mutations?account_id=${account_id}&page=${page}&page_size=${MUT_PAGE}`, { headers });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error(d.detail || `Gagal memuat mutasi (HTTP ${r.status})`); return; }
    setMovements(d.rows || []); setMutInfo(d);
  };
  // Unduh mutasi: SEMUA halaman (500 per permintaan, batas server), bukan hanya halaman yang tampil.
  const ambilSemuaMutasi = async () => {
    const out = [];
    for (let page = 1; page < 200; page += 1) {
      const r = await fetch(`/api/rahaza/finance/reports/cash-mutations?account_id=${selected.id}&page=${page}&page_size=500`, { headers });
      if (!r.ok) throw new Error('gagal');
      const d = await r.json();
      out.push(...(d.rows || []));
      if (out.length >= (d.count || 0) || !(d.rows || []).length) break;
    }
    return out;
  };
  const openAccount = (a) => { setSelected(a); fetchMovements(a.id, 1); };
  const toggleAccount = (a) => (selected?.id === a.id ? setSelected(null) : openAccount(a));

  const save = async (body) => {
    const url = body.id ? `/api/rahaza/cash-accounts/${body.id}` : '/api/rahaza/cash-accounts';
    const method = body.id ? 'PUT' : 'POST';
    const r = await fetch(url, { method, headers, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error(d.detail || `Gagal menyimpan rekening (HTTP ${r.status})`); return; }
    if (d._opening_post && d._opening_post.je_number) toast.success(`Rekening dibuat · saldo awal dijurnal ${d._opening_post.je_number}`);
    else if (d._opening_post && d._opening_post.error) toast.error(`Rekening dibuat, tetapi jurnal saldo awal GAGAL: ${d._opening_post.error}`);
    setEditing(null); fetchAccounts();
  };
  const del = async (a) => {
    if (!(await confirmDialog({ title: `Nonaktifkan ${a.name}?`, body: 'Rekening tidak bisa dipilih lagi untuk transaksi baru. Riwayat mutasinya tetap ada.', confirmLabel: 'Nonaktifkan', danger: true }))) return;
    const r = await fetch(`/api/rahaza/cash-accounts/${a.id}`, { method: 'DELETE', headers });
    if (!r.ok) { const d = await r.json().catch(() => ({})); toast.error(d.detail || `Gagal menonaktifkan rekening (HTTP ${r.status})`); }
    fetchAccounts();
  };

  const total = accounts.reduce((s, a) => s + (Number(a.balance) || 0), 0);
  const mismatch = accounts.filter((a) => a.balance_source === 'gl' && a.balance_diff !== 0);
  const noGl = accounts.filter((a) => a.balance_source !== 'gl');
  const isIdle = (a) => Math.abs(Number(a.balance) || 0) < 0.5 && !Number(a.mutation_count || 0);
  const idle = accounts.filter(isIdle);
  const shown = showIdle ? accounts : accounts.filter((a) => !isIdle(a));
  const groups = useMemo(() => {
    const m = new Map();
    for (const a of shown) { const g = groupOf(a); if (!m.has(g)) m.set(g, []); m.get(g).push(a); }
    return [...m.entries()]
      .map(([name, list]) => ({ name, list: list.sort((x, y) => Number(y.balance || 0) - Number(x.balance || 0)), total: list.reduce((s, a) => s + Number(a.balance || 0), 0) }))
      .sort((x, y) => (x.name === 'Kas' ? -1 : y.name === 'Kas' ? 1 : y.total - x.total));
  }, [shown]);
  const mutPages = Math.max(1, Math.ceil((mutInfo?.count || 0) / MUT_PAGE));

  const warning = (mismatch.length > 0 || noGl.length > 0) && (
    <Notice tone="warning" icon={AlertTriangle} testId="ca-gl-warning" className="text-xs">
      <div className="space-y-1">
        {mismatch.length > 0 && <p>{mismatch.length} rekening saldo buku besar ≠ saldo mutasi ({mismatch.map((a) => a.code).join(', ')}). Angka memakai buku besar; selisih berarti ada mutasi yang belum dijurnal.</p>}
        {noGl.length > 0 && <p>{noGl.length} rekening belum punya akun buku besar ({noGl.map((a) => a.code).join(', ')}). Minta admin menjalankan “Sinkron Bagan Akun & GL” di Adm. Sistem › Perawatan Data Keuangan.</p>}
      </div>
    </Notice>
  );

  const detail = selected && (
    <DetailPanel
      title={`Mutasi ${selected.name}`}
      description={mutInfo ? `${mutInfo.count} mutasi · masuk ${fmt(mutInfo.total_in)} · keluar ${fmt(mutInfo.total_out)} · saldo ${fmt(mutInfo.closing)}` : 'Memuat…'}
      onClose={() => setSelected(null)}
      testId="ca-movements-panel"
      actions={
        <TombolUnduh namaBerkas={`mutasi-${selected.code || selected.name}`} namaLembar="Mutasi" baris={movements}
          ambilSemua={ambilSemuaMutasi} testId="ca-mutasi-unduh"
          kolom={[
            { label: 'Tanggal', nilai: (m) => formatDateID(m.date) },
            { label: 'Jurnal', nilai: (m) => m.je_number || '' },
            { label: 'Jenis', nilai: jenisMutasi },
            { label: 'Keterangan', nilai: (m) => m.ref_label || m.description || '' },
            { label: 'Masuk', nilai: (m) => (m.direction === 'in' ? Number(m.amount) || 0 : '') },
            { label: 'Keluar', nilai: (m) => (m.direction === 'out' ? Number(m.amount) || 0 : '') },
            { label: 'Saldo', nilai: (m) => Number(m.running_balance) || 0 },
          ]} />
      }
    >
      {mutInfo && movements.length === 0 ? (
        <EmptyState icon={Wallet} title="Belum ada mutasi" description="Mutasi muncul setelah ada jurnal yang memakai rekening ini." />
      ) : (
        <Table data-testid="ca-mutations-table">
          <TableHeader><TableRow>
            <TableHead className="w-10" /><TableHead>Tanggal</TableHead><TableHead>Jurnal</TableHead>
            <TableHead className="hidden md:table-cell">Jenis</TableHead><TableHead>Keterangan</TableHead>
            <TableHead className="text-right">Masuk</TableHead><TableHead className="text-right">Keluar</TableHead><TableHead className="text-right">Saldo</TableHead>
          </TableRow></TableHeader>
          <TableBody>{movements.map((m) => {
            const open = openJe === m.id;
            const toggle = () => setOpenJe(open ? null : m.id);
            return (
              <Fragment key={m.id}>
                <TableRow data-testid={`ca-mut-${m.source_module}`} className={open ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                  <TableCell>{m.je_id && <RowToggle open={open} onClick={toggle} label="Lihat isi jurnal" testId={`ca-je-toggle-${m.je_number}`} />}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatDateID(m.date)}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {m.je_id ? <Button variant="link" size="sm" className="h-auto p-0" onClick={toggle}>{m.je_number}</Button> : (m.je_number || '—')}
                  </TableCell>
                  <TableCell className="hidden md:table-cell">{jenisMutasi(m)}</TableCell>
                  <TableCell className="min-w-[12rem] whitespace-normal">{m.ref_label || m.description || '—'}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{m.direction === 'in' ? formatNumber(m.amount) : ''}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{m.direction === 'out' ? formatNumber(m.amount) : ''}</TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">{formatNumber(m.running_balance)}</TableCell>
                </TableRow>
                {open && <RowDetail colSpan={8} testId={`ca-je-detail-${m.je_number}`}><JournalLinesInline jeId={m.je_id} token={token} /></RowDetail>}
              </Fragment>
            );
          })}
          </TableBody>
        </Table>
      )}
      {mutPages > 1 && (
        <PaginationLite page={mutPage} totalPages={mutPages} total={mutInfo?.count || 0} pageSize={MUT_PAGE}
          onPageChange={(p) => fetchMovements(selected.id, p)} />
      )}
    </DetailPanel>
  );

  return (
    <PageLayout
      testId="rahaza-cash-page"
      title="Rekening & Mutasi"
      subtitle="Saldo dan mutasi tiap rekening dari buku besar. Kas Kecil termasuk di sini."
      actions={<Button onClick={() => setEditing({ code: '', name: '', type: 'cash', opening_balance: 0, entity: defaultOwner })} data-testid="ca-add"><Plus className="w-4 h-4" />Rekening baru</Button>}
      tools={<>
        <TombolUnduh namaBerkas="rekening-kas-bank" namaLembar="Rekening" testId="ca-unduh"
          baris={groups.flatMap((g) => g.list.map((a) => ({ ...a, _grp: g.name })))}
          kolom={[
            { label: 'Kelompok', nilai: (a) => a._grp },
            { label: 'Kode', nilai: (a) => a.code },
            { label: 'Rekening', nilai: (a) => a.name },
            { label: 'No. rekening', nilai: (a) => a.account_number || '' },
            { label: 'Milik', nilai: (a) => ownerLabel(a.entity) },
            { label: 'Akun buku besar', nilai: (a) => a.gl_account_code || '' },
            { label: 'Saldo', nilai: (a) => Number(a.balance) || 0 },
            { label: 'Jumlah mutasi', nilai: (a) => Number(a.mutation_count) || 0 },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchAccounts} title="Muat ulang" aria-label="Muat ulang"><RefreshCw className="w-4 h-4" /></Button>
      </>}
      summary={<>
        <p className="text-sm text-muted-foreground" data-testid="ca-total-gl">Total saldo semua rekening <b className="text-foreground tabular-nums">{fmt(total)}</b> · {shown.length} rekening tampil{!showIdle && idle.length > 0 ? ` (${idle.length} tanpa saldo & mutasi disembunyikan)` : ''}</p>
        {warning}
      </>}
      detail={detail}
      footer={idle.length > 0 && (
        <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setShowIdle((v) => !v)} data-testid="ca-toggle-idle">
          {showIdle ? 'Sembunyikan rekening tanpa saldo & mutasi' : `Tampilkan ${idle.length} rekening tanpa saldo & mutasi`}
        </Button>
      )}
    >
      <GlassCard className="p-0 overflow-hidden">
        {accounts.length === 0 && !loading ? (
          <EmptyState icon={Wallet} title="Belum ada rekening" description="Tambahkan rekening kas atau bank untuk mulai mencatat mutasi." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="ca-table">
              <thead>
                <tr><th className="text-left">Rekening</th><th className="text-left hidden md:table-cell">No. rekening</th><th className="text-left hidden md:table-cell">Milik</th><th className="text-right">Saldo</th><th className="text-right hidden sm:table-cell">Mutasi</th><th className="w-12" /></tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <Fragment key={g.name}>
                    <tr className="bg-[hsl(var(--muted))]/50">
                      <td className="font-semibold text-foreground">{g.name}</td>
                      <td className="hidden md:table-cell" /><td className="hidden md:table-cell" />
                      <td className="text-right font-semibold tabular-nums">{formatNumber(g.total)}</td>
                      <td className="hidden sm:table-cell" /><td />
                    </tr>
                    {g.list.map((a) => (
                      <tr key={a.id} data-testid={`ca-card-${a.code}`} className={selected?.id === a.id ? 'bg-[hsl(var(--primary)/0.06)]' : ''}>
                        <td className="pl-6">
                          <Button variant="link" size="sm" className="h-auto p-0 text-left text-foreground whitespace-normal" onClick={() => toggleAccount(a)} title={`Akun buku besar ${a.gl_account_code || '—'}`}>
                            {shortName(a, g.name)}
                          </Button>
                          {a.balance_source !== 'gl' && <span className="ml-2 text-xs text-[hsl(var(--warning))]">belum tertaut buku besar</span>}
                          {a.balance_source === 'gl' && a.balance_diff !== 0 && <span className="ml-2 text-xs text-[hsl(var(--warning))]" data-testid={`ca-diff-${a.code}`}>selisih {formatNumber(a.balance_diff)}</span>}
                        </td>
                        <td className="text-muted-foreground hidden md:table-cell">{a.account_number || '—'}</td>
                        <td className="text-muted-foreground whitespace-nowrap hidden md:table-cell" data-testid={`ca-owner-${a.code}`}>{ownerLabel(a.entity)}</td>
                        <td className={`text-right tabular-nums ${Number(a.balance) < 0 ? 'text-[hsl(var(--destructive))]' : 'text-foreground'}`} data-testid={`ca-balance-${a.code}`}>{formatNumber(a.balance)}</td>
                        <td className="text-right hidden sm:table-cell">
                          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => toggleAccount(a)}>
                            {selected?.id === a.id ? 'Tutup mutasi' : 'Lihat mutasi'}
                          </Button>
                        </td>
                        <td className="text-right">
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="ghost" size="icon-sm" aria-label={`Menu ${a.name}`} title="Lainnya"><MoreHorizontal className="w-4 h-4" /></Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => openAccount(a)}>Lihat mutasi</DropdownMenuItem>
                              <DropdownMenuItem onClick={() => setEditing({ ...a })}>Ubah rekening</DropdownMenuItem>
                              <DropdownMenuItem className="text-[hsl(var(--destructive))]" onClick={() => del(a)}>Nonaktifkan</DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
      {editing && <CAEditor value={editing} onClose={() => setEditing(null)} onSave={save} headers={headers} />}
    </PageLayout>
  );
}

function CAEditor({ value, onClose, onSave, headers }) {
  const [s, setS] = useState(value);
  const [glOptions, setGlOptions] = useState([]);
  const upd = (k, v) => setS(x => ({ ...x, [k]: v }));
  useEffect(() => {
    if (s.id) return;
    fetch('/api/rahaza/cash-accounts/gl-candidates', { headers }).then(r => (r.ok ? r.json() : [])).then(setGlOptions).catch(() => setGlOptions([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const pickGl = (code) => {
    const o = glOptions.find(x => x.code === code);
    setS(x => ({ ...x, gl_account_code: code, code: o ? code : x.code, name: o && !x.name ? o.name : x.name, type: o ? (code.startsWith('1-11') ? 'cash' : 'bank') : x.type }));
  };
  // 2026-11-07 (audit form Tahap 5): kode & nama wajib disebut sebelum simpan (dulu baru ditolak server).
  // 2026-11-08 (Standar UI/UX v2): popup form standar (FormPopup pendek, Isian, Simpan hijau).
  const missing = !String(s.code || '').trim() ? 'Isi kode rekening.' : !String(s.name || '').trim() ? 'Isi nama rekening.' : '';
  return (
    <FormPopup open onClose={onClose} ukuran="pendek" testId="ca-editor"
      judul={s.id ? `Ubah rekening ${s.code}` : 'Rekening baru'}
      keterangan={s.id ? undefined : 'Rekening kas atau bank yang saldonya dihitung dari buku besar.'}
      onSimpan={() => onSave(s)} bisaSimpan={!missing} galat={missing && (s.code || s.name) ? missing : undefined}>
      {!s.id && (
        <Isian label="Akun buku besar (Bagan Akun)"
          petunjuk={glOptions.length ? `${glOptions.length} akun kas/bank di Bagan Akun belum punya rekening — pilih supaya tidak dobel.` : 'Semua akun kas/bank di Bagan Akun sudah punya rekening.'}>
          <SmartNativeSelect value={s.gl_account_code || ''} onChange={e => pickGl(e.target.value)} className="w-full h-9"
            searchPlaceholder="Cari kode atau nama akun…" data-testid="ca-gl-select">
            <option value="">— Buat akun baru otomatis di bawah Kas/Bank —</option>
            {glOptions.map(o => <option key={o.code} value={o.code}>{`${o.code} · ${o.name}`}</option>)}
          </SmartNativeSelect>
        </Isian>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Isian label="Kode" wajib htmlFor="ca-code"><GlassInput id="ca-code" value={s.code} onChange={e => upd('code', e.target.value.toUpperCase())} disabled={!!s.id} data-testid="ca-code" /></Isian>
        <Isian label="Nama" wajib htmlFor="ca-name"><GlassInput id="ca-name" value={s.name} onChange={e => upd('name', e.target.value)} data-testid="ca-name" /></Isian>
        <Isian label="Milik CV" petunjuk="Hanya bisa dipakai transaksi buku CV pemiliknya.">
          <SmartNativeSelect value={s.entity || CV_DA} onChange={e => upd('entity', e.target.value)} searchable={false} className="w-full h-9" data-testid="ca-entity">
            <option value={CV_DA}>{cvLabel(CV_DA)}</option><option value={CV_SMU}>{cvLabel(CV_SMU)}</option>
          </SmartNativeSelect>
        </Isian>
        <Isian label="Jenis">
          <SmartNativeSelect value={s.type} onChange={e => upd('type', e.target.value)} searchable={false} className="w-full h-9" data-testid="ca-type">
            <option value="cash">Kas</option><option value="bank">Bank</option>
          </SmartNativeSelect>
        </Isian>
        {s.type === 'bank' && <>
          <Isian label="Nama bank" htmlFor="ca-bank-name"><GlassInput id="ca-bank-name" value={s.bank_name || ''} onChange={e => upd('bank_name', e.target.value)} data-testid="ca-bank-name" /></Isian>
          <Isian label="Nomor rekening" htmlFor="ca-acc-no"><GlassInput id="ca-acc-no" value={s.account_number || ''} onChange={e => upd('account_number', e.target.value)} data-testid="ca-account-number" /></Isian>
        </>}
        {!s.id && <Isian label="Saldo awal"><MoneyInput glass value={s.opening_balance || 0} onChange={e => upd('opening_balance', Number(e.target.value))} data-testid="ca-opening" /></Isian>}
      </div>
    </FormPopup>
  );
}
