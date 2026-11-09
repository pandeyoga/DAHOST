import csv, io, sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from core.settlement_import import parse_settlement_report, guess_platform

# Shopee "Penghasilan Saya" style
shopee_rows = [
    ["No. Pesanan", "Tanggal Dana Dilepaskan", "Waktu Pesanan Dibuat", "Harga Asli Produk", "Total Diskon Produk",
     "Voucher Ditanggung Penjual", "Biaya Administrasi", "Biaya Layanan", "Biaya Komisi AMS", "Pengembalian Dana ke Pembeli",
     "Ongkos Kirim Dibayar Pembeli", "Total Penghasilan", "Persentase Biaya Administrasi"],
    ["2608A1", "2026-08-15", "2026-08-02 10:00", "1.000.000", "-50.000", "-20.000", "-45.000", "-15.000", "-10.000", "0", "12.000", "860.000", "4,5%"],
    ["2608A2", "2026-08-15", "2026-08-05 12:00", "2.000.000", "-100.000", "0", "-90.000", "-30.000", "0", "-200.000", "15.000", "1.580.000", "4,5%"],
]
buf = io.StringIO(); w = csv.writer(buf, delimiter=';'); w.writerows(shopee_rows)
raw = buf.getvalue().encode('utf-8-sig')
# sampel Shopee sintetis tetap (bentuk asli = xlsx multi-sheet, lihat test_tahap2_marketing)
r = parse_settlement_report(raw, 'settlement_shopee_contoh.csv')
print('SHOPEE', guess_platform(r['headers']))
print(r['values']); print(r['mapping']); print(r['settlement_date'], r['period_from'], r['period_to']); print('unmapped', r['unmapped_numeric_columns'])
assert r['values']['gross_sales'] == 3000000 and r['values']['refunds'] == 200000 and r['values']['net_payout'] == 2440000
assert r['values']['seller_discount'] == 170000 and r['values']['platform_commission'] == 135000
assert r['values']['affiliate_commission'] == 10000 and r['values']['platform_service_fee'] == 45000
assert 'No. Pesanan' not in r['unmapped_numeric_columns'] and 'Persentase Biaya Administrasi' not in r['unmapped_numeric_columns']

# TikTok laporan penghasilan (xlsx) — 2026-11-09 (riset G8): HEADER NYATA ekspor TikTok
# (versi Inggris non-AS, peta header dari parser publik ekspor asli) + angka sintetis yang
# konsisten dengan definisi TikTok: Total revenue = Subtotal after seller discounts −
# Refund subtotal after seller discounts. Sampel lama memakai rumus karangan ("Total
# revenue" sebelum diskon penjual + kolom "Seller discount") yang membuat uji hijau
# mengunci perilaku keliru.
import openpyxl
from pathlib import Path
SAMPLES = Path(__file__).resolve().parents[2] / "samples"
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Order details"
ws.append(["Order/adjustment ID", "Type", "Order created time", "Order settled time", "Currency",
           "Total settlement amount", "Total revenue", "Subtotal after seller discounts",
           "Refund subtotal after seller discounts", "Total fees", "TikTok Shop commission fee",
           "Dynamic commission", "Order processing fee", "Affiliate commission", "Shipping cost",
           "Article 22 Income Tax withheld", "Adjustment amount", "Related order ID"])
ws.append(["DEMO-T1", "Order", "03/08/2026", "16/08/2026", "IDR", 4_610_000, 5_000_000, 5_000_000, 0,
           -390_000, -250_000, -100_000, -1_250, -15_000, -20_000, -3_750, 0, ""])
ws.append(["DEMO-T2", "Order", "09/08/2026", "16/08/2026", "IDR", 1_679_000, 1_900_000, 2_000_000, -100_000,
           -151_000, -100_000, -38_000, -1_250, 0, -10_000, -1_750, -70_000, ""])
ws.append(["DEMO-T3", "Adjustment", "", "16/08/2026", "IDR", -50_000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
           -50_000, "DEMO-T1"])
b = io.BytesIO(); wb.save(b); raw2 = b.getvalue()
(SAMPLES / "settlement_tiktok_contoh.xlsx").write_bytes(raw2)
r2 = parse_settlement_report(raw2, 'settlement_tiktok_contoh.xlsx')
print('TIKTOK', guess_platform(r2['headers']))
print(r2['values']); print(r2['mapping']); print(r2['settlement_date'], r2['period_from'], r2['period_to'])
v = r2['values']
assert v['gross_sales'] == 7_000_000 and v['seller_discount'] == 0 and v['refunds'] == 100_000
assert v['platform_commission'] == 488_000 and v['platform_service_fee'] == 2_500
assert v['affiliate_commission'] == 15_000 and v['other_deductions'] == 35_500
assert v['adjustments'] == -120_000 and v["net_payout"] == 6_239_000
assert r2['invariant']['lolos'] == r2['invariant']['diuji'] == 3
print('OK')
