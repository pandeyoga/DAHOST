/**
 * QuickCompleteModal.jsx
 *
 * One-click wizard that executes the FULL production flow for a PO:
 *   1. Vendor Shipment
 *   2. Terima Shipment
 *   3. Inspeksi Material
 *   4. Production Job
 *   5. Progress Produksi (100%)
 *   6. Buyer Shipment
 *   7. Status PO → Completed
 */
import { useState } from 'react';
import {
  Truck, ClipboardCheck, Factory, TrendingUp,
  Package, CheckCircle2, AlertTriangle, Loader2,
  Info, SkipForward, Check
} from 'lucide-react';
import { apiPost } from '../../../lib/api';
import { toast } from 'sonner';
import FormPopup from '@/components/ui/form-popup';
import { Checkbox } from '@/components/ui/checkbox';
import { Notice, StatusBadge } from '../moduleAtoms';
import { PO_STATUS_LABEL } from './PODetailPanel';

const STEP_META = [
  { step: 1, icon: Truck,         label: 'Kirim bahan ke CMT',       desc: 'Buat kiriman bahan ke penjahit' },
  { step: 2, icon: CheckCircle2,  label: 'Kiriman diterima CMT',     desc: 'Tandai kiriman sudah diterima' },
  { step: 3, icon: ClipboardCheck,label: 'Inspeksi bahan',           desc: 'Catat semua bahan diterima tanpa cacat' },
  { step: 4, icon: Factory,       label: 'Job produksi',             desc: 'Buat job produksi dari kiriman' },
  { step: 5, icon: TrendingUp,    label: 'Kemajuan produksi (100%)', desc: 'Catat kemajuan produksi 100% untuk semua baris' },
  { step: 6, icon: Package,       label: 'Kiriman ke buyer',         desc: 'Buat kiriman ke buyer untuk semua barang jadi' },
  { step: 7, icon: CheckCircle2,  label: 'PO selesai',               desc: 'Tandai PO sebagai selesai' },
];

const STATUS_TONE = {
  created: 'success', done: 'success', reused: 'primary', skipped: 'muted', pending: 'muted', running: 'warning', error: 'danger',
};

const STATUS_LABEL = {
  created: 'Dibuat',
  done:    'Selesai',
  reused:  'Sudah ada (digunakan)',
  skipped: 'Dilewati',
  pending: 'Menunggu',
  running: 'Memproses…',
  error:   'Gagal',
};

// ─── Main component ──────────────────────────────────────────────────────────
export default function QuickCompleteModal({ po, onClose, onSuccess }) {
  const [phase, setPhase] = useState('confirm'); // confirm | running | result
  const [skipBuyerShipment, setSkipBuyerShipment] = useState(false);
  const [result, setResult] = useState(null);
  const [stepStatuses, setStepStatuses] = useState({});
  const [currentStep, setCurrentStep] = useState(0);
  const [error, setError] = useState(null);

  const totalItems = (po.items || []).reduce((s, i) => s + (Number(i.qty) || 0), 0);
  const vendorOk   = !!po.vendor_id;
  const itemsOk    = (po.items || []).length > 0 && totalItems > 0;
  const canRun     = vendorOk && itemsOk && !['Completed', 'Closed'].includes(po.status);

  // Animate steps after receiving result
  const animateSteps = async (steps) => {
    for (const s of steps) {
      setCurrentStep(s.step);
      setStepStatuses(prev => ({ ...prev, [s.step]: 'running' }));
      await delay(320);
      setStepStatuses(prev => ({ ...prev, [s.step]: s.status }));
      await delay(180);
    }
    setCurrentStep(0);
  };

  const handleRun = async () => {
    setPhase('running');
    setStepStatuses({});
    setError(null);
    // Show all steps as pending first
    const init = {};
    STEP_META.forEach(m => { init[m.step] = 'pending'; });
    setStepStatuses(init);

    try {
      const data = await apiPost(`/production-pos/${po.id}/quick-complete`, {
        skip_buyer_shipment: skipBuyerShipment,
      });
      setResult(data);
      await animateSteps(data.steps);
      setPhase('result');
      onSuccess?.();
      toast.success(`PO ${po.po_number} selesai dijalankan cepat.`);
    } catch (e) {
      setError(e.message || 'Terjadi kesalahan');
      setPhase('error');
    }
  };

  // Standar UI/UX v2 (8 Nov 2026): popup standar (FormPopup) — kepala tipis, tombol Batal · aksi hijau di kaki,
  // layar penuh di HP. Dulu popup buatan sendiri dengan judul putih di atas latar ungu pudar (tidak terbaca).
  const kaki = {
    confirm: { label: 'Jalankan selesaikan cepat', onSimpan: handleRun, bisa: canRun },
    running: { label: 'Memproses…', onSimpan: () => {}, bisa: false },
    result: { label: 'Selesai', onSimpan: onClose, bisa: true },
    error: { label: 'Coba lagi', onSimpan: () => { setPhase('confirm'); setError(null); }, bisa: true },
  }[phase] || { label: 'Tutup', onSimpan: onClose, bisa: true };
  return (
    <FormPopup open onClose={phase === 'running' ? () => {} : onClose} ukuran="pendek" testId="quick-complete-dialog"
      judul="Selesaikan cepat" keterangan={`PO ${po.po_number} — semua alur produksi dijalankan sekaligus.`}
      onSimpan={kaki.onSimpan} labelSimpan={kaki.label} bisaSimpan={kaki.bisa} menyimpan={phase === 'running'}>

          {/* ── CONFIRM phase ── */}
          {phase === 'confirm' && (
            <>
              {/* Pre-flight checks */}
              <div className="space-y-2">
                <p className="text-sm font-medium text-foreground">Pemeriksaan PO</p>
                {[
                  { ok: itemsOk,  pass: `${(po.items||[]).length} baris, total ${totalItems} pcs`, fail: 'PO tidak punya baris / qty = 0' },
                  { ok: vendorOk, pass: `Penjahit: ${po.vendor_name || po.vendor_id}`, fail: 'Penjahit (CMT) belum dipilih' },
                  { ok: !['Completed','Closed'].includes(po.status), pass: `Status: ${PO_STATUS_LABEL[po.status] || po.status}`, fail: `PO sudah ${PO_STATUS_LABEL[po.status] || po.status}` },
                ].map((chk, i) => (
                  <div key={i} className={`flex items-center gap-2.5 text-sm ${chk.ok ? 'text-[hsl(var(--success-text))]' : 'text-[hsl(var(--danger-text))]'}`}>
                    {chk.ok
                      ? <Check className="w-4 h-4 flex-shrink-0" />
                      : <AlertTriangle className="w-4 h-4 flex-shrink-0" />}
                    {chk.ok ? chk.pass : chk.fail}
                  </div>
                ))}
              </div>

              {/* Flow preview */}
              <div>
                <p className="text-sm font-medium text-foreground mb-2">Langkah yang akan dijalankan</p>
                <ol className="rounded-lg border border-[var(--glass-border)] divide-y divide-[var(--glass-border)]">
                  {STEP_META.filter(m => !(skipBuyerShipment && m.step === 6)).map((m) => (
                    <li key={m.step} className="flex items-start gap-3 px-3 py-2">
                      <span className="flex items-center justify-center w-6 h-6 rounded-full bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] text-xs font-semibold flex-shrink-0">
                        {m.step}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground">{m.label}</p>
                        <p className="text-xs text-muted-foreground">{m.desc}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>

              {/* Options */}
              <label htmlFor="skip-buyer" className="flex items-start gap-3 cursor-pointer">
                <Checkbox id="skip-buyer" checked={skipBuyerShipment} onCheckedChange={(v) => setSkipBuyerShipment(!!v)}
                  className="mt-0.5" data-testid="skip-buyer-checkbox" />
                <span>
                  <span className="block text-sm font-medium text-foreground">Lewati kiriman ke buyer</span>
                  <span className="block text-xs text-muted-foreground">Centang bila tidak ingin langsung membuat kiriman ke buyer.</span>
                </span>
              </label>

              <Notice tone="warning" icon={Info}>
                Selesaikan cepat membuat semua data produksi otomatis dengan anggapan <strong>bahan 100% diterima, tanpa cacat</strong>. Langkah yang sudah ada dipakai ulang (tidak digandakan).
              </Notice>
            </>
          )}

          {/* ── RUNNING phase ── */}
          {(phase === 'running') && (
            <div className="space-y-3">
              <div className="flex items-center justify-center gap-3 py-2">
                <Loader2 className="w-5 h-5 text-[hsl(var(--primary))] animate-spin" />
                <p className="text-sm font-medium text-foreground">Memproses alur produksi…</p>
              </div>
              <StepList stepStatuses={stepStatuses} currentStep={currentStep} skipBuyerShipment={skipBuyerShipment} />
            </div>
          )}

          {/* ── RESULT phase ── */}
          {phase === 'result' && result && (
            <div className="space-y-4">
              <Notice tone="success" icon={CheckCircle2} title="Berhasil">{result.message}</Notice>
              <StepList stepStatuses={stepStatuses} skipBuyerShipment={skipBuyerShipment} />
              <dl className="grid grid-cols-2 gap-3 text-sm">
                {[
                  { label: 'Nomor job', value: result.job_number },
                  { label: 'Total barang', value: `${result.total_items} pcs` },
                ].map(kv => (
                  <div key={kv.label}>
                    <dt className="text-xs text-muted-foreground">{kv.label}</dt>
                    <dd className="font-semibold text-foreground">{kv.value || '—'}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {/* ── ERROR phase ── */}
          {phase === 'error' && (
            <Notice tone="danger" icon={AlertTriangle} title="Gagal">{error}</Notice>
          )}
    </FormPopup>
  );
}

// ── Step list sub-component ───────────────────────────────────────────────────
function StepList({ stepStatuses, currentStep, skipBuyerShipment }) {
  return (
    <div className="rounded-lg border border-[var(--glass-border)] divide-y divide-[var(--glass-border)]">
      {STEP_META.map(m => {
        const st = stepStatuses[m.step] || 'pending';
        const isSkipped = skipBuyerShipment && m.step === 6;
        const effectiveSt = isSkipped ? 'skipped' : st;
        const isCurrent = currentStep === m.step;
        const Icon = m.icon;
        return (
          <div key={m.step} className={`flex items-center gap-3 px-3 py-2 ${isCurrent ? 'bg-[hsl(var(--warning)/0.08)]' : ''}`}>
            <span className="flex items-center justify-center w-6 h-6 flex-shrink-0 text-muted-foreground">
              {isCurrent
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : effectiveSt === 'created' || effectiveSt === 'done'
                  ? <Check className="w-3.5 h-3.5 text-[hsl(var(--success-text))]" />
                  : effectiveSt === 'skipped'
                    ? <SkipForward className="w-3.5 h-3.5" />
                    : <Icon className="w-3.5 h-3.5" />
              }
            </span>
            <p className="flex-1 min-w-0 text-sm text-foreground truncate">{m.label}</p>
            <StatusBadge status={effectiveSt} label={isCurrent ? 'Memproses…' : STATUS_LABEL[effectiveSt]} tone={isCurrent ? 'warning' : STATUS_TONE[effectiveSt]} />
          </div>
        );
      })}
    </div>
  );
}

// ── Helper ────────────────────────────────────────────────────────────────────
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
