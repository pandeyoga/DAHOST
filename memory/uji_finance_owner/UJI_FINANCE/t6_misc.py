from common import *
seed()
import datetime, json
from dateutil.relativedelta import relativedelta
today = datetime.date.today(); T = today.isoformat(); P = T[:7]
print('='*78); print('T6  PERJALANAN DINAS, AKRUAL BERULANG, EDIT INVOICE AP, VOID TRANSFER, ANGKA TAK HINGGA'); print('='*78)

# 6a — settlement atas uang muka yang BELUM dibayar
H.run(H.DB.employee_travel_requests.insert_one({'id':'TR1','trip_number':'TRV-01','employee_id':'u-staff','employee_name':'Andi','status':'approved',
     'destination':'Bandung','total_budget':2_000_000,'cash_advance_approved':2_000_000,'cash_advance_paid':0}))
r = H.client.post('/api/hr/expenses/travel/TR1/settlements', headers=H.tok('staff','u-staff'),
     json={'actual_items':[{'date':T,'category':'Transportasi','amount':1_500_000}]})
s = r.json(); print('  uang muka disetujui 2 jt, BELUM dibayar; karyawan belanja 1,5 jt pakai uang sendiri ->', r.status_code)
print('   ', {k: s.get(k) for k in ('advance_received','total_actual','difference','settlement_type')})
chk('jenis penyelesaian = kurang bayar (perusahaan berutang 1,5 jt ke karyawan)', s.get('settlement_type'), 'additional')

# 6b — akrual berulang menggandakan diri
def mk_acc(per):
    r = post('/api/rahaza/finance/accruals','accounting',{'period':per,'accrual_type':'utility','description':'Listrik bulanan','amount':1_000_000,
             'expense_account':'6-2900','accrued_account':'2-1600','is_recurring':True}); return r.json()['id']
m1 = (today - relativedelta(months=2)).strftime('%Y-%m'); m2 = (today - relativedelta(months=1)).strftime('%Y-%m')
a1 = mk_acc(m1); post(f'/api/rahaza/finance/accruals/{a1}/post','accounting')
post('/api/rahaza/finance/accruals/create-recurring','accounting',{'target_period':m2})
c2 = H.run(H.DB.rahaza_accruals.find_one({'period':m2},{'_id':0,'id':1}))
H.run(H.DB.rahaza_accruals.update_one({'id':c2['id']},{'$set':{'status':'posted'}}))  # anggap bulan lalu sudah diposting
r = post('/api/rahaza/finance/accruals/create-recurring','accounting',{'target_period':P})
n = H.run(H.DB.rahaza_accruals.count_documents({'period':P,'description':'Listrik bulanan'}))
print(f'\n  akrual berulang "Listrik bulanan": template {m1} → anak {m2} (posted) → buat untuk {P}: {n} draf')
chk('bulan ini hanya 1 draf akrual listrik', n, 1)

# 6c — edit total invoice AP yang sudah dijurnal
r = post('/api/rahaza/ap-invoices','accounting',{'vendor_name':'CV Kancing','issue_date':T,'due_date':T,'tax_pct':11,
         'items':[{'description':'kancing','qty':1,'unit_price':1_000_000}]}); ap = r.json()
post(f"/api/rahaza/ap-invoices/{ap['id']}/send",'accounting')
H.run(__import__('routes.rahaza_posting', fromlist=['x']).post_ap_invoice(H.DB, H.run(H.DB.rahaza_ap_invoices.find_one({'id':ap['id']},{'_id':0})), {'id':'u','name':'acc'}))
inv = H.run(H.DB.rahaza_ap_invoices.find_one({'id':ap['id']},{'_id':0,'gl_je_id':1,'total':1}))
print('\n  AP 1 jt + PPN 11% = ', inv['total'], '| jurnal:', bool(inv.get('gl_je_id')))
r = post('/api/invoice-edit-requests','accounting',{'target_collection':'rahaza_ap_invoices','target_invoice_id':ap['id'],'invoice_number':ap.get('invoice_number'),
         'invoice_category':'VENDOR','reason':'koreksi harga','after_snapshot':{'total_amount':1_332_000}})
rid = r.json().get('id') or (r.json().get('request') or {}).get('id')
r = H.client.put(f'/api/invoice-edit-requests/{rid}/approve', headers=H.tok('superadmin'), json={'approval_notes':'ok'})
print('  setujui edit total → 1.332.000 ->', r.status_code, str(r.json())[:90])
inv2 = H.run(H.DB.rahaza_ap_invoices.find_one({'id':ap['id']},{'_id':0,'gl_je_id':1,'total':1,'post_error':1,'gl_error':1}))
active = H.run(H.DB.rahaza_journal_entries.count_documents({'source_module':'ap_invoice','status':'posted'}))
print('  setelah disetujui:', inv2, '| jurnal AP aktif:', active)
chk('invoice AP masih punya jurnal aktif setelah edit disetujui', active, 1)

# 6d — void transfer yang tidak pernah terjurnal (posting gagal karena periode transfer sudah ditutup)
lm = (today.replace(day=1) - relativedelta(days=1))
H.run(H.DB.rahaza_periods.update_many({'period_code': lm.strftime('%Y-%m')}, {'$set':{'status':'closed'}}, upsert=True))
r = post('/api/finance/bank-transfers','accounting',{'from_account_code':'1-1201','to_account_code':'1-1202','amount':5_000_000,'transfer_date':lm.isoformat(),'memo':'susulan bulan lalu'})
t = r.json(); tid = t.get('id') or (t.get('transfer') or {}).get('id')
tf = H.run(H.DB.rahaza_bank_transfers.find_one({'id':tid},{'_id':0,'status':1,'gl_posted':1,'gl_error':1}))
print('\n  transfer 5 jt BCA→Mandiri bertanggal periode yang sudah ditutup ->', r.status_code, '| dokumen:', tf)
b0 = (jl_sum('1-1201'), jl_sum('1-1202'))
r = post(f'/api/finance/bank-transfers/{tid}/void','accounting'); b1 = (jl_sum('1-1201'), jl_sum('1-1202'))
print('  void ->', r.status_code, str(r.json())[:80], f'| GL (1-1201, 1-1202) sebelum {b0} sesudah {b1}')
chk('void transfer yang belum terjurnal tidak menulis apa pun ke GL', b1, b0)

# 6e — angka tak hingga
r = H.client.post('/api/rahaza/journals', headers={**H.tok('accounting'),'Content-Type':'application/json'},
     content='{"date":"%s","description":"x","post":true,"lines":[{"account_code":"6-2900","debit":1e999,"credit":0},{"account_code":"1-1201","debit":0,"credit":1e999}]}' % T)
print('\n  jurnal dengan debit/kredit 1e999 ->', r.status_code, '| tersimpan & posted:', H.run(H.DB.rahaza_journal_entries.count_documents({'description':'x','status':'posted'})))
tb = H.client.get('/api/rahaza/finance/reports/trial-balance', headers=H.tok('accounting'))
print('  lalu neraca saldo ->', tb.status_code)
chk('jurnal bernilai tak hingga ditolak', r.status_code in (400,422), True)
print('\n  hasil:', sum(R), 'lulus dari', len(R))
