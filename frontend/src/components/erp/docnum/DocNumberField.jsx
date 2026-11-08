/**
 * docnum/DocNumberField.jsx — SATU komponen kolom "Nomor Dokumen" untuk semua form.
 *
 * MENGAPA ADA (FASE G, sesi #18)
 * ------------------------------
 * Kebijakan penomoran (Otomatis/Manual per jenis dokumen) diatur System Admin di
 * layar "Penomoran Dokumen". Sebelum komponen ini, layar dokumen TIDAK PERNAH
 * membaca kebijakan itu, sehingga:
 *   · mode OTOMATIS → layar tetap menyuruh staf mengetik nomor, lalu backend
 *     MENOLAK ("nomor tidak boleh diketik") atas setelan yang staf tidak pernah lihat;
 *   · mode MANUAL   → layar tidak punya kolom nomor sama sekali, jadi dokumen TIDAK
 *     BISA dibuat ("nomor wajib diisi") dan orang menyimpulkan sistemnya rusak.
 * Satu komponen dipakai bersama supaya keduanya tidak bisa berbeda pendapat lagi,
 * dan supaya jenis dokumen berikutnya cukup memasangnya (bukan menulis ulang).
 *
 * Pakai:
 *   const pol = useDocNumberPolicy('dewi_kasbon_requests.request_number', token);
 *   <DocNumberField policy={pol} value={form.request_number}
 *                   onChange={v => setForm(f => ({ ...f, request_number: v }))}
 *                   testId="kasbon-number" />
 *   // saat submit: kirim nomor HANYA bila mode manual
 *   ...(pol?.mode === 'manual' ? { request_number: form.request_number } : {})
 */
import { useEffect, useState } from 'react';

/** "KSB-{YYYY}{MM}-{SEQ:5}" → "KSB-202611-00001" (contoh nomor yang mudah dipahami staf). */
export function contohDariPola(pola) {
  if (!pola) return '';
  const d = new Date(Date.now() + 7 * 3600 * 1000); // WIB
  const yyyy = String(d.getUTCFullYear());
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(d.getUTCDate()).padStart(2, '0');
  return String(pola)
    .replace(/\{YYYY\}/g, yyyy).replace(/\{YY\}/g, yyyy.slice(2))
    .replace(/\{MM\}/g, mm).replace(/\{DD\}/g, dd)
    .replace(/\{SEQ(?::(\d+))?\}/g, (_, n) => '1'.padStart(Number(n || 4), '0'))
    .replace(/\{[^}]*\}/g, '');
}

const API = process.env.REACT_APP_BACKEND_URL || '';

/** Baca kebijakan penomoran satu jenis dokumen. `null` = belum tahu / gagal baca.
 *
 * `ctx` (SESI #19) = token konteks yang mempengaruhi nomor, mis. `{ TIPE: 'SJ-INTERNAL' }`
 * untuk Surat Jalan. Tanpa itu pratinjau memakai token contoh ("TIP/2026/08/0001") —
 * nomor yang tidak akan pernah lahir.
 */
export function useDocNumberPolicy(key, token, ctx, refreshKey) {
  const [policy, setPolicy] = useState(null);
  const ctxKey = JSON.stringify(ctx || {});
  useEffect(() => {
    if (!key) return;
    let alive = true;
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const q = new URLSearchParams({ key });
    Object.entries(JSON.parse(ctxKey)).forEach(([k, v]) => {
      if (v) q.set(`ctx_${k}`, v);
    });
    fetch(`${API}/api/doc-number-policy?${q.toString()}`, { headers })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (alive) setPolicy(d); })
      .catch(() => { if (alive) setPolicy(null); });
    return () => { alive = false; };
  }, [key, token, ctxKey, refreshKey]);
  return policy;
}

/** Nomor yang harus dikirim ke backend (kosong bila mode otomatis). */
export function docNumberPayload(policy, field, value) {
  if (!policy || policy.mode !== 'manual') return {};
  return { [field]: (value || '').trim() };
}

export default function DocNumberField({
  policy, value, onChange, testId = 'docnum', label, className = '',
}) {
  const manual = policy?.mode === 'manual';
  const title = label || `Nomor ${policy?.label || 'Dokumen'}`;

  return (
    <div className={className} data-testid={`${testId}-wrap`}>
      <label className="block text-xs font-medium text-foreground/80 mb-1">
        {title}{manual && <span className="text-[hsl(var(--destructive))]"> *</span>}
        <span className="text-[11px] text-muted-foreground font-normal">
          {policy ? (manual ? ' (manual)' : ' (otomatis)') : ' (memuat kebijakan…)'}
        </span>
      </label>

      {manual ? (
        <>
          <input
            required
            data-testid={`${testId}-input`}
            value={value || ''}
            onChange={(e) => onChange?.(e.target.value)}
            placeholder={policy?.contoh || ''}
            className="w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground tabular-nums focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary)/0.35)]"
          />
          <p className="text-xs text-muted-foreground mt-1" data-testid={`${testId}-hint`}>
            {/* v2: pola program ({YYYY}{MM}-{SEQ:5}) tidak ditampilkan ke staf — cukup contoh nomornya */}
            Wajib berbentuk seperti <b className="tabular-nums text-foreground">{policy.contoh || contohDariPola(policy.format)}</b>.
            Ubah ke otomatis di Administrasi Sistem → Penomoran Dokumen.
          </p>
        </>
      ) : (
        <>
          <input
            readOnly disabled
            data-testid={`${testId}-auto`}
            value={policy?.nomor_berikutnya || policy?.contoh || 'dibuat otomatis saat disimpan'}
            className="w-full h-9 px-3 rounded-lg border border-[var(--glass-border)] bg-muted/50 text-sm text-muted-foreground tabular-nums"
          />
          <p className="text-xs text-muted-foreground mt-1" data-testid={`${testId}-hint`}>
            Dibuat sistem saat disimpan{(policy?.contoh || policy?.format) && <> (contoh <span className="tabular-nums">{policy.contoh || contohDariPola(policy.format)}</span>)</>}.
            Ubah ke manual di Administrasi Sistem → Penomoran Dokumen.
          </p>
        </>
      )}
    </div>
  );
}
