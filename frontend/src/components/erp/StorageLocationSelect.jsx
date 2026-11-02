import { useEffect, useState } from 'react';

// 2026-11-02 — No.18(a) owner: pengguna WAJIB memilih lokasi. Satu pemilih lokasi
// penyimpanan untuk form gerak stok yang dulu tidak punya pemilih (atau diam-diam
// memakai "lokasi aktif pertama"). Sumber: SSOT `/api/rahaza/storage-locations`
// (zona kanonik + lokasi lama berperan simpan; kantor & lantai produksi tidak ikut).
// Tidak ada pilihan bawaan: kosong sampai pengguna memilih.
let _cache = null;

export function useStorageLocations(token) {
  const [items, setItems] = useState(_cache || []);
  const [loading, setLoading] = useState(!_cache);
  useEffect(() => {
    if (_cache || !token) return undefined;
    let alive = true;
    fetch('/api/rahaza/storage-locations', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (!alive) return;
        _cache = Array.isArray(d) ? d : [];
        setItems(_cache);
      })
      .catch(() => { if (alive) setItems([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [token]);
  return { items, loading };
}

export default function StorageLocationSelect({
  token, value, onChange, required = true, testId = 'storage-location-select',
  placeholder = '— Pilih lokasi —', excludeIds = [], className = '', disabled = false,
}) {
  const { items, loading } = useStorageLocations(token);
  const list = items.filter((l) => !excludeIds.includes(l.id));
  return (
    <select
      value={value || ''}
      onChange={(e) => onChange(e.target.value)}
      required={required}
      disabled={disabled || loading}
      data-testid={testId}
      className={className || 'w-full h-10 px-3 rounded-lg border border-[var(--glass-border)] bg-[var(--input-surface)] text-sm text-foreground'}
    >
      <option value="">{loading ? 'Memuat lokasi…' : placeholder}</option>
      {list.map((l) => (
        <option key={l.id} value={l.id}>
          {l.code ? `${l.code} · ` : ''}{l.name || l.id}
        </option>
      ))}
    </select>
  );
}
