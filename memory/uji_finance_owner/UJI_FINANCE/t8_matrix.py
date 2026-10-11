from common import *
seed()
import datetime; T = datetime.date.today().isoformat(); P = T[:7]
# siapkan dokumen supaya hanya pemeriksaan PERAN yang menentukan hasil
r = post('/api/rahaza/ar-invoices','superadmin',{'customer_id':'C1','issue_date':T,'due_date':T,'items':[{'description':'x','qty':1,'unit_price':1000000}]}); ar=r.json()['id']; post(f'/api/rahaza/ar-invoices/{ar}/send','superadmin')
r = post('/api/rahaza/ap-invoices','superadmin',{'vendor_name':'V','issue_date':T,'due_date':T,'items':[{'description':'x','qty':1,'unit_price':1000000}]}); ap=r.json()['id']; post(f'/api/rahaza/ap-invoices/{ap}/send','superadmin')
H.run(H.DB.employee_travel_settlements.insert_one({'id':'S1','settlement_number':'STL-1','status':'approved','advance_received':0,'total_actual':100000,'difference':-100000,'settlement_type':'additional','employee_name':'A','actual_items':[{'date':T,'category':'Transportasi','amount':100000}]}))
H.run(H.DB.rahaza_expense_claims.insert_one({'id':'K1','claim_number':'CLM-1','status':'approved','total_amount':100000,'employee_id':'E1','employee_name':'Budi','items':[]}))
JE = {'date':T,'description':'uji','post':True,'lines':[{'account_code':'6-2900','debit':1000,'credit':0},{'account_code':'1-1201','debit':0,'credit':1000}]}
acts = [
 ('Jurnal Umum: simpan & posting', 'post', '/api/rahaza/journals', JE),
 ('Terima pembayaran piutang (AR)', 'post', f'/api/rahaza/ar-invoices/{ar}/payment', {'amount':1000,'account_id':'CA1','date':T}),
 ('Bayar hutang (AP)', 'post', f'/api/rahaza/ap-invoices/{ap}/payment', {'amount':1000,'account_id':'CA1','date':T}),
 ('Tambah rekening kas/bank', 'post', '/api/rahaza/cash-accounts', {'name':'Kas Toko','type':'cash','gl_account_code':'1-1102'}),
 ('Pengeluaran umum', 'post', '/api/rahaza/expenses', {'amount':1000,'date':T,'description':'uji'}),
 ('Kas Kecil: buat dana', 'post', '/api/finance/petty-cash/funds', {'name':'KK','opening_balance':0}),
 ('Transfer Bank', 'post', '/api/finance/bank-transfers', {'from_account_code':'1-1201','to_account_code':'1-1202','amount':1000,'transfer_date':T}),
 ('Perjalanan Dinas: Post GL', 'post', '/api/hr/expenses/settlements/S1/post', {}),
 ('Klaim karyawan: Bayar & Post GL', 'post', '/api/hr/expenses/claims/K1/disburse', {}),
 ('Tutup periode', 'post', f'/api/rahaza/periods/{P}/close', {}),
]
roles = ['accounting','staff_keuangan','manager_keuangan']
print('='*96); print('T8  PERAN RESMI PORTAL FINANCE vs PINTU-PINTU UTAMANYA  (403 = ditolak karena peran)'); print('='*96)
print(f"  {'Tindakan':38s}" + ''.join(f'{r:>19s}' for r in roles))
tab = []
for label, m, path, body in acts:
    row = []
    for role in roles:
        rr = post(path, role, body)
        row.append(rr.status_code)
    tab.append((label,row))
    print(f"  {label:38s}" + ''.join(f"{('DITOLAK 403' if c==403 else 'boleh ('+str(c)+')'):>19s}" for c in row))
import json; json.dump(tab, open('/tmp/claude-0/fin/matrix.json','w'))
den = {r: sum(1 for _,row in tab if row[i]==403) for i,r in enumerate(roles)}
print('\n  jumlah pintu yang MENOLAK peran portalnya sendiri:', den, 'dari', len(acts))
