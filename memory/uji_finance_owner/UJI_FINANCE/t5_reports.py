from common import *
seed()
import datetime
today = datetime.date.today(); T = today.isoformat(); P = T[:7]
print('='*78); print('T5  ANGGARAN, AGING PIUTANG 360, LAPORAN EKSEKUTIF, PREDIKSI KAS, DISKON PEMBELIAN'); print('='*78)
acc = {c['code']: c['id'] for c in H.run(H.DB.rahaza_coa_accounts.find({},{'_id':0,'code':1,'id':1}).to_list(None))}
# --- anggaran vs realisasi
r = post('/api/rahaza/finance/budgets','accounting',{'name':'Anggaran Operasional','year':today.year}); bid = r.json().get('id') or (r.json().get('budget') or {}).get('id')
r = post(f'/api/rahaza/finance/budgets/{bid}/items','accounting',{'account_id':acc['6-2900'],'month':P,'amount_budgeted':5000000})
print('  item anggaran 6-2900 bulan', P, '=', 5_000_000, r.status_code)
r = post('/api/rahaza/journals','accounting',{'date':T,'description':'biaya lain','post':True,
      'lines':[{'account_code':'6-2900','debit':3000000,'credit':0},{'account_code':'1-1201','debit':0,'credit':3000000}]})
print('  jurnal biaya 3 jt ke 6-2900 ->', r.status_code, '| saldo GL 6-2900 =', jl_sum('6-2900'))
v = H.client.get(f'/api/rahaza/finance/budgets/{bid}/variance', headers=H.tok('accounting')).json()
row = (v.get('rows') or [{}])[0]
chk('realisasi anggaran = 3 jt (dari buku besar)', float(row.get('actual') or row.get('actual_amount') or 0), 3000000)

# --- AR: satu terbit, satu draft, satu dihapus-buku
def mk_ar(amount, send=True):
    r = post('/api/rahaza/ar-invoices','accounting',{'customer_id':'C1','issue_date':T,'due_date':T,'items':[{'description':'x','qty':1,'unit_price':amount}]}); i=r.json()
    if send: post(f"/api/rahaza/ar-invoices/{i['id']}/send",'accounting')
    return i['id']
a_open = mk_ar(4_000_000); a_draft = mk_ar(2_000_000, send=False); a_wo = mk_ar(1_000_000)
r = post(f'/api/rahaza/ar-invoices/{a_wo}/write-off-bad-debt','accounting',{'write_off_date':T,'reason':'pelanggan tutup usaha, tidak tertagih'})
print('\n  hapus buku AR 1 jt ->', r.status_code)
a_part = mk_ar(3_000_000); post(f'/api/rahaza/ar-invoices/{a_part}/payment','accounting',{'amount':1_000_000,'account_id':'CA1','date':T})
print('  AR: terbit 4 jt | draft 2 jt | dihapus-buku 1 jt | terbit 3 jt dibayar 1 jt  -> piutang sebenarnya = 4 (terbit) + 2 (sisa invoice 3 jt) = 6 jt')
d = H.client.get('/api/rahaza/ar-360/dashboard', headers=H.tok('accounting')).json()
tot = d.get('total_outstanding') or (d.get('summary') or {}).get('total_outstanding') or (d.get('kpis') or {}).get('total_outstanding')
print('  ar-360/dashboard kunci:', list(d.keys())[:10])
chk('AR 360: total piutang = 6 jt (tanpa draft & tanpa yang dihapus buku)', float(tot or 0), 6_000_000)

fs = H.client.get(f'/api/reports/executive/finance-snapshot?year={today.year}&month={today.month}', headers=H.tok('accounting')).json()['current']
print('\n  Laporan Eksekutif bulan ini:', {k: fs.get(k) for k in ('revenue_rp','paid_revenue_rp','ar_overdue_rp')})
chk('Laporan Eksekutif: pendapatan bulan ini = 4 + 1 + 3 = 8 jt (terbit)', fs.get('revenue_rp'), 8_000_000)
from routes.dewi_cashflow_ai import _build_context
ctx = H.run(_build_context(H.DB))
print('  konteks Prediksi Kas:', {k: ctx.get(k) for k in list(ctx)[:6]})
ar_ctx = ctx.get('total_ar') or (ctx.get('ar') or {}).get('total') or (ctx.get('ar_aging') or {}).get('total')
chk('Prediksi Kas: total piutang dibaca = 6 jt', float(ar_ctx or 0), 6_000_000)

# --- diskon pembelian
r = post('/api/rahaza/ap-invoices','accounting',{'vendor_name':'CV Benang','issue_date':T,'due_date':T,'items':[{'description':'benang','qty':1,'unit_price':10_000_000}]}); ap=r.json()
post(f"/api/rahaza/ap-invoices/{ap['id']}/send",'accounting')
r = post(f"/api/rahaza/ap-invoices/{ap['id']}/payment",'accounting',{'amount':9_800_000,'discount_amount':200_000,'account_id':'CA1','date':T})
x = r.json(); print('\n  bayar AP 10 jt dengan diskon 2% (bayar 9,8 jt + diskon 200 rb) ->', r.status_code, x.get('status'), 'sisa', x.get('balance'))
chk('invoice AP lunas setelah bayar + diskon', x.get('status'), 'paid')
chk('diskon pembelian tercatat di GL', H.run(H.DB.rahaza_journal_lines.count_documents({'description':{'$regex':'iskon|iscount'}}))>0, True)
print('\n  hasil:', sum(R), 'lulus dari', len(R))
