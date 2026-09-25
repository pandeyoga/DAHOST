from common import *
seed()
print('='*78); print('T1  REKAP KEUANGAN (/api/financial-recap) vs data yang ditulis modul resmi'); print('='*78)
today = __import__('datetime').date.today().isoformat()
# AR: invoice 10.000.000 (tanpa pajak), kirim, bayar 4.000.000 ke BCA
r = post('/api/rahaza/ar-invoices', 'accounting', {'customer_id':'C1','issue_date':today,'due_date':today,
         'items':[{'description':'Kaos','qty':100,'unit_price':100000}]})
print('  buat AR', r.status_code); ar = r.json()
r = post(f"/api/rahaza/ar-invoices/{ar['id']}/send", 'accounting'); print('  kirim AR', r.status_code, r.json().get('status'))
r = post(f"/api/rahaza/ar-invoices/{ar['id']}/payment", 'accounting', {'amount':4000000,'account_id':'CA1','date':today})
print('  bayar AR', r.status_code, r.json().get('status'), 'sisa', r.json().get('balance'))
# AR kedua: DRAFT 5.000.000 (belum dikirim) -> seharusnya bukan penjualan
r = post('/api/rahaza/ar-invoices', 'accounting', {'customer_id':'C1','issue_date':today,'due_date':today,
         'items':[{'description':'Draft','qty':50,'unit_price':100000}]}); print('  buat AR draft', r.status_code)
# AP: 6.000.000, kirim, bayar 1.000.000
r = post('/api/rahaza/ap-invoices', 'accounting', {'vendor_name':'CV Kain','issue_date':today,'due_date':today,
         'items':[{'description':'Kain','qty':60,'unit_price':100000}]}); ap = r.json(); print('  buat AP', r.status_code)
r = post(f"/api/rahaza/ap-invoices/{ap['id']}/send", 'accounting'); print('  kirim AP', r.status_code, r.json().get('status'))
r = post(f"/api/rahaza/ap-invoices/{ap['id']}/payment", 'accounting', {'amount':1000000,'account_id':'CA1','date':today})
print('  bayar AP', r.status_code, r.json().get('status'), 'sisa', r.json().get('balance'))

# kebenaran menurut dokumen sumber
ars = H.run(H.DB.rahaza_ar_invoices.find({},{'_id':0}).to_list(None))
aps = H.run(H.DB.rahaza_ap_invoices.find({},{'_id':0}).to_list(None))
pays = H.run(H.DB.rahaza_ar_payments.find({},{'_id':0}).to_list(None))
print('  field pembayaran yang ditulis:', sorted(pays[0].keys()))
print('  field AP yang ditulis        :', [k for k in ('total','total_amount','balance','outstanding_amount') if k in aps[0]])
print('  status AR yang ditulis       :', sorted({a['status'] for a in ars}))

r = H.client.get(f'/api/financial-recap?date_from={today}&date_to={today}', headers=H.tok('accounting'))
d = r.json(); print('\n  respons rekap', r.status_code)
chk('Penjualan (AR terbit, draft tidak dihitung)', d['total_sales_value'], 10000000)
chk('Biaya vendor (AP 6 jt)',                      d['total_vendor_cost'], 6000000)
chk('Kas masuk (bayar AR 4 jt)',                   d['total_cash_in'], 4000000)
chk('Kas keluar (bayar AP 1 jt)',                  d['total_cash_out'], 1000000)
chk('Piutang beredar (10 − 4 = 6 jt)',             d['accounts_receivable_outstanding'], 6000000)
chk('Hutang beredar (6 − 1 = 5 jt)',               d['accounts_payable_outstanding'], 5000000)
chk('Margin kotor % (10−6)/10',                    d['gross_margin_pct'], 40.0, tol=0.05)
print('\n  hasil:', sum(R), 'lulus dari', len(R))
