/**
 * GrafikAsisten — grafik dari spesifikasi alat `tampilkan_grafik` (Kontrak B, Asisten AI Tahap A, 8 Nov 2026).
 *
 *   {"jenis": "batang"|"batang_horizontal"|"garis"|"area"|"pai", "judul": "…", "satuan": "Rp"|"pcs"|"%"|"…",
 *    "x": ["Shopee Daluna", …], "seri": [{"nama": "Omzet Nov", "nilai": [142300000, …]}, …], "catatan": "…"}
 *
 * Aturan tampilan (dataviz + PANDUAN_UI G7/G8):
 *   - warna hanya token `--chart-1..5` dengan urutan tetap (tidak diputar); "Lainnya" abu;
 *   - batang ≤ 24 px, ujung data membulat 4 px; garis 2 px; area = sapuan ~10%; garis bantu tipis padat;
 *   - teks (sumbu, legenda, tooltip) memakai warna teks, bukan warna seri; legenda bila ≥ 2 seri (pai: selalu);
 *   - angka gaya Indonesia (`lib/format`): sumbu ringkas "142 jt", tooltip penuh "Rp 142.300.000", "17,5%";
 *   - "Tampilkan angka" membuka tabel datanya (nilai tidak hanya bisa dibaca lewat hover);
 *   - spesifikasi kosong/tidak sah → pemberitahuan kecil, tidak pernah membuat layar galat.
 */
import { Component, useMemo, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatPercent } from '@/lib/format';
import { cn } from '@/lib/utils';
import { CHART_PALETTE } from '../dashboardAtoms';
import { irisanPai, pemformatSatuan, validasiSpec } from './grafikSpec';
import TabelAsisten from './TabelAsisten';

const TINTA = 'hsl(var(--muted-foreground))';
const GRID = 'var(--chart-grid, hsl(var(--border)))';
const keyOf = (i) => `s${i}`;
const potong = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function TooltipAsisten({ active, payload, label, penuh }) {
  if (!active || !payload?.length) return null;
  const judul = label ?? payload[0]?.payload?.x ?? payload[0]?.name;
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--glass-border)] bg-[var(--popover-surface)] px-3 py-2 shadow-[var(--shadow-soft)]">
      {judul !== undefined && <p className="mb-1 text-xs text-muted-foreground">{String(judul)}</p>}
      <div className="space-y-0.5">
        {payload.map((p) => (
          <div key={p.dataKey || p.name} className="flex items-center gap-2 text-xs">
            <span className="h-0.5 w-3 shrink-0 rounded-full" style={{ backgroundColor: p.color || p.payload?.fill }} />
            <span className="font-semibold tabular-nums text-foreground">{p.value === null || p.value === undefined ? '—' : penuh(p.value)}</span>
            {payload.length > 1 && <span className="text-muted-foreground">{p.name}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function Legenda({ item, garis }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="grafik-legenda">
      {item.map((it, i) => (
        <li key={`${i}-${it.nama}`} className="flex items-center gap-1.5 min-w-0">
          <span className={cn('shrink-0', garis ? 'h-0.5 w-3.5 rounded-full' : 'h-2.5 w-2.5 rounded-[2px]')} style={{ backgroundColor: it.warna }} />
          <span className="truncate text-foreground/80">{it.nama}</span>
        </li>
      ))}
    </ul>
  );
}

function sumbuNilai(fmt, satuanLabel, vertikal) {
  return {
    tick: { fontSize: 12, fill: TINTA },
    tickFormatter: fmt.sumbu,
    axisLine: false,
    tickLine: false,
    width: vertikal ? 56 : undefined,
    label: satuanLabel
      ? (vertikal
        ? { value: satuanLabel, angle: -90, position: 'insideLeft', offset: 4, style: { fontSize: 12, fill: TINTA, textAnchor: 'middle' } }
        : { value: satuanLabel, position: 'insideBottomRight', offset: -2, style: { fontSize: 12, fill: TINTA } })
      : undefined,
  };
}

function GrafikKartesius({ v, fmt, sempit }) {
  const data = useMemo(() => v.x.map((label, i) => {
    const row = { x: label };
    v.seri.forEach((s, si) => { row[keyOf(si)] = s.nilai[i]; });
    return row;
  }), [v]);
  const warna = (i) => CHART_PALETTE[i % CHART_PALETTE.length];
  const tooltip = <Tooltip content={<TooltipAsisten penuh={fmt.penuh} />} cursor={{ fill: 'hsl(var(--foreground) / 0.04)', stroke: GRID }} />;
  const grid = <CartesianGrid stroke={GRID} vertical={false} />;
  const kategori = {
    dataKey: 'x', tick: { fontSize: 12, fill: TINTA }, axisLine: { stroke: GRID }, tickLine: false,
    tickFormatter: (s) => potong(String(s), sempit ? 8 : 14), minTickGap: 4,
  };

  if (v.jenis === 'batang_horizontal') {
    const lebarLabel = Math.min(sempit ? 96 : 150, Math.max(48, Math.max(...v.x.map((s) => s.length)) * 6.5));
    const tinggi = Math.max(180, v.x.length * (v.seri.length > 1 ? 34 : 28) + 48);
    return (
      <ResponsiveContainer width="100%" height={tinggi}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 16, left: 4 }} barGap={2} barCategoryGap="22%">
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" {...sumbuNilai(fmt, fmt.label, false)} />
          <YAxis type="category" {...kategori} width={lebarLabel} interval={0}
            tickFormatter={(s) => potong(String(s), sempit ? 12 : 22)} axisLine={{ stroke: GRID }} />
          {tooltip}
          {v.seri.map((s, i) => (
            <Bar key={keyOf(i)} dataKey={keyOf(i)} name={s.nama} fill={warna(i)} radius={[0, 4, 4, 0]} maxBarSize={24} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // Layar sempit + >4 kategori: label dimiringkan supaya tidak bertumpuk (nama toko/produk panjang).
  const miring = sempit && v.x.length > 4;
  const tinggi = sempit ? (miring ? 260 : 220) : 260;
  const margin = { top: 8, right: 12, bottom: 4, left: 0 };
  const xAxis = (
    <XAxis {...kategori} interval={v.jenis === 'batang' && v.x.length <= (sempit ? 6 : 12) ? 0 : 'preserveStartEnd'}
      {...(miring ? { angle: -35, textAnchor: 'end', height: 64, tickFormatter: (s) => potong(String(s), 12) } : {})} />
  );
  const yAxis = <YAxis {...sumbuNilai(fmt, fmt.label, true)} />;

  if (v.jenis === 'batang') {
    return (
      <ResponsiveContainer width="100%" height={tinggi}>
        <BarChart data={data} margin={margin} barGap={2} barCategoryGap="22%">
          {grid}{xAxis}{yAxis}{tooltip}
          {v.seri.map((s, i) => (
            <Bar key={keyOf(i)} dataKey={keyOf(i)} name={s.nama} fill={warna(i)} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }
  const titik = v.x.length <= 12;
  if (v.jenis === 'area') {
    return (
      <ResponsiveContainer width="100%" height={tinggi}>
        <AreaChart data={data} margin={margin}>
          {grid}{xAxis}{yAxis}
          <Tooltip content={<TooltipAsisten penuh={fmt.penuh} />} cursor={{ stroke: TINTA, strokeWidth: 1 }} />
          {v.seri.map((s, i) => (
            <Area key={keyOf(i)} type="monotone" dataKey={keyOf(i)} name={s.nama} stroke={warna(i)} strokeWidth={2}
              fill={warna(i)} fillOpacity={0.1} connectNulls isAnimationActive={false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: 'hsl(var(--background))' }} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={tinggi}>
      <LineChart data={data} margin={margin}>
        {grid}{xAxis}{yAxis}
        <Tooltip content={<TooltipAsisten penuh={fmt.penuh} />} cursor={{ stroke: TINTA, strokeWidth: 1 }} />
        {v.seri.map((s, i) => (
          <Line key={keyOf(i)} type="monotone" dataKey={keyOf(i)} name={s.nama} stroke={warna(i)} strokeWidth={2}
            strokeLinecap="round" strokeLinejoin="round" connectNulls isAnimationActive={false}
            dot={titik ? { r: 4, strokeWidth: 2, stroke: 'hsl(var(--background))', fill: warna(i) } : false}
            activeDot={{ r: 5, strokeWidth: 2, stroke: 'hsl(var(--background))' }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function GrafikPai({ v, fmt, sempit }) {
  const irisan = useMemo(() => irisanPai(v), [v]);
  const total = irisan.reduce((s, r) => s + r.nilai, 0);
  if (!irisan.length) return <PemberitahuanGrafik alasan="tidak ada nilai positif untuk grafik pai" />;
  const penuh = (val) => `${fmt.penuh(val)} · ${formatPercent(total ? (val / total) * 100 : 0, 1)}`;
  return (
    <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-center">
      <div className="w-full sm:w-1/2" style={{ height: sempit ? 200 : 230 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Tooltip content={<TooltipAsisten penuh={penuh} />} />
            <Pie data={irisan} dataKey="nilai" nameKey="nama" innerRadius="55%" outerRadius="85%" paddingAngle={1}
              stroke="hsl(var(--background))" strokeWidth={2} isAnimationActive={false}>
              {irisan.map((r) => <Cell key={r.nama} fill={r.warna} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="w-full space-y-1.5 text-xs sm:w-1/2 sm:max-w-xs" data-testid="grafik-legenda">
        {irisan.map((r) => (
          <li key={r.nama} className="flex items-center gap-2 min-w-0">
            <span className="h-2.5 w-2.5 shrink-0 rounded-[2px]" style={{ backgroundColor: r.warna }} />
            <span className="min-w-0 flex-1 truncate text-foreground/80">{r.nama}</span>
            <span className="shrink-0 tabular-nums font-medium text-foreground">{formatPercent(total ? (r.nilai / total) * 100 : 0, 1)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PemberitahuanGrafik({ alasan }) {
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground" data-testid="grafik-tidak-sah">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[hsl(var(--warning))]" aria-hidden="true" />
      <span>Grafik tidak bisa ditampilkan{alasan ? ` (${alasan})` : ''}.</span>
    </p>
  );
}

/** Pagar: galat Recharts karena data aneh tidak boleh menjatuhkan seluruh percakapan. */
class PagarGrafik extends Component {
  constructor(props) { super(props); this.state = { galat: false }; }

  static getDerivedStateFromError() { return { galat: true }; }

  componentDidCatch() { /* sudah ditangani: tampilkan pemberitahuan */ }

  render() {
    return this.state.galat ? <PemberitahuanGrafik alasan="data grafik tidak sesuai" /> : this.props.children;
  }
}

function useSempit() {
  const [sempit] = useState(() => (typeof window !== 'undefined' ? window.innerWidth < 640 : false));
  return sempit;
}

export default function GrafikAsisten({ spec, testId = 'asisten-grafik' }) {
  const v = useMemo(() => validasiSpec(spec), [spec]);
  const [angka, setAngka] = useState(false);
  const sempit = useSempit();
  if (!v.ok) {
    return (
      <div className="rounded-[var(--radius-md)] border border-dashed border-[var(--glass-border)] px-3 py-2" data-testid={testId}>
        <PemberitahuanGrafik alasan={v.alasan} />
      </div>
    );
  }
  const fmt = pemformatSatuan(v.satuan);
  const legenda = v.jenis !== 'pai' && v.seri.length >= 2
    ? v.seri.map((s, i) => ({ nama: s.nama, warna: CHART_PALETTE[i % CHART_PALETTE.length] }))
    : null;
  return (
    <figure className="m-0 min-w-0 space-y-2 rounded-[var(--radius-md)] border border-[var(--glass-border)] p-3"
      data-testid={testId} data-jenis={v.jenis} aria-label={v.judul || 'Grafik'}>
      {(v.judul || legenda) && (
        <div className="space-y-1.5">
          {v.judul && <figcaption className="text-sm font-semibold text-foreground">{v.judul}</figcaption>}
          {legenda && <Legenda item={legenda} garis={v.jenis === 'garis'} />}
        </div>
      )}
      <PagarGrafik>
        {v.jenis === 'pai' ? <GrafikPai v={v} fmt={fmt} sempit={sempit} /> : <GrafikKartesius v={v} fmt={fmt} sempit={sempit} />}
      </PagarGrafik>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {v.catatan ? <p className="text-xs text-muted-foreground">{v.catatan}</p> : <span />}
        <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => setAngka((a) => !a)}
          aria-expanded={angka} data-testid={`${testId}-angka`}>
          {angka ? 'Sembunyikan angka' : 'Tampilkan angka'}
        </Button>
      </div>
      {angka && (
        <TabelAsisten
          kolom={[v.jenis === 'pai' ? 'Kategori' : 'Label', ...v.seri.map((s) => s.nama)]}
          baris={v.x.map((label, i) => [label, ...v.seri.map((s) => (s.nilai[i] === null ? '—' : fmt.penuh(s.nilai[i])))])}
          polos
          testId={`${testId}-tabel`}
        />
      )}
    </figure>
  );
}
