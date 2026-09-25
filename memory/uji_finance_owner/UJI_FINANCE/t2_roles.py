from common import *
seed()
import datetime
today = datetime.date.today().isoformat(); per = today[:7]
print('='*78); print('T2  SIAPA BISA MENULIS KE BUKU BESAR'); print('='*78)
JE = {'date': today, 'description':'Uji jurnal manual', 'post': True,
      'lines':[{'account_code':'6-2900','debit':100000,'credit':0},{'account_code':'1-1201','debit':0,'credit':100000}]}
print('\n  A. Pintu RESMI Jurnal Umum (POST /api/rahaza/journals, post=true)')
res = {}
for role in ['accounting','staff_keuangan','manager_keuangan','manager','operator','hr']:
    r = post('/api/rahaza/journals', role, JE); res[role]=r.status_code
    print(f"     {role:18s} -> HTTP {r.status_code}")
chk('accounting boleh', res['accounting'], 200)
chk('staff_keuangan (peran portal) boleh', res['staff_keuangan'], 200)
chk('manager_keuangan (peran portal) boleh', res['manager_keuangan'], 200)
chk('operator ditolak', res['operator'], 403)

print('\n  B. Pintu SAMPING yang juga menulis jurnal — dicoba sebagai OPERATOR produksi')
# B1 akrual
r = post('/api/rahaza/finance/accruals','operator',{'period':per,'accrual_type':'other','description':'akrual iseng','amount':2500000,
         'expense_account':'6-2900','accrued_account':'2-1600'}); print('     buat akrual', r.status_code, r.text[:90])
acc_id = (r.json() or {}).get('id') or ((r.json() or {}).get('accrual') or {}).get('id')
r2 = post(f'/api/rahaza/finance/accruals/{acc_id}/post','operator'); print('     posting akrual', r2.status_code, str(r2.json())[:140])
je = H.run(H.DB.rahaza_journal_entries.find_one({'source_module':{'$regex':'accrual'}},{'_id':0,'je_number':1,'created_by':1,'status':1}))
chk('operator BERHASIL memposting jurnal akrual (seharusnya ditolak)', bool(je and je.get('status')=='posted'), False)
# B2 kasbon atas nama rekan kerja, disetujui & dicairkan sendiri
r = post('/api/dewi/kasbon/requests','operator',{'employee_id':'E2','type':'kasbon','amount':3000000,'purpose':'uji','installment_count':1}, uid='E1')
print('     ajukan kasbon atas nama E2', r.status_code, str(r.json())[:100])
kid = ((r.json() or {}).get('request') or r.json() or {}).get('id')
r = H.client.patch(f'/api/dewi/kasbon/requests/{kid}/hr-review', headers=H.tok('operator','E1'), json={'action':'approve'}); print('     setujui sendiri (hr-review)', r.status_code)
r = H.client.patch(f'/api/dewi/kasbon/requests/{kid}/disburse', headers=H.tok('operator','E1'), json={}); print('     cairkan sendiri', r.status_code, str(r.json().get('gl'))[:120])
k = H.run(H.DB.dewi_kasbon_requests.find_one({'id':kid},{'_id':0,'employee_id':1,'employee_name':1,'status':1,'hr_reviewed_by':1,'disbursed_by':1}))
print('     dokumen kasbon:', k)
chk('operator bisa ajukan+setujui+cairkan kasbon orang lain (seharusnya tidak)', (k or {}).get('status')=='disbursed', False)
# B3 seed demo kasbon di sistem nyata
H.run(H.DB.dewi_kasbon_requests.delete_many({}))
r = post('/api/dewi/kasbon/seed','operator'); n = H.run(H.DB.dewi_kasbon_requests.count_documents({}))
print('     POST /api/dewi/kasbon/seed ->', r.status_code, '| dokumen kasbon tercipta:', n)
chk('endpoint seed demo tertutup di produksi', r.status_code in (403,404), True)
# B4 laporan keuangan dibaca operator
r = H.client.get(f'/api/rahaza/finance/reports/trial-balance', headers=H.tok('operator'))
if r.status_code == 404: r = H.client.get(f'/api/rahaza/trial-balance?from={per}-01&to={today}', headers=H.tok('operator'))
print('     neraca saldo dibaca operator ->', r.status_code)
chk('operator bisa membaca neraca saldo (seharusnya tidak)', r.status_code==200, False)
print('\n  hasil:', sum(R), 'lulus dari', len(R))
