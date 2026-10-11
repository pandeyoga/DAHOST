import harness as H, json
R = []
def chk(label, got, want, tol=0.5):
    if isinstance(want,(int,float)) and not isinstance(want,bool) and isinstance(got,(int,float)) and not isinstance(got,bool):
        ok = abs(got-want) <= tol
    else: ok = got == want
    R.append(ok); print(f"  {'OK   ' if ok else 'GAGAL'} {label}: dapat={got!r} harap={want!r}")
    return ok
def seed():
    SA = H.tok('superadmin')
    r = H.client.post('/api/rahaza/admin/seed-all-accounting', headers=SA, json={})
    assert r.status_code == 200, r.text
    H.run(H.DB.rahaza_customers.insert_one({'id':'C1','name':'PT Buyer Uji','code':'BUY-01','active':True}))
    H.run(H.DB.rahaza_cash_accounts.insert_one({'id':'CA1','name':'BCA Operasional','type':'bank','gl_account_code':'1-1201','active':True,'opening_balance':0}))
    H.run(H.DB.rahaza_employees.insert_many([
        {'id':'E1','employee_id':'E1','name':'Budi (operator)','email':'operator@da.test','active':True,'department':'Produksi'},
        {'id':'E2','employee_id':'E2','name':'Sari (rekan kerja)','email':'sari@da.test','active':True,'department':'Produksi'}]))
def jl_sum(code, since=None):
    q={'account_code':code}
    rows = H.run(H.DB.rahaza_journal_lines.find(q,{'_id':0}).to_list(None))
    return round(sum(float(r.get('debit') or 0)-float(r.get('credit') or 0) for r in rows),2)
def post(path, role='superadmin', body=None, uid=None, method='post'):
    fn = getattr(H.client, method)
    kw = {'headers': H.tok(role, uid)}
    if method != 'get' and method != 'delete': kw['json'] = body or {}
    return fn(path, **kw)
