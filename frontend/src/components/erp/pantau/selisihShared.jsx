/**
 * Penyaring bersama Laporan Selisih (periode · portal · vendor · PO). Disimpan di konteks modul supaya
 * pindah tab tidak mengulang pilihan.
 */
import { createContext, useContext, useMemo, useState } from 'react';
import SmartNativeSelect from '@/components/ui/smart-native-select';
import PeriodPicker, { ALL_TIME, PERIOD_PRESETS, periodFromPreset } from '../finance/PeriodPicker';
import { useApi } from './pantauShared';

const Ctx = createContext(null);

export function SelisihFilterProvider({ businessType, children }) {
  const [bt, setBt] = useState(businessType);
  const [period, setPeriod] = useState(() => periodFromPreset('3m'));
  const [vendor, setVendor] = useState('');
  const [po, setPo] = useState('');
  const qs = `business_type=${bt}${period.from ? `&from=${period.from}` : ''}${period.to ? `&to=${period.to}` : ''}`;
  // pilihan vendor & PO = PO pada portal + periode ini (tanpa saringan vendor/PO)
  const opts = useApi(`/pantau/selisih?${qs}`);
  const value = useMemo(() => ({
    bt, setBt: (v) => { setBt(v); setVendor(''); setPo(''); }, period, setPeriod, vendor, setVendor, po, setPo,
    query: `${qs}${vendor ? `&vendor_id=${encodeURIComponent(vendor)}` : ''}${po ? `&po_id=${encodeURIComponent(po)}` : ''}`,
    vendors: opts.data?.vendors || [], pos: opts.data?.pos || [],
  }), [bt, period, vendor, po, qs, opts.data]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelisihFilter() {
  return useContext(Ctx);
}

export function SelisihFilters({ testId = 'selisih-filter' }) {
  const f = useSelisihFilter();
  if (!f) return null;
  return (
    <>
      <PeriodPicker value={f.period} onChange={f.setPeriod} presets={[ALL_TIME, ...PERIOD_PRESETS]} testId={`${testId}-period`} />
      <SmartNativeSelect value={f.bt} onChange={(e) => f.setBt(e.target.value)} searchable={false} className="h-9 w-40"
        aria-label="Portal" data-testid={`${testId}-portal`}>
        <option value="internal">PO internal</option>
        <option value="maklon">PO maklon</option>
      </SmartNativeSelect>
      <SmartNativeSelect value={f.vendor} onChange={(e) => { f.setVendor(e.target.value); f.setPo(''); }} className="h-9 w-48"
        aria-label="Vendor CMT" data-testid={`${testId}-vendor`}>
        <option value="">Semua vendor</option>
        {f.vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
      </SmartNativeSelect>
      <SmartNativeSelect value={f.po} onChange={(e) => f.setPo(e.target.value)} className="h-9 w-48"
        aria-label="PO" data-testid={`${testId}-po`}>
        <option value="">Semua PO</option>
        {f.pos.filter((p) => !f.vendor || p.vendor_id === f.vendor)
          .map((p) => <option key={p.id} value={p.id}>{p.po_number}</option>)}
      </SmartNativeSelect>
    </>
  );
}
