import { useState, useEffect } from 'react';
import { Clock, AlertTriangle, Package, Send, TrendingUp, Briefcase } from 'lucide-react';
import { StatCard } from './VendorShared';
import { apiGet } from '../../../lib/api';

export default function VendorDashboard({ token, user, onNavigate }) {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    apiGet('/vendor/dashboard').then(setMetrics).catch(console.error);
  }, []);

  const fmtDate = d => d ? new Date(d).toLocaleDateString('id-ID') : '-';

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Dashboard Vendor</h1>
        <p className="text-muted-foreground text-sm mt-1">Ikhtisar produksi — {user?.name}</p>
      </div>

      {/* Row 1: Job & Progress */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Job Produksi Aktif" value={metrics?.activeJobs || 0} icon={Briefcase} color="bg-[hsl(var(--primary))]" sub="job parent berjalan" />
        <StatCard title="Job Selesai" value={metrics?.completedJobs || 0} icon={TrendingUp} color="bg-[hsl(var(--success))]" sub="selesai diproduksi" />
        <StatCard title="Total Diproduksi" value={`${(metrics?.totalProduced || 0).toLocaleString('id-ID')} pcs`} icon={TrendingUp} color="bg-[hsl(var(--success))]" sub={`${metrics?.progressPct || 0}% dari material tersedia`} />
        <StatCard title="Job Overdue" value={metrics?.overdueJobs || 0} icon={AlertTriangle} color={metrics?.overdueJobs > 0 ? "bg-[hsl(var(--destructive))]" : "bg-muted-foreground/50"} sub="melewati deadline" alert={metrics?.overdueJobs > 0} />
      </div>

      {/* Row 2: Material Status */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Material Diterima" value={`${(metrics?.totalReceived || 0).toLocaleString('id-ID')} pcs`} icon={Package} color="bg-[hsl(var(--success))]" sub="dari semua shipment" />
        <StatCard title="Material Kurang" value={`${(metrics?.totalMissing || 0).toLocaleString('id-ID')} pcs`} icon={AlertTriangle} color={metrics?.totalMissing > 0 ? "bg-[hsl(var(--warning))]" : "bg-muted-foreground/50"} sub="belum dikirim" alert={metrics?.totalMissing > 0} />
        <StatCard title="Material Cacat" value={`${(metrics?.totalDefect || 0).toLocaleString('id-ID')} pcs`} icon={AlertTriangle} color={metrics?.totalDefect > 0 ? "bg-[hsl(var(--destructive))]" : "bg-muted-foreground/50"} sub="dari laporan defect" alert={metrics?.totalDefect > 0} />
        <StatCard title="Shipment Masuk" value={metrics?.incomingShipments || 0} icon={Package} color="bg-[hsl(var(--warning))]" sub="menunggu konfirmasi" alert={metrics?.incomingShipments > 0} />
      </div>

      {/* Row 3: Requests & Shipments */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Permintaan Tambahan" value={metrics?.pendingAdditional || 0} icon={AlertTriangle} color={metrics?.pendingAdditional > 0 ? "bg-[hsl(var(--warning))]" : "bg-muted-foreground/50"} sub="pending persetujuan" alert={metrics?.pendingAdditional > 0} />
        <StatCard title="Permintaan Pengganti" value={metrics?.pendingReplacement || 0} icon={AlertTriangle} color={metrics?.pendingReplacement > 0 ? "bg-[hsl(var(--destructive))]" : "bg-muted-foreground/50"} sub="pending persetujuan" alert={metrics?.pendingReplacement > 0} />
        <StatCard title="Buyer Shipments" value={metrics?.pendingBuyerShipments || 0} icon={Send} color="bg-[hsl(var(--primary))]" sub="total pengiriman ke buyer" />
        <StatCard title="Inspeksi Pending" value={metrics?.pendingInspections || 0} icon={Package} color={metrics?.pendingInspections > 0 ? "bg-[hsl(var(--warning))]" : "bg-muted-foreground/50"} sub="shipment belum diinspeksi" alert={metrics?.pendingInspections > 0} />
      </div>

      {/* Overall progress */}
      {metrics && (
        <div className="bg-card rounded-xl border border-border p-5 shadow-sm">
          <div className="flex justify-between items-center mb-2">
            <span className="font-semibold text-foreground/90 text-sm">Progress Produksi Keseluruhan (Parent + Child Jobs)</span>
            <span className="text-sm font-bold text-[hsl(var(--primary))]">
              {(metrics.totalProduced || 0).toLocaleString('id-ID')} / {(metrics.totalAvailable || 0).toLocaleString('id-ID')} pcs ({metrics.progressPct || 0}%)
            </span>
          </div>
          <div className="w-full bg-muted rounded-full h-3">
            <div className="h-3 rounded-full transition-all bg-gradient-to-r from-[hsl(var(--success)/0.1)] to-[hsl(var(--success)/0.1)]" style={{ width: `${Math.min(100, metrics.progressPct || 0)}%` }} />
          </div>
          {(metrics.totalMissing > 0 || metrics.totalDefect > 0) && (
            <div className="flex gap-4 mt-3 text-xs">
              {metrics.totalMissing > 0 && (
                <span className="px-2 py-1 bg-[hsl(var(--warning)/0.1)] border border-[hsl(var(--warning)/0.35)] rounded text-[hsl(var(--warning))]">
                  ⚠️ {metrics.totalMissing.toLocaleString('id-ID')} pcs material kurang
                </span>
              )}
              {metrics.totalDefect > 0 && (
                <span className="px-2 py-1 bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.35)] rounded text-[hsl(var(--destructive))]">
                  🚫 {metrics.totalDefect.toLocaleString('id-ID')} pcs material cacat
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Alerts */}
      {metrics?.alerts?.overdueJobs?.length > 0 && (
        <div className="bg-[hsl(var(--destructive)/0.1)] border border-[hsl(var(--destructive)/0.35)] rounded-xl p-4">
          <h3 className="font-semibold text-[hsl(var(--destructive))] flex items-center gap-2 mb-3"><AlertTriangle className="w-4 h-4" /> Job Melewati Deadline ({metrics.alerts.overdueJobs.length})</h3>
          <div className="space-y-2">
            {metrics.alerts.overdueJobs.map(j => (
              <div key={j.id} className="flex items-center justify-between p-2 bg-card rounded-lg border border-[hsl(var(--destructive)/0.35)]">
                <div>
                  <span className="font-bold text-[hsl(var(--destructive))] text-sm">{j.job_number}</span>
                  <span className="text-xs text-muted-foreground ml-2">PO: {j.po_number}</span>
                </div>
                <span className="text-xs text-[hsl(var(--destructive))] font-medium">Deadline: {fmtDate(j.deadline)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {metrics?.alerts?.nearDeadlineJobs?.length > 0 && (
        <div className="bg-[hsl(var(--warning)/0.1)] border border-[hsl(var(--warning)/0.35)] rounded-xl p-4">
          <h3 className="font-semibold text-[hsl(var(--warning))] flex items-center gap-2 mb-3"><Clock className="w-4 h-4" /> Mendekati Deadline ({metrics.alerts.nearDeadlineJobs.length})</h3>
          <div className="space-y-2">
            {metrics.alerts.nearDeadlineJobs.map(j => (
              <div key={j.id} className="flex items-center justify-between p-2 bg-card rounded-lg border border-[hsl(var(--warning)/0.35)]">
                <div>
                  <span className="font-bold text-[hsl(var(--warning))] text-sm">{j.job_number}</span>
                  <span className="text-xs text-muted-foreground ml-2">PO: {j.po_number}</span>
                </div>
                <span className="text-xs text-[hsl(var(--warning))] font-medium">Deadline: {fmtDate(j.deadline)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <button onClick={() => onNavigate('receiving')} className="py-3 bg-[hsl(var(--warning)/0.1)] border border-[hsl(var(--warning)/0.35)] text-[hsl(var(--warning))] rounded-xl text-sm font-medium hover:bg-[hsl(var(--warning)/0.15)] transition-colors">
          📦 Penerimaan Material
        </button>
        <button onClick={() => onNavigate('production-jobs')} className="py-3 bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)] text-[hsl(var(--primary))] rounded-xl text-sm font-medium hover:bg-[hsl(var(--primary)/0.15)] transition-colors">
          💼 Kelola Job Produksi
        </button>
        <button onClick={() => onNavigate('progress')} className="py-3 bg-[hsl(var(--success)/0.1)] border border-[hsl(var(--success)/0.35)] text-[hsl(var(--success))] rounded-xl text-sm font-medium hover:bg-[hsl(var(--success)/0.15)] transition-colors">
          📈 Input Progress Produksi
        </button>
        <button onClick={() => onNavigate('buyer-shipments')} className="py-3 bg-[hsl(var(--primary)/0.1)] border border-[hsl(var(--primary)/0.35)] text-[hsl(var(--primary))] rounded-xl text-sm font-medium hover:bg-[hsl(var(--primary)/0.15)] transition-colors">
          🚚 Pengiriman ke Buyer
        </button>
      </div>
    </div>
  );
}

// ─── VENDOR ACCESSORIES PANEL (lazy-loaded per shipment) ──────────────────────


