// Backup/Restore — pembantu unduh & unggah berkas.
//
// KENAPA BERUBAH (2026-08-01, laporan owner "tidak bisa download, upload bermasalah"):
//  1. UNDUH: dulu fetch → Blob → <a download>. Preview aplikasi berjalan di dalam
//     IFRAME dan Chrome MEMBLOKIR unduhan dari iframe tanpa izin `allow-downloads`
//     (tanpa error apa pun) — user melihat toast "Sukses" tapi tidak ada berkas.
//     Selain itu `revokeObjectURL` dipanggil serentak setelah `click()` sehingga
//     unduhan bisa dibatalkan sebelum terbaca.
//     SEKARANG: minta TIKET sekali-pakai ke backend, lalu buka URL biasa di TAB
//     BARU (navigasi normal → selalu diizinkan). URL-nya juga dikembalikan agar
//     UI bisa menampilkan tautan manual sebagai jalan terakhir.
//  2. UNGGAH: tanpa progress & seluruh berkas dibaca ke memori. SEKARANG memakai
//     XHR (ada progress) untuk berkas ≤ 8 MB dan unggah BERPOTONG 5 MB untuk yang
//     lebih besar (lolos batas badan-permintaan proxy, aman untuk RAM 2 GB).

const BACKEND = process.env.REACT_APP_BACKEND_URL || '';
const API = `${BACKEND}/api/admin/backup`;
const CHUNK_THRESHOLD = 8 * 1024 * 1024; // > 8 MB → unggah berpotong
const CHUNK_SIZE = 5 * 1024 * 1024;      // 5 MB per potongan

/** Ubah `detail` dari FastAPI (string ATAU objek {message,reason,hint}) jadi teks. */
export const describeError = (detail, fallback = 'Terjadi kesalahan') => {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg || JSON.stringify(d)).join('; ');
  const parts = [detail.message, detail.reason, detail.hint ? `Saran: ${detail.hint}` : null];
  const text = parts.filter(Boolean).join(' — ');
  return text || fallback;
};

const readError = async (response, fallback) => {
  try {
    const body = await response.json();
    return describeError(body?.detail ?? body, fallback);
  } catch {
    return `${fallback} (HTTP ${response.status})`;
  }
};

/**
 * Unduh backup sebagai ZIP.
 * Mengembalikan { ok, url, method, error }.
 *  - method 'tab'  : tab baru dibuka (unduhan berjalan di sana)
 *  - method 'blob' : fallback unduhan langsung di halaman ini
 * `url` selalu diisi saat tiket berhasil dibuat, supaya UI bisa menampilkan
 * tautan "klik untuk unduh" bila browser memblokir otomatisasi.
 */
export const downloadBackup = async (backupId, token) => {
  let url = null;
  try {
    const ticketRes = await fetch(`${API}/download-ticket/${encodeURIComponent(backupId)}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });

    if (ticketRes.ok) {
      const data = await ticketRes.json();
      url = `${BACKEND}${data.url}`;
      // Navigasi normal di tab baru — tidak terkena blokir unduhan iframe.
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener';
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => a.remove(), 0);
      return { ok: true, url, method: 'tab' };
    }

    // Tiket gagal (mis. versi backend lama) → fallback cara lama, tapi dengan
    // revoke yang DITUNDA agar unduhan tidak dibatalkan browser.
    const response = await fetch(`${API}/download/${encodeURIComponent(backupId)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error(await readError(response, 'Unduhan gagal'));

    const blob = await response.blob();
    if (!blob || blob.size === 0) throw new Error('Berkas backup kosong (0 byte)');

    const blobUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = `${backupId}.zip`;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      window.URL.revokeObjectURL(blobUrl);
      a.remove();
    }, 4000);
    return { ok: true, url: null, method: 'blob' };
  } catch (e) {
    return { ok: false, url, error: e.message };
  }
};

/** XHR dengan progress (dipakai untuk unggah satu-permintaan & per potongan). */
const xhrPost = (path, formData, token, onProgress) =>
  new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API}${path}`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    if (onProgress) {
      xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable) onProgress(evt.loaded, evt.total);
      };
    }
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* biarkan null */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body || {});
      else reject(new Error(describeError(body?.detail ?? body, `Gagal (kode ${xhr.status})`)));
    };
    xhr.onerror = () => reject(new Error('Koneksi terputus saat mengunggah'));
    xhr.ontimeout = () => reject(new Error('Unggahan melewati batas waktu'));
    xhr.send(formData);
  });

/**
 * Unggah berkas ZIP backup.
 * @param {File} file
 * @param {string} token
 * @param {(percent:number, info:string)=>void} onProgress
 */
export const uploadBackup = async (file, token, onProgress = () => {}) => {
  try {
    if (!file) throw new Error('Belum ada berkas yang dipilih');
    if (!/\.zip$/i.test(file.name)) {
      throw new Error('Format tidak didukung — pilih berkas .zip hasil backup database');
    }
    if (file.size === 0) throw new Error('Berkas kosong (0 byte)');

    // Berkas kecil: satu permintaan (paling cepat).
    if (file.size <= CHUNK_THRESHOLD) {
      const fd = new FormData();
      fd.append('file', file);
      const result = await xhrPost('/upload-file', fd, token, (loaded, total) => {
        onProgress(Math.round((loaded / total) * 100), 'mengunggah');
      });
      onProgress(100, 'selesai');
      return { ok: true, ...result };
    }

    // Berkas besar: potong 5 MB agar lolos batas proxy & hemat memori server.
    const initRes = await fetch(`${API}/upload-init`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: file.name,
        total_size: file.size,
        total_chunks: Math.ceil(file.size / CHUNK_SIZE),
      }),
    });
    if (!initRes.ok) throw new Error(await readError(initRes, 'Gagal memulai unggahan'));
    const { upload_id: uploadId } = await initRes.json();

    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    for (let i = 0; i < totalChunks; i += 1) {
      const blob = file.slice(i * CHUNK_SIZE, Math.min((i + 1) * CHUNK_SIZE, file.size));
      const fd = new FormData();
      fd.append('upload_id', uploadId);
      fd.append('index', String(i));
      fd.append('file', blob, `${file.name}.part${i}`);
      await xhrPost('/upload-chunk', fd, token, (loaded) => {
        const done = i * CHUNK_SIZE + loaded;
        onProgress(Math.min(99, Math.round((done / file.size) * 100)),
          `potongan ${i + 1}/${totalChunks}`);
      });
    }

    const doneRes = await fetch(`${API}/upload-complete`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload_id: uploadId }),
    });
    if (!doneRes.ok) throw new Error(await readError(doneRes, 'Gagal menyelesaikan unggahan'));
    onProgress(100, 'selesai');
    return { ok: true, ...(await doneRes.json()) };
  } catch (e) {
    return { ok: false, error: e.message };
  }
};

export const listCollections = async (backupId, token) => {
  try {
    const response = await fetch(`${API}/${encodeURIComponent(backupId)}/collections`, {
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    });
    if (!response.ok) throw new Error(await readError(response, 'Gagal membaca daftar koleksi'));
    return await response.json();
  } catch (e) {
    return { collections: [], error: e.message };
  }
};

export const restoreSelective = async (backupId, collections, mode, token) => {
  try {
    const response = await fetch(`${API}/restore-selective`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ backup_id: backupId, collections, mode, confirm: true }),
    });
    if (!response.ok) throw new Error(await readError(response, 'Pemulihan gagal'));
    return await response.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
};

// ── Nama tampilan koleksi (Standar UI/UX v2, 8 Nov 2026) ─────────────────────
// Nama koleksi (`rahaza_employees`) adalah istilah program; layar menampilkan terjemahan kata per kata
// ("Karyawan"). Nama asli tetap dipakai untuk memilih/mengosongkan dan ikut di berkas unduhan & keterangan arah kursor.
const KATA_KOLEKSI = {
  acc: 'aksesoris', accessories: 'aksesoris', accessory: 'aksesoris', account: 'akun', accounts: 'akun', accruals: 'akrual',
  activity: 'aktivitas', adjustments: 'penyesuaian', ads: 'iklan', advance: 'uang muka', ai: 'AI', alert: 'peringatan',
  allowances: 'tunjangan', announcements: 'pengumuman', ap: 'utang', ar: 'piutang', asset: 'aset', assets: 'aset',
  assignments: 'penugasan', assistant: 'asisten', attachments: 'lampiran', attempts: 'percobaan', attendance: 'absensi',
  audit: 'audit', auto: 'otomatis', bank: 'bank', barcode: 'barcode', batches: 'batch', bom: 'BOM', boms: 'BOM',
  bridge: 'jembatan', buckets: 'kelompok', budgets: 'anggaran', buildings: 'gedung', buyer: 'pembeli', calendar: 'kalender',
  candidates: 'kandidat', cash: 'kas', catalog: 'katalog', catalogs: 'katalog', categories: 'kategori', category: 'kategori',
  centers: 'pusat', challenges: 'tantangan', change: 'perubahan', changes: 'perubahan', channel: 'kanal', channels: 'kanal',
  chat: 'obrolan', checklists: 'daftar periksa', checks: 'pemeriksaan', claims: 'klaim', client: 'klien', clients: 'klien',
  cmt: 'CMT', coa: 'COA', colors: 'warna', comm: 'komisi', company: 'perusahaan', complaints: 'keluhan', component: 'komponen',
  config: 'pengaturan', configs: 'pengaturan', consumptions: 'pemakaian', content: 'konten', controls: 'kontrol',
  conversations: 'percakapan', conversions: 'konversi', cost: 'biaya', costing: 'kalkulasi biaya', counters: 'penghitung',
  courses: 'kursus', creator: 'kreator', creators: 'kreator', credentials: 'kredensial', customers: 'pelanggan', cutting: 'potong',
  da: '', data: 'data', delivery: 'pengiriman', depr: 'penyusutan', devices: 'perangkat', dewi: '', discounts: 'diskon',
  dispatches: 'pengiriman', doc: 'dokumen', documents: 'dokumen', downtime: 'waktu henti', employee: 'karyawan',
  employees: 'karyawan', enrollments: 'pendaftaran', entries: 'entri', events: 'peristiwa', expense: 'biaya', expenses: 'biaya',
  fabric: 'kain', fg: 'barang jadi', fixed: 'tetap', flashsales: 'flash sale', formats: 'format', funds: 'dana', fx: 'kurs',
  gl: 'buku besar', grn: 'penerimaan', groups: 'grup', handover: 'serah terima', handovers: 'serah terima', health: 'kesehatan',
  history: 'riwayat', hpp: 'HPP', import: 'impor', incentive: 'insentif', inspection: 'inspeksi', inspections: 'inspeksi',
  inventory: 'persediaan', invoices: 'faktur', issues: 'pengeluaran', item: 'item', items: 'item', job: 'pekerjaan',
  jobs: 'pekerjaan', journal: 'jurnal', kasbon: 'kasbon', key: 'kunci', kol: 'KOL', kpi: 'KPI', kreator: 'kreator',
  launches: 'peluncuran', layers: 'lapisan', leave: 'cuti', ledger: 'buku', limit: 'batas', lines: 'baris', links: 'tautan',
  lists: 'daftar', live: 'live', livehost: 'live host', livehosts: 'live host', lms: 'LMS', locations: 'lokasi', locks: 'kunci',
  log: 'log', login: 'masuk', logs: 'log', machine: 'mesin', machines: 'mesin', maklon: 'maklon', mapping: 'pemetaan',
  marketing: 'marketing', master: 'induk', material: 'material', materials: 'material', messages: 'pesan', model: 'model',
  models: 'model', movements: 'mutasi', notes: 'catatan', notif: 'notifikasi', notifications: 'notifikasi', number: 'nomor',
  objectives: 'sasaran', okr: 'OKR', onboarding: 'orientasi', opname3: 'opname', options: 'opsi', orders: 'pesanan',
  org: 'organisasi', out: 'keluar', overtime: 'lembur', pack: 'paket', packs: 'paket', partners: 'mitra', payments: 'pembayaran',
  payroll: 'penggajian', payslips: 'slip gaji', pdf: 'PDF', pending: 'tertunda', perform: 'kinerja', period: 'periode',
  periods: 'periode', permak: 'permak', permissions: 'izin', petty: 'kas kecil', platform: 'platform', po: 'PO', portal: 'portal',
  pos: 'POS', positions: 'jabatan', posting: 'posting', price: 'harga', print: 'cetak', process: 'proses', processes: 'proses',
  procurement: 'pengadaan', product: 'produk', production: 'produksi', products: 'produk', profiles: 'profil', progress: 'progres',
  purchase: 'pembelian', push: 'push', qc: 'QC', quarantine: 'karantina', questions: 'pertanyaan', quick: 'cepat', racks: 'rak',
  rahaza: '', rate: 'tarif', rates: 'tarif', read: 'dibaca', receipt: 'penerimaan', receipts: 'penerimaan', receive: 'terima',
  receiving: 'penerimaan', records: 'catatan', recruitment: 'rekrutmen', rejects: 'tolakan', reminders: 'pengingat',
  reports: 'laporan', requests: 'permintaan', results: 'hasil', return: 'retur', returns: 'retur', revaluation: 'revaluasi',
  reviews: 'tinjauan', revisions: 'revisi', rnd: 'R&D', role: 'peran', roles: 'peran', roll: 'roll', rolls: 'roll', runs: 'proses',
  salary: 'gaji', sales: 'penjualan', sample: 'sampel', samples: 'sampel', scan: 'pindai', scheduler: 'penjadwal',
  schedules: 'jadwal', scripts: 'naskah', session: 'sesi', sessions: 'sesi', settings: 'pengaturan', settlements: 'penyelesaian',
  sheets: 'lembar', shift: 'shift', shifts: 'shift', shipment: 'pengiriman', shipments: 'pengiriman', short: 'kurang',
  sku: 'SKU', snapshots: 'potret', sop: 'SOP', stock: 'stok', study: 'studi', styles: 'gaya', submissions: 'kiriman',
  subscriptions: 'langganan', supplier: 'pemasok', suppliers: 'pemasok', syncs: 'sinkronisasi', system: 'sistem',
  targets: 'target', task: 'tugas', tasks: 'tugas', tech: 'teknis', templates: 'templat', toko: 'toko', training: 'pelatihan',
  transfers: 'transfer', travel: 'perjalanan dinas', txns: 'transaksi', types: 'jenis', undo: 'urungkan', unit: 'satuan',
  units: 'satuan', usage: 'pemakaian', users: 'pengguna', variances: 'selisih', variant: 'varian', variants: 'varian',
  vendor: 'vendor', warehouse: 'gudang', webauthn: 'sidik jari', webhook: 'webhook', weekly: 'mingguan', wh: 'gudang',
  wip: 'WIP', withdrawals: 'penarikan', work: 'kerja', zkteco: 'mesin absen', zones: 'zona',
};

export function labelKoleksi(nama) {
  const kata = String(nama || '').toLowerCase().split(/[_.-]+/).filter(Boolean)
    .map((w) => (w in KATA_KOLEKSI ? KATA_KOLEKSI[w] : w)).filter(Boolean);
  // kata yang sama berurutan (mis. "aksesoris aksesoris") cukup sekali
  const unik = kata.filter((w, i) => w !== kata[i - 1]);
  const s = unik.join(' ').trim() || String(nama || '');
  return s.charAt(0).toUpperCase() + s.slice(1);
}
