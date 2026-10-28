"""BioBusca 2.0: consultas científicas reais e cache SQLite local."""
import json, sqlite3, time, urllib.parse, urllib.request, os
from pathlib import Path
DB=Path(os.environ.get('BIOBUSCA_CACHE_PATH', '/tmp/biobusca_cache.sqlite3' if os.environ.get('RENDER') else str(Path(__file__).with_name('biobusca_cache.sqlite3'))))
def init():
    with sqlite3.connect(DB) as c:
        c.execute("CREATE TABLE IF NOT EXISTS queries (provider TEXT, term TEXT, checked_at INTEGER, payload TEXT, PRIMARY KEY(provider,term))")
def request(url):
    req=urllib.request.Request(url,headers={'User-Agent':'BioBusca/2.0 educational research prototype','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=9) as r: return json.load(r)
def cached(provider,term,fn):
    init()
    with sqlite3.connect(DB) as c:
        row=c.execute("SELECT checked_at,payload FROM queries WHERE provider=? AND term=?",(provider,term)).fetchone()
        if row and time.time()-row[0]<86400:
            return {'status':'cache','checked_at':row[0],'records':json.loads(row[1])}
    records=fn(term)
    with sqlite3.connect(DB) as c:
        c.execute("INSERT OR REPLACE INTO queries VALUES(?,?,?,?)",(provider,term,int(time.time()),json.dumps(records,ensure_ascii=False)))
    return {'status':'online','checked_at':int(time.time()),'records':records}
def epmc(t):
    q=urllib.parse.urlencode({'query':f'({t}) AND OPEN_ACCESS:y','format':'json','pageSize':12,'sort':'RELEVANCE'})
    data=request('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'+q)
    return [{'title':r.get('title'),'doi':r.get('doi'),'year':r.get('pubYear'),'url':'https://europepmc.org/article/'+str(r.get('source','MED'))+'/'+str(r.get('id','')),'peer_reviewed':'não verificado'} for r in data.get('resultList',{}).get('result',[])]
def openalex(t):
    q=urllib.parse.urlencode({'search':t,'per-page':12,'filter':'is_oa:true'})
    data=request('https://api.openalex.org/works?'+q)
    return [{'title':r.get('display_name'),'doi':r.get('doi'),'year':r.get('publication_year'),'url':r.get('doi') or r.get('id'),'peer_reviewed':'não verificado'} for r in data.get('results',[])]
def mesh(t):
    q=urllib.parse.urlencode({'db':'mesh','term':t,'retmode':'json','retmax':5})
    data=request('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?'+q)
    ids=data.get('esearchresult',{}).get('idlist',[])
    if not ids:return []
    detail=request('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?'+urllib.parse.urlencode({'db':'mesh','id':','.join(ids),'retmode':'json'}))
    return [{'id':i,'name':detail.get('result',{}).get(i,{}).get('ds_meshterms',[]),'url':'https://www.ncbi.nlm.nih.gov/mesh/'+i} for i in ids]
PROVIDERS={'Europe PMC':epmc,'OpenAlex':openalex,'MeSH (NCBI)':mesh}
def search(term):
    term=term.strip()[:120]
    if not term:raise ValueError('Informe uma palavra.')
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs={name:pool.submit(cached,name,term,fn) for name,fn in PROVIDERS.items()}
        results={}
        for name,f in jobs.items():
            try:results[name]=f.result()
            except Exception as exc:results[name]={'status':'indisponível','records':[],'error':type(exc).__name__}
    return {'query':term,'providers':results,'notice':'Registros recuperados ou em cache. A indexação não certifica revisão por pares, relevância ou validade científica.'}
