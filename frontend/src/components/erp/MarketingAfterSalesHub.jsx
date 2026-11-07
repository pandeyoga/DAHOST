/**
 * MarketingAfterSalesHub.jsx — Komplain & Retur (Portal Toko).
 * Consolidation #9: Komplain + Refund & nota kredit + Log penyelesaian.
 * Replaces: marketing-complaints + marketing-returns (2 sidebar entries → 1)
 *
 * Standar UI/UX v2 (8 Nov 2026): hub memakai HubTabs (dulu kepala & tab buatan sendiri → kepala ganda dengan modul
 * di dalamnya). Log penyelesaian = tabel + unduh + detail popup (dulu kartu per baris).
 * Deep-link tab `hub_tab_marketing-after-sales` (makeRedirect) dibaca HubTabs.
 */
import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import TabelData from '@/components/ui/tabel-data';
import TombolUnduh from '@/components/ui/tombol-unduh';
import DetailPopup, { BarisDetail } from '@/components/ui/detail-popup';
import { formatDateID } from '@/lib/format';
import HubTabs from './hubs/HubTabs';
import PageLayout from './layout/PageLayout';
import { EmptyState, StatusBadge } from './moduleAtoms';
import ComplaintsManagementModule from './marketing/ComplaintsManagementModule';
import ReturnsRefundsModule from './marketing/ReturnsRefundsModule';

const API = process.env.REACT_APP_BACKEND_URL;

// ── Log penyelesaian ────────────────────────────────────────────────────────
const STATUS_LABEL = {
  resolved: { label: 'Diselesaikan', tone: 'success' },
  closed: { label: 'Ditutup', tone: 'muted' },
  completed: { label: 'Selesai', tone: 'success' },
  rejected: { label: 'Ditolak', tone: 'danger' },
};
const JENIS = {
  complaint: { label: 'Komplain', tone: 'warning' },
  return: { label: 'Refund', tone: 'primary' },
  wh_return: { label: 'Retur fisik', tone: 'info' },
};
const tgl = (v) => (v ? formatDateID(v) : '—');
const labelPlatform = (p) => (p ? String(p).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '—');

function ResolutionLogTab({ token }) {
  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);

  const fetchLog = useCallback(async () => {
    setLoading(true);
    try {
      const [cRes, rRes, whRes] = await Promise.all([
        axios.get(`${API}/api/marketing/complaints`, {
          params: { status: 'resolved', page_size: 15 }, headers: authH
        }).catch(() => ({ data: { complaints: [] } })),
        axios.get(`${API}/api/marketing/returns`, {
          params: { status: 'completed', page_size: 15 }, headers: authH
        }).catch(() => ({ data: { data: [] } })),
        // RC-FLOW-UX-11f: merge retur fisik Gudang yang sudah Resolved
        axios.get(`${API}/api/wh/returns`, {
          params: { status: 'Resolved' }, headers: authH
        }).catch(() => ({ data: [] })),
      ]);

      const complaints = (cRes.data?.complaints || []).map(c => ({
        id: c.id,
        type: 'complaint',
        title: c.complaint_number || 'Komplain',
        summary: `${c.customer_name || '-'} • ${c.product_name || '-'}`,
        status: c.status,
        date: c.updated_at || c.complaint_date,
        platform: c.platform,
      }));

      const returns = (rRes.data?.data || []).map(r => ({
        id: r.id,
        type: 'return',
        title: `Refund #${r.order_id || '?'}`,
        summary: `${r.product || '-'} • Rp ${(r.refund_amount || 0).toLocaleString('id-ID')}${r.wh_return_code ? ` • fisik: ${r.wh_return_code}` : ''}`,
        status: r.status,
        date: r.updated_at || r.date,
        platform: r.platform,
      }));

      // Wh returns yang sudah Resolved — abaikan jika sudah punya kembar
      // marketing_return (di-list `returns` di atas) untuk mencegah duplikat visual.
      const marketingSourceIds = new Set(
        (rRes.data?.data || []).map(r => r.wh_return_id).filter(Boolean)
      );
      const whReturnsList = Array.isArray(whRes.data) ? whRes.data : (whRes.data?.data || []);
      const whReturns = whReturnsList
        .filter(w => !marketingSourceIds.has(w.id)) // hindari duplikat
        .map(w => ({
          id: w.id,
          type: 'wh_return',
          title: `${w.return_code || 'Retur fisik'}`,
          summary: `${w.product_name || '-'} • ${w.action_taken || 'Diselesaikan'}${w.restock_qty ? ` • ${w.restock_qty} pcs masuk stok lagi` : ''}`,
          status: 'resolved',
          date: w.resolved_at || w.updated_at || w.created_at,
          platform: w.channel || w.return_type,
        }));

      const merged = [...complaints, ...returns, ...whReturns]
        .sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0))
        .slice(0, 30);

      setItems(merged);
    } finally {
      setLoading(false);
    }
  }, [token]); // eslint-disable-line

  useEffect(() => { fetchLog(); }, [fetchLog]);

  const st = (s) => STATUS_LABEL[s] || { label: s || '—', tone: 'muted' };
  const kolom = [
    { kunci: 'judul', label: 'Nomor', hp: 'judul', isi: (i) => <span className="font-medium text-foreground">{i.title}</span> },
    { kunci: 'jenis', label: 'Jenis', isi: (i) => <StatusBadge status={i.type} label={JENIS[i.type]?.label} tone={JENIS[i.type]?.tone} /> },
    { kunci: 'ringkas', label: 'Ringkasan', hp: 'keterangan', isi: (i) => <p className="truncate text-sm md:max-w-[26rem]" title={i.summary}>{i.summary}</p> },
    { kunci: 'platform', label: 'Platform', isi: (i) => labelPlatform(i.platform) },
    { kunci: 'status', label: 'Status', isi: (i) => <StatusBadge status={i.status} label={st(i.status).label} tone={st(i.status).tone} /> },
    { kunci: 'tanggal', label: 'Tanggal', isi: (i) => <span className="tabular-nums md:whitespace-nowrap">{tgl(i.date)}</span> },
  ];

  return (
    <PageLayout testId="resolution-log" title="Log penyelesaian"
      subtitle="Komplain, refund, dan retur fisik yang sudah ditangani — 30 terbaru."
      tools={<>
        <TombolUnduh namaBerkas="log-penyelesaian" namaLembar="Penyelesaian" baris={items} testId="resolution-log-unduh"
          kolom={[
            { label: 'Nomor', nilai: (i) => i.title },
            { label: 'Jenis', nilai: (i) => JENIS[i.type]?.label || '' },
            { label: 'Ringkasan', nilai: (i) => i.summary },
            { label: 'Platform', nilai: (i) => labelPlatform(i.platform) },
            { label: 'Status', nilai: (i) => st(i.status).label },
            { label: 'Tanggal', nilai: (i) => tgl(i.date) },
          ]} />
        <Button variant="outline" size="icon" onClick={fetchLog} disabled={loading} title="Muat ulang" aria-label="Muat ulang">
          <RefreshCw className={loading ? 'animate-spin' : ''} />
        </Button>
      </>}>
      {loading && items.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Memuat log penyelesaian…</p>
      ) : (
        <TabelData kolom={kolom} baris={items} kunci={(i) => `${i.type}-${i.id}`} onKlikBaris={setDetail} testId="resolution-log-table"
          kosong={<EmptyState title="Belum ada riwayat penyelesaian" description="Komplain dan retur yang selesai ditangani muncul di sini." />} />
      )}
      {detail && (
        <DetailPopup open onClose={() => setDetail(null)} judul={detail.title} testId="resolution-log-detail"
          status={<><StatusBadge status={detail.type} label={JENIS[detail.type]?.label} tone={JENIS[detail.type]?.tone} />
            <StatusBadge status={detail.status} label={st(detail.status).label} tone={st(detail.status).tone} /></>}>
          <dl className="divide-y divide-[var(--glass-border)]">
            <BarisDetail label="Ringkasan">{detail.summary}</BarisDetail>
            <BarisDetail label="Platform">{labelPlatform(detail.platform)}</BarisDetail>
            <BarisDetail label="Tanggal">{tgl(detail.date)}</BarisDetail>
          </dl>
          <p className="text-sm text-muted-foreground">Rincian lengkap ada di tab {detail.type === 'complaint' ? 'Komplain' : 'Refund & nota kredit'}.</p>
        </DetailPopup>
      )}
    </PageLayout>
  );
}

// ── Hub ─────────────────────────────────────────────────────────────────────
export default function MarketingAfterSalesHub({ token, onNavigate }) {
  const authH = { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` };
  const [openComplaints, setOpenComplaints] = useState(0);
  const [pendingReturns, setPendingReturns] = useState(0);

  useEffect(() => {
    // Hitungan untuk label tab (dari ringkasan server, bukan halaman yang dimuat)
    axios.get(`${API}/api/marketing/complaints/summary`, { headers: authH })
      .then(r => setOpenComplaints((r.data?.by_status?.open || 0) + (r.data?.by_status?.in_progress || 0)))
      .catch(() => {});
    axios.get(`${API}/api/marketing/returns/summary`, { headers: authH })
      .then(r => setPendingReturns(r.data?.data?.pending || 0))
      .catch(() => {});
  }, [token]); // eslint-disable-line

  return (
    <div data-testid="after-sales-hub">
      <HubTabs hubId="marketing-after-sales" title="Komplain & retur"
        subtitle="Komplain pelanggan, refund & nota kredit, dan riwayat penyelesaian."
        tabs={[
          { key: 'complaints', label: openComplaints > 0 ? `Komplain (${openComplaints})` : 'Komplain',
            Component: ComplaintsManagementModule, props: { token, onNavigate } },
          { key: 'returns', label: pendingReturns > 0 ? `Refund & nota kredit (${pendingReturns})` : 'Refund & nota kredit',
            Component: ReturnsRefundsModule, props: { token, onNavigate } },
          { key: 'log', label: 'Log penyelesaian', Component: ResolutionLogTab, props: { token } },
        ]} />
    </div>
  );
}
