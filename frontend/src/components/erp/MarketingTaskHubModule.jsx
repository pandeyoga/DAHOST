/**
 * MarketingTaskHubModule.jsx — Manajemen Tugas (Portal Toko).
 * Consolidation #10: Papan tugas + Menunggu persetujuan + Templat tugas
 * Replaces: marketing-tasks + marketing-approvals + marketing-templates (3 → 1)
 *
 * Standar UI/UX v2 (8 Nov 2026): HubTabs (dulu kepala & tab buatan sendiri → kepala ganda dengan modul di dalamnya);
 * judul tiap tab disembunyikan otomatis, tombolnya pindah ke baris tab.
 */
import React, { useState, useEffect } from 'react';
import HubTabs from './hubs/HubTabs';
import TaskManagementModule from './TaskManagementModule';
import ApprovalInboxModule from './ApprovalInboxModule';
import TaskTemplatesModule from './TaskTemplatesModule';

const API = process.env.REACT_APP_BACKEND_URL;

export default function MarketingTaskHubModule({ token }) {
  const [pendingCount, setPendingCount] = useState(0);

  useEffect(() => {
    // Jumlah tugas menunggu persetujuan untuk label tab (total dari server)
    fetch(`${API}/api/marketing/tasks?status=pending_approval&limit=1`, {
      headers: { Authorization: `Bearer ${token || localStorage.getItem('erp_token')}` },
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) {
          const count = data?.pagination?.total ?? (data?.tasks?.length ?? 0);
          setPendingCount(count);
        }
      })
      .catch(() => {});
  }, [token]);

  return (
    <HubTabs hubId="marketing-task-hub" title="Manajemen tugas"
      subtitle="Tugas harian, persetujuan, dan templat tugas berulang."
      tabs={[
          { key: 'kanban', label: 'Papan tugas', Component: TaskManagementModule, props: { token } },
          { key: 'approvals', label: pendingCount > 0 ? `Menunggu persetujuan (${pendingCount})` : 'Menunggu persetujuan',
            Component: ApprovalInboxModule, props: { token } },
          { key: 'templates', label: 'Templat tugas', Component: TaskTemplatesModule, props: { token } },
        ]} />
  );
}
