/**
 * AssetDetailDrawer — detail satu aset: Info, Penyusutan, Penugasan, Pemeliharaan.
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *  • panel samping (Sheet) → DetailPopup; tombol aset (Cetak label, Pindahkan, Ajukan pelepasan / Lepas aset)
 *    di kepala popup; "Lepas aset" memakai dialog konfirmasi aplikasi (dulu konfirmasi bawaan peramban);
 *  • kotak abu ber-label HURUF BESAR → baris detail (BarisDetail); kotak biru/hijau ber-emoji untuk garansi &
 *    asuransi → bagian biasa dengan lencana "Sudah habis / Habis < 30 hari";
 *  • form di dalam panel (tugaskan, catat pemeliharaan, posting penyusutan) → tombol yang membuka popup form
 *    standar; isian tanggal/bulan bawaan peramban → DatePicker / pilihan bulan;
 *  • riwayat penyusutan, penugasan, pemeliharaan = tabel yang bisa diunduh.
 * Endpoint, isian, dan aturan (batas Rp 5 juta untuk pelepasan lewat persetujuan) tidak berubah.
 */
import { useState, useEffect, useRef } from 'react';
import {
  ArrowRight, Camera, Package, Printer, Trash2, TrendingDown, UserPlus, Undo2, Wrench,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MoneyInput } from '@/components/ui/money-input';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import FormPopup, { Isian } from '@/components/ui/form-popup';
import DatePicker from '@/components/ui/date-picker';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { confirmDialog } from '@/components/ui/confirm-dialog';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { todayWIB, thisMonthWIB, toWIBDate, daysAheadWIB } from '@/lib/waktu';
import { monthOptions } from '../../finance/PeriodPicker';
import { Notice, StatusBadge as Lencana } from '../../moduleAtoms';
import { angka, apicall, fmtCurrency, fmtDate, fmtPersen, API } from '../utils';
import { StatusBadge } from '../components/StatusBadge';
import { Bagian } from '../components/KPICard';
import { STATUS_CONFIG, MAINT_TYPE_LABEL, MAINT_STATUS_LABEL } from '../constants';

const BATAS_PERSETUJUAN = 5_000_000;
/** Riwayat penyusutan: catatan lama Portal Aset memakai amount/cumulative; jadwal registri Keuangan (aset tertaut)
 *  memakai depr_amount/accumulated_depr — dulu kolom ini tampil kosong untuk aset tertaut. */
const nilaiSusut = (d) => d.amount ?? d.depr_amount;
const akumSusut = (d) => d.cumulative ?? d.accumulated_depr;
const MAINT_KOSONG = () => ({ type: 'corrective', description: '', cost: '', performed_by: '', maintenance_date: todayWIB(), status: 'completed' });

/** Lencana masa berlaku garansi/asuransi. */
function MasaBerlaku({ tanggal }) {
  if (!tanggal) return null;
  const t = toWIBDate(tanggal);
  if (t < todayWIB()) return <Lencana status="habis" label="Sudah habis" tone="danger" />;
  if (t < daysAheadWIB(30)) return <Lencana status="segera" label="Habis < 30 hari" tone="warning" />;
  return null;
}

export function AssetDetailDrawer({ asset: assetProp, token, open, onClose, onRefresh, onTransferClick, onRequestDisposalClick }) {
  const [detail, setDetail] = useState(assetProp);
  const [deprPeriod, setDeprPeriod] = useState(thisMonthWIB());
  const [assignForm, setAssignForm] = useState({ user_id: '', user_name: '', notes: '' });
  const [maintForm, setMaintForm] = useState(MAINT_KOSONG);
  const [activeTab, setActiveTab] = useState('info');
  const [loading, setLoading] = useState(false);
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [assignments, setAssignments] = useState([]);
  const [maintenance, setMaintenance] = useState([]);
  const [popup, setPopup] = useState(null);        // null | 'tugas' | 'rawat' | 'susut'
  const [galat, setGalat] = useState('');
  const photoInputRef = useRef(null);

  // Keep local `detail` in sync when the parent passes a new/updated asset object.
  useEffect(() => { setDetail(assetProp); }, [assetProp]);

  // On open (or asset change) load the full detail (nbv + depreciation_history) and sub-lists.
  useEffect(() => {
    if (!open || !assetProp?.id) return;
    apicall('GET', `/api/assets/${assetProp.id}`, token).then(d => { if (d?.id) setDetail(d); }).catch(() => {});
    apicall('GET', `/api/assets/${assetProp.id}/assignments`, token).then(d => setAssignments(Array.isArray(d) ? d : [])).catch(() => {});
    apicall('GET', `/api/assets/${assetProp.id}/maintenance`, token).then(d => setMaintenance(Array.isArray(d) ? d : [])).catch(() => {});
  }, [open, assetProp, token]);

  if (!assetProp && !detail) return null;

  // `asset` is the freshest known state (detail from GET /{id}, falling back to the list prop).
  const asset = detail || assetProp;

  // Re-fetch this asset's detail + assignments after a mutation so the popup reflects changes live.
  const reloadDetail = async () => {
    if (!assetProp?.id) return;
    try {
      const [d, asg] = await Promise.all([
        apicall('GET', `/api/assets/${assetProp.id}`, token),
        apicall('GET', `/api/assets/${assetProp.id}/assignments`, token),
      ]);
      if (d?.id) setDetail(d);
      setAssignments(Array.isArray(asg) ? asg : []);
    } catch { /* noop */ }
  };

  const nbv = (asset.purchase_cost || 0) - (asset.accumulated_depreciation || 0);
  const deprPct = asset.purchase_cost > 0
    ? Math.min(100, Math.round(asset.accumulated_depreciation / asset.purchase_cost * 100))
    : 0;

  const handlePhotoUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      toast.error('Berkas harus berupa gambar');
      return;
    }

    if (file.size > 5 * 1024 * 1024) {
      toast.error('Ukuran foto maksimal 5 MB');
      return;
    }

    setUploadingPhoto(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API}/api/assets/${asset.id}/upload-photo`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });

      if (!res.ok) throw new Error('Unggah gagal');

      await res.json();
      toast.success('Foto aset berhasil diunggah');
      onRefresh();
    } catch {
      toast.error('Gagal mengunggah foto');
    } finally {
      setUploadingPhoto(false);
      if (photoInputRef.current) photoInputRef.current.value = '';
    }
  };

  const bukaPopup = (jenis) => { setGalat(''); setPopup(jenis); };

  const postDepr = async () => {
    if (!deprPeriod) return;
    setLoading(true); setGalat('');
    try {
      const d = await apicall('POST', `/api/assets/${asset.id}/depreciate/${deprPeriod}`, token, {});
      if (d.id) {
        toast.success(`Penyusutan ${deprPeriod} diposting: ${fmtCurrency(d.amount)}`);
        setPopup(null);
        await reloadDetail(); onRefresh();
      } else setGalat(d.detail || 'Gagal posting penyusutan.');
    } catch (e) { setGalat(e.message || 'Gagal posting penyusutan.'); }
    finally { setLoading(false); }
  };

  const assignAsset = async () => {
    if (!assignForm.user_id) { setGalat('ID karyawan wajib diisi.'); return; }
    setLoading(true); setGalat('');
    try {
      await apicall('POST', `/api/assets/${asset.id}/assign`, token, assignForm);
      toast.success('Aset berhasil ditugaskan');
      setAssignForm({ user_id: '', user_name: '', notes: '' });
      setPopup(null);
      await reloadDetail(); onRefresh();
    } catch (e) { setGalat(e.message || 'Gagal menugaskan aset.'); }
    finally { setLoading(false); }
  };

  const unassign = async () => {
    try {
      await apicall('POST', `/api/assets/${asset.id}/unassign`, token, {});
      toast.success('Aset dikembalikan'); await reloadDetail(); onRefresh();
    } catch (e) { toast.error(e.message || 'Gagal mengembalikan aset'); }
  };

  const addMaintenance = async () => {
    if (!maintForm.description) { setGalat('Uraian pemeliharaan wajib diisi.'); return; }
    setLoading(true); setGalat('');
    try {
      await apicall('POST', `/api/assets/${asset.id}/maintenance`, token, {
        ...maintForm, cost: Number(maintForm.cost) || 0,
      });
      toast.success('Pemeliharaan berhasil dicatat');
      const d = await apicall('GET', `/api/assets/${asset.id}/maintenance`, token);
      setMaintenance(Array.isArray(d) ? d : []);
      await reloadDetail();
      setMaintForm(MAINT_KOSONG());
      setPopup(null);
    } catch (e) { setGalat(e.message || 'Gagal mencatat pemeliharaan.'); }
    finally { setLoading(false); }
  };

  const disposeAsset = async () => {
    const ok = await confirmDialog({
      title: `Lepas aset ${asset.asset_number}?`,
      body: `${asset.name} dicatat sebagai dilepas hari ini dengan nilai jual Rp 0.`,
      confirmLabel: 'Lepas aset', danger: true,
    });
    if (!ok) return;
    setLoading(true);
    try {
      const d = await apicall('POST', `/api/assets/${asset.id}/dispose`, token, { disposal_date: todayWIB(), disposal_value: 0, reason: 'Disposal' });
      if (d.ok) { toast.success('Aset berhasil dilepas'); onRefresh(); onClose(); }
      else toast.error(d.detail || 'Gagal');
    } catch (e) { toast.error(e.message || 'Gagal'); }
    finally { setLoading(false); }
  };

  const cetakLabel = (template) => window.open(`${API}/api/assets/${asset.id}/label-pdf?template=${template}`, '_blank');

  const bisaDiubah = asset.status !== 'disposed' && asset.status !== 'pending_disposal';
  const perluPersetujuan = (parseFloat(asset.purchase_cost || 0) - parseFloat(asset.accumulated_depreciation || 0)) > BATAS_PERSETUJUAN;
  const riwayatSusut = asset.depreciation_history || [];
  const adaGaransi = asset.warranty_expiry_date || asset.warranty_provider;
  const adaAsuransi = asset.insurance_policy_number || asset.insurance_provider;

  return (
    <>
      <DetailPopup open={open} onClose={onClose} judul={asset.name} testId="asset-detail"
        keterangan={[asset.asset_number, asset.category_name].filter(Boolean).join(' · ')}
        status={<StatusBadge status={asset.status} configMap={STATUS_CONFIG} />}
        aksi={<>
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" data-testid="print-label-btn"><Printer />Cetak label</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => cetakLabel('standard')} data-testid="print-label-standard-btn">Label standar (90 × 50 mm)</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => cetakLabel('sticker')}>Stiker kecil (50 × 25 mm)</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => cetakLabel('a4')}>Satu halaman A4</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          {bisaDiubah && (
            <Button size="sm" variant="outline" onClick={() => onTransferClick?.(asset)} data-testid="transfer-asset-btn">
              <ArrowRight />Pindahkan
            </Button>
          )}
          {/* Pelepasan: nilai buku > Rp 5 juta lewat persetujuan, selain itu langsung */}
          {bisaDiubah && (perluPersetujuan ? (
            <Button size="sm" variant="outline" onClick={() => onRequestDisposalClick?.(asset)} data-testid="request-disposal-btn">
              <Trash2 />Ajukan pelepasan
            </Button>
          ) : (
            <Button size="sm" variant="destructive" onClick={disposeAsset} disabled={loading} data-testid="dispose-asset-btn">
              <Trash2 />Lepas aset
            </Button>
          ))}
        </>}>
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="max-w-full justify-start overflow-x-auto">
            <TabsTrigger value="info">Info</TabsTrigger>
            <TabsTrigger value="depr">Penyusutan</TabsTrigger>
            <TabsTrigger value="assign">Penugasan</TabsTrigger>
            <TabsTrigger value="maint">Pemeliharaan</TabsTrigger>
          </TabsList>

          {/* Info */}
          <TabsContent value="info" className="mt-4 space-y-4">
            {asset.status === 'pending_disposal' && (
              <Notice tone="warning" title="Menunggu persetujuan pelepasan">
                Permintaan pelepasan aset ini sedang ditinjau Keuangan/Admin.
              </Notice>
            )}
            {!asset.fixed_asset_id && (
              <Notice tone="info" testId="asset-label-unlinked" title="Belum tertaut ke registri Aset Tetap (Keuangan)">
                Label belum bisa dicetak: kode label = kode registri. Tautkan dulu di Keuangan › Aset Tetap.
              </Notice>
            )}
            <div className="grid gap-4 sm:grid-cols-[14rem_1fr]">
              {/* Foto */}
              <div className="space-y-2">
                {asset.photo_url ? (
                  <img src={`${API}${asset.photo_url}`} alt={asset.name}
                    className="h-40 w-full rounded-lg border border-[var(--glass-border)] object-cover" />
                ) : (
                  <div className="grid h-40 place-items-center rounded-lg border-2 border-dashed border-[var(--glass-border)] text-center">
                    <div>
                      <Package className="mx-auto mb-1 h-8 w-8 text-muted-foreground" />
                      <p className="text-sm text-muted-foreground">Belum ada foto</p>
                    </div>
                  </div>
                )}
                <Button size="sm" variant="outline" className="w-full" onClick={() => photoInputRef.current?.click()}
                  disabled={uploadingPhoto} data-testid="asset-photo-btn">
                  <Camera />{uploadingPhoto ? 'Mengunggah…' : asset.photo_url ? 'Ganti foto' : 'Unggah foto'}
                </Button>
                <input type="file" ref={photoInputRef} onChange={handlePhotoUpload} accept="image/*" className="hidden" />
              </div>
              <dl className="divide-y divide-[var(--glass-border)]">
                <BarisDetail label="Kategori">{asset.category_name || '—'}</BarisDetail>
                <BarisDetail label="Lokasi">{asset.location || '—'}</BarisDetail>
                <BarisDetail label="Departemen">{asset.department || '—'}</BarisDetail>
                <BarisDetail label="No. seri">{asset.serial_number || '—'}</BarisDetail>
                <BarisDetail label="Merek / model">{[asset.brand, asset.model].filter(Boolean).join(' · ') || '—'}</BarisDetail>
                <BarisDetail label="Tanggal beli">{fmtDate(asset.purchase_date)}</BarisDetail>
                <BarisDetail label="Ditugaskan ke">{asset.assigned_to_name || '—'}</BarisDetail>
                <BarisDetail label="Harga beli"><span className="tabular-nums">{fmtCurrency(asset.purchase_cost)}</span></BarisDetail>
                <BarisDetail label="Akumulasi penyusutan"><span className="tabular-nums">{fmtCurrency(asset.accumulated_depreciation || 0)}</span></BarisDetail>
                <BarisDetail label="Nilai buku">
                  <span className="font-semibold tabular-nums">{fmtCurrency(nbv)}</span>
                  <span className="text-muted-foreground"> · {fmtPersen(deprPct, 0)} tersusutkan</span>
                </BarisDetail>
              </dl>
            </div>

            {adaGaransi && (
              <Bagian judul="Garansi">
                <dl className="divide-y divide-[var(--glass-border)]">
                  {asset.warranty_expiry_date && (
                    <BarisDetail label="Berakhir">
                      <span className="inline-flex flex-wrap items-center gap-2">{fmtDate(asset.warranty_expiry_date)}<MasaBerlaku tanggal={asset.warranty_expiry_date} /></span>
                    </BarisDetail>
                  )}
                  {asset.warranty_provider && <BarisDetail label="Penyedia">{asset.warranty_provider}</BarisDetail>}
                  {asset.warranty_terms && <BarisDetail label="Syarat">{asset.warranty_terms}</BarisDetail>}
                </dl>
              </Bagian>
            )}
            {adaAsuransi && (
              <Bagian judul="Asuransi">
                <dl className="divide-y divide-[var(--glass-border)]">
                  {asset.insurance_policy_number && <BarisDetail label="Nomor polis"><span className="tabular-nums">{asset.insurance_policy_number}</span></BarisDetail>}
                  {asset.insurance_provider && <BarisDetail label="Penyedia">{asset.insurance_provider}</BarisDetail>}
                  {asset.insurance_expiry_date && (
                    <BarisDetail label="Berakhir">
                      <span className="inline-flex flex-wrap items-center gap-2">{fmtDate(asset.insurance_expiry_date)}<MasaBerlaku tanggal={asset.insurance_expiry_date} /></span>
                    </BarisDetail>
                  )}
                  {asset.insurance_value > 0 && <BarisDetail label="Nilai pertanggungan"><span className="tabular-nums">{fmtCurrency(asset.insurance_value)}</span></BarisDetail>}
                </dl>
              </Bagian>
            )}
          </TabsContent>

          {/* Penyusutan */}
          <TabsContent value="depr" className="mt-4 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm">Penyusutan per bulan: <span className="font-semibold tabular-nums">{fmtCurrency(asset.monthly_depreciation)}</span></p>
              <Button size="sm" variant="outline" onClick={() => bukaPopup('susut')} data-testid="post-depr-open-btn">
                <TrendingDown />Posting penyusutan
              </Button>
            </div>
            <Bagian judul="Riwayat penyusutan"
              alat={<TombolUnduh namaBerkas={`penyusutan-${asset.asset_number}`} namaLembar="Penyusutan" baris={riwayatSusut}
                testId="asset-depr-unduh" kolom={[
                  { label: 'Periode', nilai: (d) => d.period },
                  { label: 'Penyusutan', nilai: (d) => angka(nilaiSusut(d)) },
                  { label: 'Akumulasi', nilai: (d) => angka(akumSusut(d)) },
                ]} />}>
              <TabelData baris={riwayatSusut} kunci={(d) => d.id || d.period} testId="asset-depr-table"
                kosong={<p className="py-4 text-center text-sm text-muted-foreground">Belum ada posting penyusutan.</p>}
                kolom={[
                  { kunci: 'periode', label: 'Periode', hp: 'judul', isi: (d) => <span className="tabular-nums">{d.period}</span> },
                  { kunci: 'jumlah', label: 'Penyusutan', rata: 'kanan', isi: (d) => <span className="tabular-nums">{fmtCurrency(nilaiSusut(d))}</span> },
                  { kunci: 'akum', label: 'Akumulasi', rata: 'kanan', isi: (d) => <span className="tabular-nums">{fmtCurrency(akumSusut(d))}</span> },
                ]} />
            </Bagian>
          </TabsContent>

          {/* Penugasan */}
          <TabsContent value="assign" className="mt-4 space-y-4">
            {asset.assigned_to_id ? (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm">Sedang ditugaskan ke <span className="font-semibold">{asset.assigned_to_name}</span></p>
                <Button size="sm" variant="outline" onClick={unassign} data-testid="unassign-asset-btn">
                  <Undo2 />Kembalikan aset
                </Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">Aset ini tidak sedang ditugaskan ke siapa pun.</p>
                <Button size="sm" variant="outline" onClick={() => bukaPopup('tugas')} data-testid="assign-open-btn">
                  <UserPlus />Tugaskan ke karyawan
                </Button>
              </div>
            )}
            <Bagian judul="Riwayat penugasan"
              alat={<TombolUnduh namaBerkas={`penugasan-${asset.asset_number}`} namaLembar="Penugasan" baris={assignments}
                testId="asset-assign-unduh" kolom={[
                  { label: 'Karyawan', nilai: (a) => a.assigned_to_name },
                  { label: 'Mulai', nilai: (a) => fmtDate(a.assigned_date) },
                  { label: 'Selesai', nilai: (a) => (a.returned_date ? fmtDate(a.returned_date) : 'Masih aktif') },
                ]} />}>
              <TabelData baris={assignments} testId="asset-assign-table"
                kosong={<p className="py-4 text-center text-sm text-muted-foreground">Belum pernah ditugaskan.</p>}
                kolom={[
                  { kunci: 'nama', label: 'Karyawan', hp: 'judul', isi: (a) => a.assigned_to_name },
                  { kunci: 'mulai', label: 'Mulai', isi: (a) => fmtDate(a.assigned_date) },
                  { kunci: 'selesai', label: 'Selesai', isi: (a) => (a.returned_date ? fmtDate(a.returned_date)
                    : <Lencana status="aktif" label="Masih aktif" tone="info" />) },
                ]} />
            </Bagian>
          </TabsContent>

          {/* Pemeliharaan */}
          <TabsContent value="maint" className="mt-4 space-y-4">
            <div className="flex justify-end">
              <Button size="sm" variant="outline" onClick={() => bukaPopup('rawat')} data-testid="maint-open-btn">
                <Wrench />Catat pemeliharaan
              </Button>
            </div>
            <Bagian judul="Riwayat pemeliharaan"
              alat={<TombolUnduh namaBerkas={`pemeliharaan-${asset.asset_number}`} namaLembar="Pemeliharaan" baris={maintenance}
                testId="asset-maint-unduh" kolom={[
                  { label: 'Tanggal', nilai: (m) => fmtDate(m.maintenance_date) },
                  { label: 'Uraian', nilai: (m) => m.description },
                  { label: 'Jenis', nilai: (m) => MAINT_TYPE_LABEL[m.type] || m.type || '' },
                  { label: 'Status', nilai: (m) => MAINT_STATUS_LABEL[m.status] || m.status || '' },
                  { label: 'Dilakukan oleh', nilai: (m) => m.performed_by || '' },
                  { label: 'Biaya', nilai: (m) => angka(m.cost || 0) },
                ]} />}>
              <TabelData baris={maintenance} testId="asset-maint-table"
                kosong={<p className="py-4 text-center text-sm text-muted-foreground">Belum ada riwayat pemeliharaan.</p>}
                kolom={[
                  { kunci: 'tgl', label: 'Tanggal', hp: 'keterangan', isi: (m) => fmtDate(m.maintenance_date) },
                  { kunci: 'uraian', label: 'Uraian', hp: 'judul', isi: (m) => <span className="font-medium">{m.description}</span> },
                  { kunci: 'jenis', label: 'Jenis', isi: (m) => MAINT_TYPE_LABEL[m.type] || m.type || '—' },
                  { kunci: 'biaya', label: 'Biaya', rata: 'kanan', isi: (m) => <span className="tabular-nums">{m.cost > 0 ? fmtCurrency(m.cost) : '—'}</span> },
                ]} />
            </Bagian>
          </TabsContent>
        </Tabs>
      </DetailPopup>

      {/* Posting penyusutan satu bulan */}
      <FormPopup open={popup === 'susut'} onClose={() => setPopup(null)} ukuran="pendek" testId="asset-depr-form"
        judul="Posting penyusutan bulanan" keterangan={`${asset.asset_number} — ${asset.name}`}
        labelSimpan="Posting" onSimpan={postDepr} menyimpan={loading} galat={galat}>
        <Isian label="Periode" wajib petunjuk={`Penyusutan per bulan: ${fmtCurrency(asset.monthly_depreciation)}.`}>
          <SmartNativeSelect value={deprPeriod} onChange={e => setDeprPeriod(e.target.value)} searchable={false}
            className="h-9 w-full" data-testid="post-depr-period">
            {monthOptions(24).map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </SmartNativeSelect>
        </Isian>
      </FormPopup>

      {/* Tugaskan ke karyawan */}
      <FormPopup open={popup === 'tugas'} onClose={() => setPopup(null)} ukuran="pendek" testId="asset-assign-form"
        judul="Tugaskan ke karyawan" keterangan={`${asset.asset_number} — ${asset.name}`}
        labelSimpan="Tugaskan" onSimpan={assignAsset} menyimpan={loading} galat={galat}>
        <Isian label="ID karyawan" wajib htmlFor="assign-user-id">
          <Input id="assign-user-id" placeholder="ID karyawan" data-testid="assign-user-id" value={assignForm.user_id}
            onChange={e => setAssignForm(p => ({ ...p, user_id: e.target.value }))} />
        </Isian>
        <Isian label="Nama karyawan" htmlFor="assign-user-name">
          <Input id="assign-user-name" placeholder="Nama karyawan" data-testid="assign-user-name" value={assignForm.user_name}
            onChange={e => setAssignForm(p => ({ ...p, user_name: e.target.value }))} />
        </Isian>
        <Isian label="Catatan" htmlFor="assign-notes">
          <Input id="assign-notes" placeholder="Opsional" value={assignForm.notes}
            onChange={e => setAssignForm(p => ({ ...p, notes: e.target.value }))} />
        </Isian>
      </FormPopup>

      {/* Catat pemeliharaan */}
      <FormPopup open={popup === 'rawat'} onClose={() => setPopup(null)} ukuran="pendek" testId="asset-maint-form"
        judul="Catat pemeliharaan" keterangan={`${asset.asset_number} — ${asset.name}`}
        labelSimpan="Simpan pemeliharaan" onSimpan={addMaintenance} menyimpan={loading} galat={galat}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Jenis">
            <SmartNativeSelect value={maintForm.type} onChange={e => setMaintForm(p => ({ ...p, type: e.target.value }))}
              searchable={false} className="h-9 w-full" data-testid="maint-type">
              <option value="scheduled">Terjadwal</option>
              <option value="corrective">Korektif</option>
              <option value="preventive">Preventif</option>
            </SmartNativeSelect>
          </Isian>
          <Isian label="Status">
            <SmartNativeSelect value={maintForm.status} onChange={e => setMaintForm(p => ({ ...p, status: e.target.value }))}
              searchable={false} className="h-9 w-full" data-testid="maint-status">
              <option value="completed">Selesai</option>
              <option value="in_progress">Sedang berjalan</option>
              <option value="scheduled">Terjadwal</option>
            </SmartNativeSelect>
          </Isian>
        </div>
        <Isian label="Uraian pemeliharaan" wajib htmlFor="maint-desc">
          <Input id="maint-desc" placeholder="Contoh: ganti sabuk motor" value={maintForm.description}
            onChange={e => setMaintForm(p => ({ ...p, description: e.target.value }))} data-testid="maint-desc" />
        </Isian>
        <div className="grid gap-4 sm:grid-cols-2">
          <Isian label="Biaya (Rp)" htmlFor="maint-cost">
            <MoneyInput id="maint-cost" placeholder="0" value={maintForm.cost}
              onChange={e => setMaintForm(p => ({ ...p, cost: e.target.value }))} />
          </Isian>
          <Isian label="Tanggal">
            <DatePicker value={maintForm.maintenance_date} onChange={v => setMaintForm(p => ({ ...p, maintenance_date: v }))}
              bolehKosong={false} testId="maint-date" />
          </Isian>
        </div>
        <Isian label="Dilakukan oleh" htmlFor="maint-by">
          <Input id="maint-by" placeholder="Teknisi / vendor" value={maintForm.performed_by}
            onChange={e => setMaintForm(p => ({ ...p, performed_by: e.target.value }))} />
        </Isian>
      </FormPopup>
    </>
  );
}

