import React, { Children, useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Search, Download, Loader2, Inbox, ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import TombolUnduh from '@/components/ui/tombol-unduh';
import { EmptyState } from '../moduleAtoms';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useSortableTable } from './useSortableTable';
import PaginationFooter from './PaginationFooter';
import PageLayout from '../layout/PageLayout';

/**
 * DataTable
 *
 * Reusable listing table with two pagination modes:
 *
 *   1. **Client-side mode (default, legacy)**
 *      Pass `data` prop with the full array. The component handles search,
 *      sort, and paging locally (10 rows/page).
 *
 *   2. **Server-side mode (Phase 10C)**
 *      Pass `serverPagination` prop. The component manages page/per_page/sort/search
 *      state internally and calls the provided `fetcher` to retrieve each page.
 *      The `data` prop is ignored in this mode.
 *
 * Server pagination prop shape:
 *   serverPagination = {
 *     fetcher: async ({ page, per_page, sort_by, sort_dir, search }) =>
 *                ({ items, total, page, per_page, total_pages }),
 *     deps: [filterStatus, refetchKey],   // refetch when these change (resets to page 1)
 *     initialPerPage: 20,                 // default 20
 *     initialSort: { key: 'created_at', dir: 'desc' },  // optional default
 *     itemLabel: 'produk',                 // shown in pagination footer
 *     searchDebounceMs: 350,               // default 350ms
 *   }
 *
 * Common props:
 *   columns     : [{ key, label, render?, sortable?, sortValue? }]
 *   data        : array (client-mode only)
 *   searchKeys  : keys used for client-mode search
 *   storageKey  : localStorage key to persist sort
 *   defaultSort : { key, direction } initial sort
 *   actions     : ReactNode rendered in header
 *   exportData  : function to trigger CSV/Excel export (server-mode aware)
 *   expandedRow : (row) => ReactNode | null
 *
 * Standar UI/UX v2 (8 Nov 2026):
 *   searchValue : string — kata cari dikendalikan dari luar (kotak cari di slot `filters` PageLayout); kotak cari
 *                 di kepala tabel lalu disembunyikan, sehingga penyaring tetap satu baris.
 *   unduh       : { namaBerkas, kolom:[{label,nilai}], ambilSemua?, namaLembar? } — tombol Unduh (Excel + CSV) di
 *                 kepala tabel. Mode server: tanpa `ambilSemua` yang diunduh baris halaman yang tampil.
 */

/**
 * PageLayoutSatuBaris — PageLayout yang menaruh `tools` di UJUNG baris penyaring (satu baris flex-wrap).
 * Alasan (8 Nov 2026): di Toolbar bersama, kotak penyaring ber-`flex-1 min-w-0` sedangkan alat `shrink-0`, sehingga
 * di HP (390 px) alat yang lebar (Unduh, muat ulang, …) memeras kotak cari menjadi 46 px dan pil penyaring terpotong.
 * Di sini alat ikut membungkus ke baris berikutnya; di layar lebar tetap rata kanan (ml-auto). Tanpa penyaring →
 * perilaku PageLayout biasa (di hub alat pindah ke baris tab). Usulan perbaikan permanen di Toolbar ada di laporan.
 */
export function PageLayoutSatuBaris({ filters, tools, ...rest }) {
  const adaPenyaring = Children.toArray(filters).length > 0;
  const adaAlat = Children.toArray(tools).length > 0;
  if (!adaPenyaring || !adaAlat) return <PageLayout filters={filters} tools={tools} {...rest} />;
  return (
    <PageLayout {...rest} filters={<>
      {filters}
      <div className="ml-auto flex flex-wrap items-center gap-2" data-alat-baris="">{tools}</div>
    </>} />
  );
}

/** Ambil SEMUA halaman dari endpoint berhalaman ({items,total_pages}) — untuk `ambilSemua` TombolUnduh. */
export async function ambilSemuaHalaman(ambilHalaman, { perHalaman = 200, maksHalaman = 50 } = {}) {
  const semua = [];
  for (let page = 1; page <= maksHalaman; page += 1) {
    const env = await ambilHalaman({ page, per_page: perHalaman });
    const items = Array.isArray(env?.items) ? env.items : (Array.isArray(env) ? env : []);
    semua.push(...items);
    const totalPages = Number(env?.total_pages) || 1;
    if (Array.isArray(env) || page >= totalPages || items.length === 0) break;
  }
  return semua;
}
export default function DataTable({
  columns,
  data,
  searchKeys = [],
  onSearch,
  actions,
  exportData,
  expandedRow,
  storageKey,
  defaultSort,
  serverPagination,
  // FASE 22 — `onRowClick` DULU DITERIMA TAPI TIDAK PERNAH DIPASANG ke <tr>.
  // Akibat nyatanya: modul yang mengandalkan klik baris untuk membuka detail
  // (mis. Surat Jalan Buyer → riwayat dispatch, rincian per PO, child shipment)
  // TIDAK BISA DIBUKA SAMA SEKALI — pengguna menyimpulkan "datanya tidak bisa
  // diambil" padahal hanya pemicunya yang hilang (keluhan #6 owner).
  onRowClick,
  searchValue,
  unduh,
}) {
  const isServerMode = !!serverPagination?.fetcher;

  // ─── Common state ──────────────────────────────────────────────────────────
  const [search, setSearch] = useState('');

  // ─── Server-mode state ─────────────────────────────────────────────────────
  const initialPerPage = serverPagination?.initialPerPage || 20;
  const [serverPage, setServerPage] = useState(1);
  const [serverPerPage, setServerPerPage] = useState(initialPerPage);
  const [serverItems, setServerItems] = useState([]);
  const [serverTotal, setServerTotal] = useState(0);
  const [serverLoading, setServerLoading] = useState(false);
  const [serverError, setServerError] = useState(null);
  const [serverSort, setServerSort] = useState(() => {
    if (storageKey && typeof window !== 'undefined') {
      try {
        const raw = window.localStorage.getItem(`sort:${storageKey}`);
        if (raw) {
          const p = JSON.parse(raw);
          if (p?.sortKey) return { key: p.sortKey, dir: p.sortDir || 'desc' };
        }
      } catch (_) { /* ignore */ }
    }
    if (serverPagination?.initialSort) return { ...serverPagination.initialSort };
    if (defaultSort) return { key: defaultSort.key, dir: defaultSort.direction || 'desc' };
    return { key: null, dir: null };
  });
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Debounce the search box for server mode
  useEffect(() => {
    if (!isServerMode) return undefined;
    const wait = serverPagination?.searchDebounceMs ?? 350;
    const t = setTimeout(() => setDebouncedSearch(search), wait);
    return () => clearTimeout(t);
  }, [search, isServerMode, serverPagination?.searchDebounceMs]);

  // Persist server-mode sort to localStorage (parity with client-mode)
  useEffect(() => {
    if (!isServerMode || !storageKey) return;
    try {
      window.localStorage.setItem(
        `sort:${storageKey}`,
        JSON.stringify({ sortKey: serverSort.key, sortDir: serverSort.dir })
      );
    } catch (_) { /* ignore */ }
  }, [isServerMode, storageKey, serverSort.key, serverSort.dir]);

  // Reset to page 1 whenever caller deps, search, sort, or per-page changes
  const deps = serverPagination?.deps || [];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!isServerMode) return;
    setServerPage(1);
    // deps spread is intentional
  }, [isServerMode, debouncedSearch, serverSort.key, serverSort.dir, serverPerPage, ...deps]);

  // Track latest fetch to avoid race conditions
  const fetchSeqRef = useRef(0);
  // Stabilize the fetcher reference — parents typically pass an inline arrow
  // function inside an inline `serverPagination={{ fetcher: ... }}` object,
  // which would otherwise change identity on every parent render and cause an
  // infinite refetch loop (especially when the fetcher itself calls setState
  // on the parent).
  const fetcherRef = useRef(serverPagination?.fetcher);
  useEffect(() => {
    fetcherRef.current = serverPagination?.fetcher;
  });

  const runFetch = useCallback(async () => {
    if (!isServerMode) return;
    const fetcher = fetcherRef.current;
    if (!fetcher) return;
    const seq = ++fetchSeqRef.current;
    setServerLoading(true);
    setServerError(null);
    try {
      const env = await fetcher({
        page: serverPage,
        per_page: serverPerPage,
        sort_by: serverSort.key || undefined,
        sort_dir: serverSort.dir || undefined,
        search: debouncedSearch || undefined,
      });
      // Stale response — drop
      if (seq !== fetchSeqRef.current) return;
      // Defensive: backend may legacy-return an array for pre-paginated endpoints
      if (Array.isArray(env)) {
        setServerItems(env);
        setServerTotal(env.length);
      } else if (env && typeof env === 'object') {
        setServerItems(Array.isArray(env.items) ? env.items : []);
        setServerTotal(typeof env.total === 'number' ? env.total : 0);
      } else {
        setServerItems([]);
        setServerTotal(0);
      }
    } catch (err) {
      if (seq !== fetchSeqRef.current) return;
      setServerError(err?.message || 'Gagal memuat data');
      setServerItems([]);
      setServerTotal(0);
    } finally {
      if (seq === fetchSeqRef.current) setServerLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isServerMode, serverPage, serverPerPage, serverSort.key, serverSort.dir, debouncedSearch, ...deps]);

  useEffect(() => {
    if (!isServerMode) return;
    runFetch();
  }, [runFetch, isServerMode]);

  // ─── Client-mode setup ─────────────────────────────────────────────────────
  const [clientPage, setClientPage] = useState(1);
  const clientPageSize = 10;

  const getSortValue = (row, key) => {
    const col = columns.find((c) => c.key === key);
    if (col && typeof col.sortValue === 'function') {
      try {
        return col.sortValue(row);
      } catch (_) {
        return row[key];
      }
    }
    return row ? row[key] : undefined;
  };

  // Sorting hook only used for client-mode; server-mode bypasses it
  const { sortedData, sortKey: clientSortKey, sortDir: clientSortDir, toggleSort: clientToggleSort } = useSortableTable(
    isServerMode ? [] : data || [],
    {
      storageKey: isServerMode ? null : storageKey,
      defaultKey: defaultSort?.key || null,
      defaultDir: defaultSort?.direction || 'asc',
      getValue: getSortValue,
    }
  );

  // ─── Sort indicator + toggle (mode-aware) ─────────────────────────────────
  const activeSortKey = isServerMode ? serverSort.key : clientSortKey;
  const activeSortDir = isServerMode ? serverSort.dir : clientSortDir;

  const toggleSort = (key) => {
    if (isServerMode) {
      setServerSort((prev) => {
        if (prev.key !== key) return { key, dir: 'asc' };
        if (prev.dir === 'asc') return { key, dir: 'desc' };
        if (prev.dir === 'desc') return { key: null, dir: null };
        return { key, dir: 'asc' };
      });
    } else {
      clientToggleSort(key);
    }
  };

  const indicatorFor = (key) => {
    if (key === activeSortKey && activeSortDir) return activeSortDir === 'asc' ? '▲' : '▼';
    return '↕';
  };

  // ─── Client-mode filter/paginate (memoized to avoid re-compute on unrelated renders) ───
  const clientFiltered = useMemo(() => {
    if (isServerMode) return [];
    if (!search) return sortedData || [];
    const lc = search.toLowerCase();
    return (sortedData || []).filter((row) =>
      searchKeys.some((key) => String(row[key] || '').toLowerCase().includes(lc))
    );
  }, [isServerMode, sortedData, search, searchKeys]);

  const clientTotalPages = useMemo(
    () => Math.ceil((clientFiltered?.length || 0) / clientPageSize),
    [clientFiltered, clientPageSize]
  );
  const clientPaginated = useMemo(
    () => !isServerMode
      ? (clientFiltered || []).slice((clientPage - 1) * clientPageSize, clientPage * clientPageSize)
      : [],
    [isServerMode, clientFiltered, clientPage, clientPageSize]
  );

  const handleSearch = (val) => {
    setSearch(val);
    if (!isServerMode) setClientPage(1);
    if (onSearch) onSearch(val);
  };
  // Kotak cari di luar tabel (slot filters PageLayout) → ikuti nilainya.
  const searchOutside = searchValue !== undefined;
  useEffect(() => {
    if (!searchOutside) return;
    setSearch(searchValue || '');
    if (!isServerMode) setClientPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchOutside, searchValue]);

  // ─── Render data choice ────────────────────────────────────────────────────
  const renderRows = isServerMode ? serverItems : clientPaginated;

  // ─── Virtualization (opt-in via serverPagination.virtualize) ──────────────
  // When enabled, only the rows visible in the scroll viewport are rendered to
  // the DOM. Critical for `per_page >= 50` where DOM cost dominates.
  // Falls back to non-virtualized rendering automatically when:
  //   - data is empty (loading / no rows)
  //   - shouldVirtualize is false
  const shouldVirtualize = isServerMode && !!serverPagination?.virtualize && renderRows.length > 0;
  const virtualizeMaxHeight = serverPagination?.virtualizeHeight || 600;
  const estimatedRowHeight = serverPagination?.estimatedRowHeight || 56;

  const scrollParentRef = useRef(null);
  const rowVirtualizer = useVirtualizer({
    count: shouldVirtualize ? renderRows.length : 0,
    getScrollElement: () => scrollParentRef.current,
    estimateSize: () => estimatedRowHeight,
    overscan: 8,
    // Re-measure whenever the underlying data identity changes
    getItemKey: (index) => renderRows[index]?.id ?? index,
  });

  const virtualItems = shouldVirtualize ? rowVirtualizer.getVirtualItems() : [];
  const totalSize = shouldVirtualize ? rowVirtualizer.getTotalSize() : 0;
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start : 0;
  const paddingBottom = virtualItems.length > 0
    ? totalSize - virtualItems[virtualItems.length - 1].end
    : 0;

  // Reset scroll to top whenever a fresh page lands (server mode)
  useEffect(() => {
    if (shouldVirtualize && scrollParentRef.current) {
      scrollParentRef.current.scrollTop = 0;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverPage, debouncedSearch, serverSort.key, serverSort.dir, serverPerPage]);

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--glass-border)] bg-[var(--card-surface)]">
      {/* Kepala tabel: cari (kiri) · unduh/aksi (kanan). Tanpa isi → tidak digambar. */}
      {(!searchOutside || exportData || unduh || actions) && (
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--glass-border)] px-3 py-2.5">
        {!searchOutside && (
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="text"
            placeholder="Cari…"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            className="pl-8"
            data-testid="datatable-search-input"
          />
          {isServerMode && serverLoading && (
            <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--primary))] w-4 h-4 animate-spin" />
          )}
        </div>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {unduh && (
            <TombolUnduh namaBerkas={unduh.namaBerkas} namaLembar={unduh.namaLembar} kolom={unduh.kolom}
              baris={renderRows} ambilSemua={unduh.ambilSemua} testId={unduh.testId || 'datatable-unduh'} />
          )}
          {exportData && (
            <Button
              variant="outline"
              onClick={exportData}
              data-testid="datatable-export-btn"
            >
              <Download /> Unduh
            </Button>
          )}
          {actions}
        </div>
      </div>
      )}

      {/* Server-mode error banner */}
      {isServerMode && serverError && (
        <div className="px-4 py-2 border-b border-[var(--glass-border)] text-sm text-[hsl(var(--danger-text))]" role="alert" data-testid="datatable-error">
          Gagal memuat data: {serverError}
        </div>
      )}

      {/* Table */}
      <div
        ref={scrollParentRef}
        className={shouldVirtualize ? 'overflow-auto' : 'overflow-x-auto'}
        style={shouldVirtualize ? { maxHeight: virtualizeMaxHeight } : undefined}
        data-testid={shouldVirtualize ? 'datatable-virtual-scroller' : undefined}
      >
        <table className="w-full text-sm">
          <thead className={shouldVirtualize ? 'sticky top-0 z-10' : undefined}>
            <tr>
              {columns.map((col) => {
                const isSortable = col.sortable !== false && col.key !== 'actions';
                const active = isSortable && activeSortKey === col.key && !!activeSortDir;
                return (
                  <th
                    key={col.key}
                    role={isSortable ? 'button' : undefined}
                    aria-sort={active ? (activeSortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                    data-testid={isSortable ? `sort-header-${col.key}` : undefined}
                    onClick={isSortable ? () => toggleSort(col.key) : undefined}
                    className={`text-left px-3 py-2.5 text-xs font-medium text-muted-foreground whitespace-nowrap bg-[var(--card-surface)] ${
                      isSortable ? 'cursor-pointer select-none hover:text-foreground' : ''
                    }`}
                  >
                    <span className="inline-flex items-center gap-1">
                      {col.label}
                      {isSortable && (
                        <span
                          className={`text-xs ${active ? 'text-[hsl(var(--primary))]' : 'text-muted-foreground/50'}`}
                          aria-hidden="true"
                        >
                          {indicatorFor(col.key)}
                        </span>
                      )}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          {shouldVirtualize ? (
            // ─── Virtualized rendering: one tbody per row so measureElement
            // can pick up dynamic heights (including expanded sub-rows). ───
            <>
              {paddingTop > 0 && (
                <tbody aria-hidden="true">
                  <tr>
                    <td colSpan={columns.length} style={{ height: paddingTop, padding: 0, border: 0 }} />
                  </tr>
                </tbody>
              )}
              {virtualItems.map((vi) => {
                const row = renderRows[vi.index];
                const exp = expandedRow ? expandedRow(row) : null;
                return (
                  <tbody
                    key={row.id ?? vi.index}
                    data-index={vi.index}
                    ref={rowVirtualizer.measureElement}
                  >
                    <tr className={`hover:bg-foreground/[0.03] transition-colors border-t border-[var(--glass-border)] ${onRowClick ? 'cursor-pointer' : ''}`}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}>
                      {columns.map((col) => (
                        <td key={col.key} className="px-3 py-2.5 text-sm text-foreground align-top">
                          {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '-')}
                        </td>
                      ))}
                    </tr>
                    {exp && (
                      <tr>
                        {/* FASE 9: sel expand tidak boleh memaksa lebar tabel induk;
                            kontennya membawa scroll horizontal sendiri. */}
                        <td colSpan={columns.length} className="p-0 border-b border-[var(--glass-border)] max-w-0">
                          {exp}
                        </td>
                      </tr>
                    )}
                  </tbody>
                );
              })}
              {paddingBottom > 0 && (
                <tbody aria-hidden="true">
                  <tr>
                    <td colSpan={columns.length} style={{ height: paddingBottom, padding: 0, border: 0 }} />
                  </tr>
                </tbody>
              )}
            </>
          ) : (
            <tbody className="divide-y divide-[var(--glass-border)]">
              {isServerMode && serverLoading && renderRows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="text-center py-4 text-muted-foreground/70 text-sm">
                    <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-[hsl(var(--primary))]" />
                    Memuat data...
                  </td>
                </tr>
              ) : renderRows.length === 0 ? (
                <tr>
                  <td colSpan={columns.length}>
                    <EmptyState icon={Inbox} title="Belum ada data"
                      description={search ? 'Ubah kata pencarian untuk melihat data lain.' : 'Data akan tampil di sini setelah dicatat.'} />
                  </td>
                </tr>
              ) : (
                renderRows.map((row, i) => (
                  <React.Fragment key={row.id || i}>
                    <tr className={`hover:bg-foreground/[0.03] transition-colors ${onRowClick ? 'cursor-pointer' : ''}`}
                      onClick={onRowClick ? () => onRowClick(row) : undefined}>
                      {columns.map((col) => (
                        <td key={col.key} className="px-3 py-2.5 text-sm text-foreground align-top">
                          {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '-')}
                        </td>
                      ))}
                    </tr>
                    {expandedRow && expandedRow(row) && (
                      <tr>
                        {/* FASE 9: sel expand tidak boleh memaksa lebar tabel induk;
                            kontennya membawa scroll horizontal sendiri. */}
                        <td colSpan={columns.length} className="p-0 border-b border-[var(--glass-border)] max-w-0">
                          {expandedRow(row)}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          )}
        </table>
      </div>

      {/* Pagination */}
      {isServerMode ? (
        <PaginationFooter
          page={serverPage}
          perPage={serverPerPage}
          total={serverTotal}
          onPageChange={setServerPage}
          onPerPageChange={setServerPerPage}
          loading={serverLoading}
          itemLabel={serverPagination?.itemLabel || 'baris'}
          testIdPrefix="datatable-pagination"
        />
      ) : (
        clientTotalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--glass-border)]">
            <span className="text-sm text-muted-foreground">
              {(clientPage - 1) * clientPageSize + 1}–{Math.min(clientPage * clientPageSize, clientFiltered.length)} dari {clientFiltered.length}
            </span>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon-sm" onClick={() => setClientPage((p) => Math.max(1, p - 1))}
                disabled={clientPage === 1} title="Halaman sebelumnya" aria-label="Halaman sebelumnya">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              {Array.from({ length: Math.min(5, clientTotalPages) }, (_, i) => {
                const p = i + 1;
                return (
                  <Button key={p} size="icon-sm" variant={clientPage === p ? 'default' : 'ghost'}
                    onClick={() => setClientPage(p)} aria-label={`Halaman ${p}`} aria-current={clientPage === p ? 'page' : undefined}>
                    {p}
                  </Button>
                );
              })}
              <Button variant="ghost" size="icon-sm" onClick={() => setClientPage((p) => Math.min(clientTotalPages, p + 1))}
                disabled={clientPage === clientTotalPages} title="Halaman berikutnya" aria-label="Halaman berikutnya">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )
      )}
    </div>
  );
}
