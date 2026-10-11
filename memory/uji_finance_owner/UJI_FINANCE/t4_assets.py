from common import *
seed()
import datetime
from dateutil.relativedelta import relativedelta
print('='*78); print('T4  ASET TETAP: posting depresiasi per baris, metode saldo menurun, pelepasan'); print('='*78)
acc = {c['code']: c['id'] for c in H.run(H.DB.rahaza_coa_accounts.find({},{'_id':0,'code':1,'id':1}).to_list(None))}
start = (datetime.date.today().replace(day=1) - relativedelta(months=6)).isoformat()
body = {'name':'Mesin Jahit Juki','category':'mesin','purchase_date':start,'purchase_cost':60000000,'residual_value':0,
        'useful_life_months':60,'depreciation_method':'straight_line',
        'account_id_asset':acc.get('1-2201') or acc.get('1-2200'),'account_id_accum_depr':acc.get('1-2501'),'account_id_depr_expense':acc.get('6-2700')}
r = post('/api/rahaza/finance/fixed-assets','operator',body); a = r.json(); aid = a.get('id') or (a.get('asset') or {}).get('id')
print('  buat aset oleh OPERATOR ->', r.status_code)
chk('operator ditolak mendaftarkan aset', r.status_code, 403)
p1 = start[:7]
r = post(f'/api/rahaza/finance/fixed-assets/{aid}/post-depr/{p1}','accounting')
print(f'  tombol "Posting" periode {p1} ->', r.status_code, r.json())
sch = H.run(H.DB.rahaza_depr_schedules.find_one({'asset_id':aid,'period':p1},{'_id':0}))
nje = H.run(H.DB.rahaza_journal_entries.count_documents({'source_module':{'$regex':'depr'}}))
chk('jadwal ditandai posted', bool(sch and sch.get('posted')), True)
chk('...dan ADA jurnalnya', nje>0 or bool((sch or {}).get('journal_entry_id')), True)
r = post('/api/rahaza/finance/fixed-assets/run-batch-depreciation','accounting',{'period':p1,'auto_post':True})
st = [x.get('status') for x in r.json().get('results',[])]
print(f'  batch periode {p1} ->', st)
chk('batch memperbaiki periode yang "posted" tanpa jurnal', 'already_posted' not in st, True)

from routes.rahaza_fixed_assets import _generate_schedule
ddb = _generate_schedule({'purchase_cost':60000000,'residual_value':0,'useful_life_months':60,'depreciation_method':'double_declining','purchase_date':'2026-01-15'})
yr1 = sum(x['depr_amount'] for x in ddb[:12]); rest = ddb[-1]['book_value_end']
print(f'\n  saldo menurun ganda, 60 bln, harga 60 jt: tahun-1 = {yr1:,.0f}; nilai buku akhir bulan ke-60 = {rest:,.0f}')
chk('depresiasi tahun pertama ≈ 40% (2/5 thn) × 60 jt ≈ 20–24 jt', 20_000_000 <= yr1 <= 24_500_000, True)
chk('nilai buku akhir masa manfaat mendekati residu (0)', rest < 6_000_000, True)

# pelepasan: aset lain, sudah terdepresiasi 6 bulan via batch
body2 = dict(body, name='Mesin Obras', account_id_asset=body['account_id_asset'])
r = post('/api/rahaza/finance/fixed-assets','accounting',body2); a2 = r.json().get('id') or (r.json().get('asset') or {}).get('id')
for i in range(6):
    per = (datetime.date.fromisoformat(start)+relativedelta(months=i)).strftime('%Y-%m')
    post('/api/rahaza/finance/fixed-assets/run-batch-depreciation','accounting',{'period':per,'asset_ids':[a2],'auto_post':True})
accum = jl_sum('1-2501')
print(f'\n  akumulasi depresiasi di GL untuk Mesin Obras sebelum dilepas: {accum:,.0f}')
r = post(f'/api/rahaza/finance/fixed-assets/{a2}/dispose','accounting',{'disposal_date':datetime.date.today().isoformat(),'disposal_value':50000000,'notes':'dijual'})
res = r.json(); print('  dispose ->', r.status_code, '| layar: NBV', res.get('nbv_at_disposal'), 'laba/rugi', res.get('gain_loss'), '| GL:', str(res.get('posting_result'))[:110])
je = H.run(H.DB.rahaza_journal_entries.find_one({'source_ref':f'asset_disposal:{a2}'},{'_id':0}))
if je:
    for ln in je['lines']: print(f"     {ln['account_code']:8s} {ln.get('account_name','')[:30]:30s} Dr {ln['debit']:>12,.0f}  Cr {ln['credit']:>12,.0f}")
    loss = sum(l['debit'] for l in je['lines'] if 'rugi' in (l.get('account_name') or '').lower() or 'loss' in (l.get('account_name') or '').lower())
    gain = sum(l['credit'] for l in je['lines'] if 'laba' in (l.get('account_name') or '').lower() or 'gain' in (l.get('account_name') or '').lower())
    chk('jurnal mendebit Akumulasi Depresiasi', any(l['account_code']=='1-2501' and l['debit']>0 for l in je['lines']), True)
    chk('laba/rugi di jurnal = laba/rugi di layar', round(gain-loss), round(res.get('gain_loss') or 0))
print('\n  hasil:', sum(R), 'lulus dari', len(R))
