
import { Factory, Handshake } from 'lucide-react';
import FilterChips from '@/components/ui/filter-chips';

/**
 * Identifier visual untuk membedakan data proses bisnis:
 * - Internal  : produksi milik sendiri (business_type != 'maklon' / legacy null)
 * - Maklon    : produksi jasa (CMT) untuk buyer eksternal (business_type == 'maklon')
 *
 * Dipakai di list yang menggabungkan data internal + maklon (mis. Shipment portal produksi).
 */
export function BizBadge({ type, size = 'sm', className = '' }) {
  const isMaklon = type === 'maklon';
  const Icon = isMaklon ? Handshake : Factory;
  const pad = size === 'xs' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-0.5 text-xs';
  const tone = isMaklon
    ? 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.35)]'
    : 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.35)]';
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border font-semibold ${pad} ${tone} ${className}`}
      data-testid={`biz-badge-${isMaklon ? 'maklon' : 'internal'}`}
      title={isMaklon ? 'Produksi Maklon (CMT)' : 'Produksi Internal'}
    >
      <Icon className="w-3 h-3" />
      {isMaklon ? 'Maklon' : 'Internal'}
    </span>
  );
}

/**
 * Penyaring Semua / Internal / Maklon (client-side).
 * value: 'all' | 'internal' | 'maklon'
 * Standar UI/UX v2: memakai FilterChips (dulu segmen buatan sendiri); props & data-testid tetap.
 */
export function BizFilter({ value = 'all', onChange, counts = null, className = '' }) {
  const opts = [
    { key: 'all', label: 'Semua' },
    { key: 'internal', label: 'Internal' },
    { key: 'maklon', label: 'Maklon' },
  ].map((o) => (counts ? { ...o, count: counts[o.key] ?? null } : o));
  return (
    <FilterChips options={opts} value={value} onChange={onChange} hideWhenEmpty={false}
      className={className} testId="biz-filter" ariaLabel="Jenis proses bisnis" />
  );
}

/** Helper cocokkan business_type sebuah row terhadap nilai filter. */
export function matchBiz(rowType, filter) {
  if (filter === 'all') return true;
  if (filter === 'maklon') return rowType === 'maklon';
  return rowType !== 'maklon'; // internal + legacy/null
}
