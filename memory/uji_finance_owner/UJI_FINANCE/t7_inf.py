from common import *
seed()
import datetime, math; T = datetime.date.today().isoformat()
r = H.client.post('/api/rahaza/journals', headers={**H.tok('accounting'),'Content-Type':'application/json'},
     content='{"date":"%s","description":"uji tak hingga","post":true,"lines":[{"account_code":"6-2900","debit":1e999,"credit":0},{"account_code":"1-1201","debit":0,"credit":1e999}]}' % T)
print('POST jurnal 1e999 ->', r.status_code)
jes = H.run(H.DB.rahaza_journal_entries.find({},{'_id':0,'je_number':1,'status':1,'total_debit':1,'description':1,'memo':1}).to_list(None))
print('jurnal tersimpan:', jes)
lines = H.run(H.DB.rahaza_journal_lines.find({},{'_id':0,'account_code':1,'debit':1,'credit':1}).to_list(None))
print('baris buku besar:', lines)
tb = H.client.get('/api/rahaza/finance/reports/trial-balance', headers=H.tok('accounting')); print('neraca saldo ->', tb.status_code)
pl = H.client.get('/api/rahaza/finance/reports/profit-loss', headers=H.tok('accounting')); print('laba rugi ->', pl.status_code)
bs = H.client.get('/api/rahaza/finance/reports/balance-sheet', headers=H.tok('accounting')); print('neraca ->', bs.status_code)
