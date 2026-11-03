/**
 * AdminSetupPanelModule — Phase 7F
 * One-click setup COA, Posting Profiles, EEM Categories untuk deployment baru
 */
import React, { useState, useEffect } from 'react';
import { Database, CheckCircle2, AlertCircle, Loader2, RefreshCw, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

// Auth: gunakan JWT Bearer (standar aplikasi, sama seperti 224 modul lain).
// Sebelumnya modul ini keliru pakai `credentials: 'include'` (cookie) tanpa
// Authorization header → endpoint `_require_super` menolak 401 → "Gagal fetch status".
const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem('erp_token')}` });

// 2026-11-02 (S2-H) — kartu "Integritas tautan COA" dari accounting-status.coa_integrity (core/coa_bindings).
function CoaIntegrityCard({ data }) {
  const groups = [
    ['dangling_refs', 'Akun tidak ada di Bagan Akun'],
    ['inactive_targets', 'Akun nonaktif'],
    ['group_targets', 'Akun grup (tidak bisa diposting)'],
  ];
  const nProblem = groups.reduce((n, [k]) => n + (data[k] || []).length, 0);
  return (
    <Card className={`shadow-sm ${nProblem ? 'border-destructive/50' : 'border-border/50'}`} data-testid="coa-integrity-card">
      <CardHeader>
        <CardTitle className="text-base flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            {nProblem ? <AlertCircle className="h-4 w-4 text-destructive" /> : <CheckCircle2 className="h-4 w-4 text-success" />}
            Integritas tautan COA
          </span>
          <Badge variant="outline" className={nProblem ? 'text-destructive' : 'text-success'}>{nProblem ? `${nProblem} masalah` : 'OK'}</Badge>
        </CardTitle>
        <CardDescription>
          {data.checked_refs ?? 0} rujukan konfigurasi (profil posting, toko, rekening, relasi, pemetaan GL, kas kecil, aset, anggaran, kode program) diperiksa terhadap {data.accounts ?? 0} akun.
          {data.error && ` Gagal: ${data.error}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {groups.map(([k, label]) => (data[k] || []).length > 0 && (
          <div key={k}>
            <p className="font-medium">{label} ({data[k].length})</p>
            <ul className="mt-1 space-y-1 text-xs">
              {data[k].slice(0, 8).map((r) => (
                <li key={r.code} className="break-words">
                  <span className="font-mono">{r.code}</span> {r.name || ''} — {(r.refs || []).slice(0, 2).join(' · ')}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {(data.fallback_warnings || []).length > 0 && (
          <div>
            <p className="font-medium">Kode cadangan yang akan terpakai ({data.fallback_warnings.length})</p>
            <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
              {data.fallback_warnings.slice(0, 6).map((w) => (
                <li key={`${w.role}-${w.code}`}>Peran <span className="font-mono">{w.role}</span> kosong → <span className="font-mono">{w.code}</span> {w.name || ''}</li>
              ))}
            </ul>
          </div>
        )}
        {(data.sync_skipped || []).length > 0 && (
          <div>
            <p className="font-medium">Dilewati sinkron toko ({data.sync_skipped.length})</p>
            <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
              {data.sync_skipped.slice(0, 6).map((x) => <li key={x.code}><span className="font-mono">{x.code}</span> {x.name} — {x.reason}</li>)}
            </ul>
          </div>
        )}
        {!nProblem && !(data.fallback_warnings || []).length && !(data.sync_skipped || []).length && (
          <p className="text-muted-foreground">Semua rujukan menunjuk akun yang ada, aktif, dan bisa diposting.</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function AdminSetupPanelModule() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [seedLoading, setSeedLoading] = useState({
    coa: false,
    posting_profiles: false,
    all: false,
  });

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/rahaza/admin/accounting-status`, {
        headers: authHeaders(),
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data);
      } else {
        toast.error('Gagal fetch status');
      }
    } catch (err) {
      console.error('Fetch status error:', err);
      toast.error('Terjadi kesalahan saat fetch status');
    } finally {
      setLoading(false);
    }
  };

  const handleSeedCOA = async () => {
    setSeedLoading((prev) => ({ ...prev, coa: true }));
    try {
      const res = await fetch(`${API_BASE}/api/rahaza/admin/seed-coa`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const data = await res.json();
      if (data.ok) {
        const extra = [
          data.recreated?.length ? `${data.recreated.length} akun bawaan dibuat ulang (${data.recreated.slice(0, 5).join(', ')})` : '',
          data.normal_balance_fixed?.length ? `saldo normal kontra dirapikan: ${data.normal_balance_fixed.join(', ')}` : '',
        ].filter(Boolean).join(' · ');
        toast.success(`COA: ${data.count_before} → ${data.count_after} akun${extra ? ` · ${extra}` : ''}`);
        await fetchStatus();
      } else {
        toast.error(data.error || 'Seed COA failed');
      }
    } catch (err) {
      console.error('Seed COA error:', err);
      toast.error('Terjadi kesalahan');
    } finally {
      setSeedLoading((prev) => ({ ...prev, coa: false }));
    }
  };

  const handleSeedPostingProfiles = async () => {
    setSeedLoading((prev) => ({ ...prev, posting_profiles: true }));
    try {
      const res = await fetch(`${API_BASE}/api/rahaza/admin/seed-posting-profiles`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const data = await res.json();
      if (data.ok) {
        toast.success(`Posting Profiles seeded: ${data.count_before} → ${data.count_after} profiles`);
        await fetchStatus();
      } else {
        toast.error(data.error || 'Seed Posting Profiles failed');
      }
    } catch (err) {
      console.error('Seed Posting Profiles error:', err);
      toast.error('Terjadi kesalahan');
    } finally {
      setSeedLoading((prev) => ({ ...prev, posting_profiles: false }));
    }
  };

  const handleSeedAll = async () => {
    setSeedLoading((prev) => ({ ...prev, all: true }));
    try {
      const res = await fetch(`${API_BASE}/api/rahaza/admin/seed-all-accounting`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const data = await res.json();
      if (data.ok) {
        let msg = 'Semua seed berhasil: ';
        const details = data.details || {};
        if (details.coa?.ok) msg += `COA (${details.coa.count_after}) `;
        if (details.posting_profiles?.ok) msg += `Profiles (${details.posting_profiles.count_after}) `;
        toast.success(msg);
        await fetchStatus();
      } else {
        toast.error('Seed all failed');
      }
    } catch (err) {
      console.error('Seed all error:', err);
      toast.error('Terjadi kesalahan');
    } finally {
      setSeedLoading((prev) => ({ ...prev, all: false }));
    }
  };

  const StatusBadge = ({ status }) => {
    if (status === 'ready') {
      return <Badge className="bg-success/15 text-success hover:bg-success/20">Ready</Badge>;
    }
    return <Badge variant="outline" className="text-muted-foreground">Empty</Badge>;
  };

  if (loading && !status) {
    return (
      <div className="h-screen flex items-center justify-center" data-testid="admin-setup-loading">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div data-testid="admin-setup-panel-module">
      <div className="mx-auto max-w-4xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight" data-testid="module-title">
              Admin Setup Panel
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Setup COA, Posting Profiles, dan master data accounting untuk deployment baru
            </p>
          </div>
          <div className="flex gap-2">
            <Badge variant="outline" className="text-xs">Phase 7F</Badge>
            <Button 
              variant="ghost" 
              size="sm" 
              onClick={fetchStatus}
              data-testid="refresh-status-btn"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Quick Actions */}
        <Card className="border-border/50 shadow-sm bg-primary/5">
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Zap className="h-5 w-5 text-primary" />
              Quick Setup
            </CardTitle>
            <CardDescription>
              One-click setup untuk deployment baru (idempotent — aman dijalankan berulang kali)
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button 
              onClick={handleSeedAll} 
              disabled={seedLoading.all}
              size="lg"
              className="w-full"
              data-testid="seed-all-btn"
            >
              {seedLoading.all ? (
                <>
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  Setup Semua Sedang Berjalan...
                </>
              ) : (
                <>
                  <Database className="mr-2 h-5 w-5" />
                  Setup Semua (COA + Posting Profiles + EEM)
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {/* Status Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* COA */}
          <Card className="border-border/50 shadow-sm">
            <CardHeader>
              <CardTitle className="text-base flex items-center justify-between">
                <span>Chart of Accounts (COA)</span>
                {status && <StatusBadge status={status.coa?.status} />}
              </CardTitle>
              <CardDescription>
                {status?.coa?.count || 0} accounts
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button 
                onClick={handleSeedCOA} 
                disabled={seedLoading.coa}
                variant="outline"
                className="w-full"
                data-testid="seed-coa-btn"
              >
                {seedLoading.coa ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Seeding...
                  </>
                ) : (
                  <>
                    <Database className="mr-2 h-4 w-4" />
                    Seed COA
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Posting Profiles */}
          <Card className="border-border/50 shadow-sm">
            <CardHeader>
              <CardTitle className="text-base flex items-center justify-between">
                <span>Posting Profiles</span>
                {status && <StatusBadge status={status.posting_profiles?.status} />}
              </CardTitle>
              <CardDescription>
                {status?.posting_profiles?.count || 0} profiles
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Button 
                onClick={handleSeedPostingProfiles} 
                disabled={seedLoading.posting_profiles}
                variant="outline"
                className="w-full"
                data-testid="seed-posting-profiles-btn"
              >
                {seedLoading.posting_profiles ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Seeding...
                  </>
                ) : (
                  <>
                    <Database className="mr-2 h-4 w-4" />
                    Seed Posting Profiles
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* EEM Categories */}
          <Card className="border-border/50 shadow-sm">
            <CardHeader>
              <CardTitle className="text-base flex items-center justify-between">
                <span>Employee Expense Categories</span>
                {status && <StatusBadge status={status.eem_categories?.status} />}
              </CardTitle>
              <CardDescription>
                {status?.eem_categories?.count || 0} categories
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                Otomatis ter-seed saat seed all
              </div>
            </CardContent>
          </Card>

          {/* EEM GL Mapping */}
          <Card className="border-border/50 shadow-sm">
            <CardHeader>
              <CardTitle className="text-base flex items-center justify-between">
                <span>EEM GL Mapping</span>
                {status && <StatusBadge status={status.eem_gl_mapping?.status} />}
              </CardTitle>
              <CardDescription>
                {status?.eem_gl_mapping?.count || 0} mappings
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground">
                Setup manual via EEM GL Mapping module
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 2026-11-02 (S2-H) INV-COA-REF — rujukan konfigurasi → akun ada, aktif, bukan grup */}
        {status?.coa_integrity && <CoaIntegrityCard data={status.coa_integrity} />}

        {/* Info */}
        <Card className="border-border/50 bg-muted/20">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" />
              Informasi
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground space-y-2">
            <p>• <strong>COA</strong>: skema tunggal 4 digit (1 aset · 2 liabilitas · 3 ekuitas · 4 pendapatan · 5 HPP · 6 beban · 7 pendapatan/beban lain). Akun bawaan yang hilang dibuat ulang & dilaporkan; saldo normal akun kontra dirapikan.</p>
            <p>• <strong>Posting Profiles</strong>: 18+ event types (ar_invoice, ap_invoice, payroll_run, inventory_*, expense, wip_to_fg, bank_transfer, dll)</p>
            <p>• <strong>Idempotent</strong>: Aman dijalankan berulang kali tanpa duplikasi data</p>
            <p>• <strong>Auto-seed on startup</strong>: Deployment baru otomatis seed COA & Posting Profiles jika masih kosong</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
