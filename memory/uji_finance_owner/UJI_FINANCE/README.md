# Uji eksekusi Portal Keuangan (T1–T9)

Menjalankan `backend/server.py` DA37 ERP apa adanya (semua router, gerbang, middleware) di atas
basis data tiruan `mongomock_motor`, lalu memanggil endpoint dengan token JWT asli per peran.

## Menjalankan

```bash
pip install mongomock-motor email-validator apscheduler python-barcode   # + requirements.txt backend
export DAHOST_REPO=/path/ke/DAHOST          # bawaan: ~/DAHOST
python3 t1_recap.py      # Rekap Keuangan (FIN-01)
python3 t2_roles.py      # pintu samping & kasbon (FIN-03, FIN-04)
python3 t3_petty.py      # Kas Kecil (FIN-05)
python3 t4_assets.py     # Aset Tetap (FIN-06)
python3 t5_reports.py    # Anggaran, AR 360, Eksekutif, Prediksi Kas, Diskon (FIN-07/08/09)
python3 t6_misc.py       # Dinas, akrual berulang, edit invoice AP, void transfer (FIN-11..14)
python3 t7_inf.py        # nilai tak hingga (FIN-15)
python3 t8_matrix.py     # matriks peran portal (FIN-02)
python3 t9_control.py    # KONTROL POSITIF — harus 5/5 lulus
```

Setiap skrip mencetak `OK` / `GAGAL` per pemeriksaan. `GAGAL` pada T1–T8 = temuan masih ada.
Setelah perbaikan, pemeriksaan itu seharusnya berubah menjadi `OK` — jadikan uji regresi.

Paket `emergentintegrations` (AI) diganti modul tiruan kosong oleh `harness.py`.
Log hasil pada commit `4ce149a` ada di folder `log/`.
