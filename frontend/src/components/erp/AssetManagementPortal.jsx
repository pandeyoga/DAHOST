/**
 * Manajemen Aset — CV. Dewi Aditya ERP
 * Aset perusahaan, pemakaian, pemeliharaan, pengadaan, pelepasan, dan peminjaman (satu pintu, 8 tab).
 *
 * Standar UI/UX v2 (8 Nov 2026): cetakan PageLayout + tab hub bersama (HubTabs). Kepala halaman tipis;
 * tombol tiap tab pindah ke baris tab (dulu 6 tombol menumpuk di kepala, di HP memakan 200 px);
 * nama tab berbahasa Indonesia tanpa emoji; detail = popup, form = popup standar.
 * Fitur, panggilan API, dan aturan tidak berubah — hanya tampilan.
 * 2026-11-08 (keputusan owner): "Posting penyusutan" (satu aset / massal) selalu ditolak server sejak K18 →
 * diganti tautan ke Keuangan › Aset Tetap, tab Penyusutan (hanya bila pengguna boleh membuka Portal Keuangan).
 *
 * File ini = pengatur (state + pemuat data + susunan). Isi tiap tab di ./asset/tabs/*.
 */
import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import PageLayout from './layout/PageLayout';
import HubTabs from './hubs/HubTabs';
import AssetScannerModal from './AssetScannerModal';

import { apicall } from './asset/utils';
import { MENU_PENYUSUTAN } from './asset/constants';
import { canAccessPortal } from './portalAccess';
import { EditCategoryDialog } from './asset/dialogs/EditCategoryDialog';
import { TransferAssetDialog } from './asset/dialogs/TransferAssetDialog';
import { DisposalRequestDialog } from './asset/dialogs/DisposalRequestDialog';
import { BulkImportDialog } from './asset/dialogs/BulkImportDialog';
import { CreateAssetDialog } from './asset/dialogs/CreateAssetDialog';
import { CreatePRDialog } from './asset/dialogs/CreatePRDialog';
import { DisposalApprovalInbox } from './asset/sections/DisposalApprovalInbox';
import { AssetDetailDrawer } from './asset/drawers/AssetDetailDrawer';
import { PRDetailDrawer } from './asset/drawers/PRDetailDrawer';

import { DashboardTab } from './asset/tabs/DashboardTab';
import { AssetsTab } from './asset/tabs/AssetsTab';
import { CategoriesTab } from './asset/tabs/CategoriesTab';
import { ProcurementTab } from './asset/tabs/ProcurementTab';
import { UtilizationReportTab } from './asset/tabs/UtilizationReportTab';
import { PredictiveMaintenanceTab } from './asset/tabs/PredictiveMaintenanceTab';
// ACC-3 — Peminjaman Alat & Aset (relokasi dari Portal Aksesoris)
import { LoansTab } from './asset/tabs/LoansTab';

const PR_PER_HALAMAN = 50;

export default function AssetManagementPortal({ token, user, defaultTab, onNavigate }) {
  // Fix menu-duplikat: menu lama (dashboard/daftar/pengadaan/peminjaman) membuka tab berbeda
  const [mainTab, setMainTab] = useState(defaultTab || 'dashboard');
  const [dashData, setDashData] = useState(null);
  const [expiringAlerts, setExpiringAlerts] = useState(null);
  const [assets, setAssets] = useState([]);
  const [assetPagination, setAssetPagination] = useState({ total: 0, page: 1, total_pages: 1, page_size: 20 });
  const [categories, setCategories] = useState([]);
  const [prData, setPrData] = useState([]);
  const [prPagination, setPrPagination] = useState({ total: 0, page: 1, total_pages: 1, page_size: PR_PER_HALAMAN });
  const [prInbox, setPrInbox] = useState([]);
  const [prTab, setPrTab] = useState('all');
  const [inboxScope, setInboxScope] = useState('relevant'); // relevant | all | mine
  const [inboxDept, setInboxDept] = useState(''); // optional dept filter (admin only)
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [selectedPR, setSelectedPR] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState(null);
  const [showCreateAsset, setShowCreateAsset] = useState(false);
  const [showCreatePR, setShowCreatePR] = useState(false);
  const [showEditCategory, setShowEditCategory] = useState(false);
  const [showAssetScanner, setShowAssetScanner] = useState(false);
  const [showTransferAsset, setShowTransferAsset] = useState(false);
  const [assetToTransfer, setAssetToTransfer] = useState(null);
  const [showBulkImport, setShowBulkImport] = useState(false);
  const [showDisposalRequest, setShowDisposalRequest] = useState(false);
  const [assetForDisposal, setAssetForDisposal] = useState(null);
  const [assetSearch, setAssetSearch] = useState('');
  const [assetStatus, setAssetStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [dashLoading, setDashLoading] = useState(false);
  const [catLoading, setCatLoading] = useState(false);
  const [prLoading, setPrLoading] = useState(false);
  const [prSearch, setPrSearch] = useState('');

  // Load dashboard
  const loadDashboard = useCallback(async () => {
    setDashLoading(true);
    try {
      const d = await apicall('GET', '/api/assets/dashboard', token);
      setDashData(d);
    } catch {
      setDashData((p) => p || { gagal: true });
    } finally { setDashLoading(false); }
  }, [token]);

  // Load expiring alerts (warranty + insurance)
  const loadExpiringAlerts = useCallback(async () => {
    try {
      const d = await apicall('GET', '/api/assets/expiring-alerts?days=30', token);
      setExpiringAlerts(d);
    } catch {}
  }, [token]);

  // Load assets
  const loadAssets = useCallback(async (page = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page, limit: 20 });
      if (assetSearch) params.set('search', assetSearch);
      if (assetStatus) params.set('status', assetStatus);
      const d = await apicall('GET', `/api/assets?${params}`, token);
      if (d.items) {
        setAssets(d.items);
        setAssetPagination(d.pagination);
      }
    } catch {}
    finally { setLoading(false); }
  }, [token, assetSearch, assetStatus]);

  /** Semua aset hasil saringan (untuk unduhan) — halaman demi halaman, 100 per halaman (batas API). */
  const fetchAssetPage = useCallback((page) => {
    const params = new URLSearchParams({ page, limit: 100 });
    if (assetSearch) params.set('search', assetSearch);
    if (assetStatus) params.set('status', assetStatus);
    return apicall('GET', `/api/assets?${params}`, token);
  }, [token, assetSearch, assetStatus]);

  // Load categories
  const loadCategories = useCallback(async () => {
    setCatLoading(true);
    try {
      const d = await apicall('GET', '/api/assets/categories', token);
      if (Array.isArray(d)) setCategories(d);
    } catch (e) {
      console.warn('loadCategories error:', e.message);
    } finally { setCatLoading(false); }
  }, [token]);

  // Load PRs
  const loadPRs = useCallback(async (page = 1) => {
    setPrLoading(true);
    try {
      const params = new URLSearchParams({ limit: PR_PER_HALAMAN, page });
      if (prSearch) params.set('search', prSearch);
      const inboxParams = new URLSearchParams({ scope: inboxScope });
      if (inboxDept) inboxParams.set('department', inboxDept);
      const [all, inbox] = await Promise.all([
        apicall('GET', `/api/procurement/requests?${params}`, token),
        apicall('GET', `/api/procurement/inbox?${inboxParams}`, token),
      ]);
      if (all.items) setPrData(all.items);
      if (all.pagination) setPrPagination(all.pagination);
      if (Array.isArray(inbox)) setPrInbox(inbox);
    } catch (e) {
      console.warn('loadPRs error:', e.message);
    } finally { setPrLoading(false); }
  }, [token, prSearch, inboxScope, inboxDept]);

  const fetchPRPage = useCallback((page) => {
    const params = new URLSearchParams({ limit: 100, page });
    if (prSearch) params.set('search', prSearch);
    return apicall('GET', `/api/procurement/requests?${params}`, token);
  }, [token, prSearch]);

  useEffect(() => { loadDashboard(); loadCategories(); loadExpiringAlerts(); }, [loadDashboard, loadCategories, loadExpiringAlerts]);
  useEffect(() => { if (mainTab === 'assets') loadAssets(); }, [mainTab, loadAssets]);
  useEffect(() => { if (mainTab === 'procurement') loadPRs(); }, [mainTab, loadPRs]);

  const userRole = (user?.role || '').toLowerCase();
  const isAdminLike = userRole === 'admin' || userRole === 'superadmin';
  // Daftar departemen unik (untuk filter admin) — dari prInbox + prData
  const uniqueDepartments = Array.from(new Set(
    [...(prData || []), ...(prInbox || [])]
      .map(p => (p.department || '').trim())
      .filter(Boolean)
  )).sort();

  // K18: penyusutan hanya dari registri Keuangan. Tanpa akses Portal Keuangan → null (layar hanya memberi keterangan).
  const bukaPenyusutan = onNavigate && canAccessPortal(user?.role, 'finance')
    ? () => onNavigate(MENU_PENYUSUTAN.modul, { tab: MENU_PENYUSUTAN.tab })
    : null;

  const aksiAset = {
    onTambahAset: () => setShowCreateAsset(true),
    onScan: () => setShowAssetScanner(true),
    onImpor: () => setShowBulkImport(true),
    onBukaPenyusutan: bukaPenyusutan,
  };
  const bukaAset = (a) => setSelectedAsset(a);

  const tabs = [
    {
      key: 'dashboard', label: 'Dashboard', Component: DashboardTab,
      props: {
        dashData, expiringAlerts, memuat: dashLoading, onAssetClick: bukaAset,
        onMuatUlang: () => { loadDashboard(); loadExpiringAlerts(); },
        ...aksiAset, onBuatPR: () => setShowCreatePR(true),
      },
    },
    {
      key: 'assets', label: 'Aset', Component: AssetsTab,
      props: {
        assetSearch, setAssetSearch, assetStatus, setAssetStatus,
        assets, loading, assetPagination, loadAssets, fetchAssetPage,
        onAssetClick: bukaAset, ...aksiAset,
      },
    },
    {
      key: 'categories', label: 'Kategori', Component: CategoriesTab,
      props: {
        categories, loading: catLoading, onMuatUlang: loadCategories,
        onEditCategory: (c) => { setSelectedCategory(c); setShowEditCategory(true); },
      },
    },
    {
      key: 'procurement', label: prInbox.length > 0 ? `Pengadaan (${prInbox.length})` : 'Pengadaan',
      Component: ProcurementTab,
      props: {
        prTab, setPrTab, prData, prInbox, prPagination, loading: prLoading,
        prSearch, setPrSearch, loadPRs, fetchPRPage,
        onSelectPR: (pr) => setSelectedPR(pr), onBuatPR: () => setShowCreatePR(true),
        isAdminLike, inboxScope, setInboxScope, inboxDept, setInboxDept, uniqueDepartments,
      },
    },
    {
      key: 'disposal-requests', label: 'Pelepasan', Component: DisposalApprovalInbox,
      props: { token, userRole: user?.role, onRefresh: () => { loadAssets(); loadDashboard(); } },
    },
    { key: 'utilization', label: 'Pemakaian', Component: UtilizationReportTab, props: { token, categories } },
    { key: 'pm-alerts', label: 'Peringatan pemeliharaan', Component: PredictiveMaintenanceTab, props: { token, categories } },
    { key: 'loans', label: 'Peminjaman', Component: LoansTab, props: { token } },
  ];

  return (
    <PageLayout testId="asset-mgmt-portal" title="Manajemen aset"
      subtitle="Aset perusahaan, pemakaian, pemeliharaan, pengadaan, pelepasan, dan peminjaman.">
      <HubTabs hubId="asset-mgmt" tabs={tabs} value={mainTab} onValueChange={setMainTab} />

      {/* Popup form & detail */}
      <CreateAssetDialog
        open={showCreateAsset}
        onClose={() => setShowCreateAsset(false)}
        token={token}
        categories={categories}
        onCreated={() => { loadAssets(); loadDashboard(); }}
      />
      <BulkImportDialog
        open={showBulkImport}
        onClose={() => setShowBulkImport(false)}
        token={token}
        categories={categories}
        onImported={() => { loadAssets(); loadDashboard(); loadExpiringAlerts(); }}
      />
      <DisposalRequestDialog
        open={showDisposalRequest}
        onClose={() => { setShowDisposalRequest(false); setAssetForDisposal(null); }}
        token={token}
        asset={assetForDisposal}
        onRequested={() => { loadAssets(); loadDashboard(); setSelectedAsset(null); }}
      />
      <AssetDetailDrawer
        asset={selectedAsset}
        token={token}
        open={!!selectedAsset}
        onClose={() => setSelectedAsset(null)}
        onRefresh={() => { loadAssets(); loadDashboard(); }}
        onTransferClick={(asset) => { setAssetToTransfer(asset); setShowTransferAsset(true); }}
        onRequestDisposalClick={(asset) => { setAssetForDisposal(asset); setShowDisposalRequest(true); }}
        onBukaPenyusutan={bukaPenyusutan}
      />
      <CreatePRDialog
        open={showCreatePR}
        onClose={() => setShowCreatePR(false)}
        token={token}
        onCreated={() => loadPRs()}
      />
      <PRDetailDrawer
        pr={selectedPR}
        token={token}
        open={!!selectedPR}
        onClose={() => setSelectedPR(null)}
        onRefresh={() => loadPRs(prPagination.page || 1)}
        currentUser={user}
      />
      <EditCategoryDialog
        open={showEditCategory}
        onClose={() => { setShowEditCategory(false); setSelectedCategory(null); }}
        token={token}
        category={selectedCategory}
        onUpdated={() => { loadCategories(); }}
      />
      {showAssetScanner && (
        <AssetScannerModal
          token={token}
          onScanned={(asset, details) => {
            setShowAssetScanner(false);
            toast.success(`Aset ${asset.asset_number} berhasil dipindai`, {
              description: `Lokasi: ${details.location || asset.location || '—'}`,
            });
            loadAssets();
            loadDashboard();
          }}
          onClose={() => setShowAssetScanner(false)}
        />
      )}
      <TransferAssetDialog
        open={showTransferAsset}
        onClose={() => { setShowTransferAsset(false); setAssetToTransfer(null); }}
        token={token}
        asset={assetToTransfer}
        onTransferred={() => { loadAssets(); loadDashboard(); }}
      />
    </PageLayout>
  );
}
