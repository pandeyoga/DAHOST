/**
 * WebhookSecurityPanel — status keamanan tanda tangan (HMAC) webhook marketplace (FASE 19 / AUDIT-2).
 *
 * Menampilkan, per platform, apakah verifikasi tanda tangan sudah aktif beserta skema teks yang ditandatangani
 * dan header yang diterima — supaya tim integrasi bisa memperbaiki sendiri tanpa membuka berkas pengaturan server.
 * TIDAK PERNAH menampilkan nilai rahasia (backend `GET /api/marketing/webhooks/security-status` tidak mengirimkannya).
 *
 * Standar UI/UX v2 (8 Nov 2026): satu baris pemberitahuan ringkas; rincian dibuka sebagai popup (dulu panel
 * yang membuka ke bawah di dalam halaman). Rincian = tabel + unduh.
 */
import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { ShieldCheck, ShieldAlert, RefreshCw, ListTree } from 'lucide-react';
import { Button } from '../../ui/button';
import DetailPopup from '../../ui/detail-popup';
import TabelData from '../../ui/tabel-data';
import TombolUnduh from '../../ui/tombol-unduh';
import { Notice, StatusBadge } from '../moduleAtoms';

const API = process.env.REACT_APP_BACKEND_URL || '';

const LABEL = { tokopedia: 'Tokopedia', shopee: 'Shopee', tiktok: 'TikTok Shop' };
/** Skema teks yang ditandatangani, dengan nama bagian dalam bahasa staf. */
const BAGIAN = { webhook_url: 'alamat webhook', raw_body: 'isi kiriman', app_key: 'kunci aplikasi' };
const skema = (v) => String(v || '—').replace(/\{(\w+)\}/g, (_, k) => `[${BAGIAN[k] || k.replace(/_/g, ' ')}]`);
const tanpaKurung = (v) => String(v || '').replace(/\s*\([^)]*\)/g, '');
const ENV_LABEL = { shopee: 'Shopee', tokopedia: 'Tokopedia', tiktok: 'TikTok Shop', shared_fallback: 'Cadangan bersama' };

export default function WebhookSecurityPanel({ headers }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await axios.get(`${API}/api/marketing/webhooks/security-status`, { headers });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Gagal memuat status keamanan');
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => { load(); }, [load]);

  const allOk = data?.all_configured;
  const platforms = data?.platforms || {};
  const baris = Object.entries(platforms).map(([p, v]) => ({ id: p, p, ...v }));
  const statusLabel = (v) => (v.configured ? 'Terverifikasi' : 'Kunci rahasia belum diatur');

  const kolom = [
    { kunci: 'platform', label: 'Platform', hp: 'judul', isi: (r) => <span className="font-medium">{LABEL[r.p] || r.p}</span> },
    { kunci: 'status', label: 'Status', isi: (r) => (
      <StatusBadge status={r.configured ? 'ok' : 'belum'} label={statusLabel(r)} tone={r.configured ? 'success' : 'warning'} />) },
    { kunci: 'teks', label: 'Teks yang ditandatangani', isi: (r) => <span className="text-sm">{skema(r.base_string_scheme)}</span> },
    { kunci: 'header', label: 'Header diterima', isi: (r) => (
      <span className="block min-w-0 break-all text-xs">
        <code className="block text-foreground">{r.canonical_header}</code>
        {(r.accepted_headers || []).filter((h) => h !== r.canonical_header).map((h) => (
          <code key={h} className="block text-muted-foreground">{h}</code>))}
      </span>) },
    { kunci: 'toleransi', label: 'Toleransi pengulangan', rata: 'kanan', isi: (r) => <span className="tabular-nums">{r.replay_tolerance_sec} detik</span> },
  ];

  return (
    <div data-testid="webhook-security-panel">
      <Notice tone={error ? 'danger' : allOk ? 'success' : 'warning'} icon={allOk ? ShieldCheck : ShieldAlert}
        title="Keamanan webhook (tanda tangan HMAC-SHA256)"
        action={
          <div className="flex items-center gap-2">
            <Button size="icon" variant="outline" onClick={load} disabled={loading} title="Muat ulang status keamanan"
              aria-label="Muat ulang status keamanan" data-testid="btn-refresh-webhook-security">
              <RefreshCw className={loading ? 'animate-spin' : ''} />
            </Button>
            <Button size="sm" variant="outline" onClick={() => setOpen(true)} disabled={!data}
              data-testid="btn-toggle-webhook-security">
              <ListTree />Rincian
            </Button>
          </div>
        }>
        <span className="block">
          {error
            ? error
            : allOk
              ? 'Semua platform memverifikasi tanda tangan — kiriman palsu ditolak.'
              : 'Sebagian platform belum punya kunci rahasia. Webhook dari platform itu akan ditolak.'}
        </span>
        <span className="mt-1.5 flex flex-wrap gap-1.5">
          {baris.length === 0 && !loading && !error && <span className="text-xs text-muted-foreground">Tidak ada platform terdaftar.</span>}
          {baris.map((r) => (
            <span key={r.p} data-testid={`webhook-sec-${r.p}`}>
              <StatusBadge status={r.configured ? 'ok' : 'belum'} tone={r.configured ? 'success' : 'warning'}
                label={`${LABEL[r.p] || r.p}: ${r.configured ? 'terverifikasi' : 'belum diatur'}`} />
            </span>
          ))}
        </span>
      </Notice>

      {open && data && (
        <DetailPopup open onClose={() => setOpen(false)} judul="Rincian keamanan webhook" testId="webhook-security-detail"
          keterangan="Nilai kunci rahasia tidak pernah ditampilkan. Kunci diatur di pengaturan server."
          status={<StatusBadge status={allOk ? 'ok' : 'belum'} label={allOk ? 'Semua terverifikasi' : 'Belum lengkap'} tone={allOk ? 'success' : 'warning'} />}
          aksi={<TombolUnduh namaBerkas="keamanan-webhook" namaLembar="Keamanan" baris={baris} testId="webhook-security-unduh"
            kolom={[
              { label: 'Platform', nilai: (r) => LABEL[r.p] || r.p },
              { label: 'Status', nilai: statusLabel },
              { label: 'Teks yang ditandatangani', nilai: (r) => skema(r.base_string_scheme) },
              { label: 'Header utama', nilai: (r) => r.canonical_header },
              { label: 'Header diterima', nilai: (r) => (r.accepted_headers || []).join(', ') },
              { label: 'Toleransi pengulangan (detik)', nilai: (r) => r.replay_tolerance_sec },
            ]} />}>
          <TabelData kolom={kolom} baris={baris} testId="webhook-security-table" />
          <div className="space-y-1 text-sm">
            {baris.filter((r) => r.uses_shared_secret).map((r) => (
              <p key={`s-${r.p}`} className="text-[hsl(var(--warning-text))]">
                {LABEL[r.p] || r.p}: memakai kunci rahasia bersama (pengembangan). Di produksi atur kunci per platform.
              </p>
            ))}
            {platforms.shopee && (
              <p className="text-muted-foreground">Alamat yang ditandatangani Shopee:{' '}
                <code className="break-all text-foreground">{platforms.shopee.webhook_url || '(belum diatur)'}</code></p>
            )}
            {platforms.tiktok && (
              <p className="text-muted-foreground">Kunci aplikasi TikTok: {platforms.tiktok.app_key_set ? 'sudah diatur' : 'belum diatur'}</p>
            )}
          </div>
          {data.env_keys && (
            <div className="space-y-1 border-t border-[var(--glass-border)] pt-3 text-sm">
              <p className="font-medium text-foreground">Nama pengaturan di server (untuk tim teknis)</p>
              {Object.entries(data.env_keys).map(([k, arr]) => (
                <p key={k} className="text-muted-foreground">
                  {ENV_LABEL[k] || k}: <code className="break-all text-xs text-foreground">{arr.map(tanpaKurung).join(' · ')}</code>
                </p>
              ))}
            </div>
          )}
        </DetailPopup>
      )}
    </div>
  );
}
