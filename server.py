"""BioBusca 2.0: mapa, literatura e banco de questões com procedência."""
import json, os, re, unicodedata, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT=Path(__file__).resolve().parent
CONCEPTS=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
CURRICULUM=json.loads((ROOT/'curriculo_bncc.json').read_text(encoding='utf-8'))
EXAMS=json.loads((ROOT/'exams.json').read_text(encoding='utf-8'))
OFFICIAL=json.loads((ROOT/'official_questions.json').read_text(encoding='utf-8'))
ANSWER_INDEX=json.loads((ROOT/'enem_2024_caderno7_gabaritos.json').read_text(encoding='utf-8'))
def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if unicodedata.category(c)!='Mn')
def evidence(term):
    q=urllib.parse.quote(f'TITLE_ABS:"{term}" AND OPEN_ACCESS:y')
    url=f'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}&format=json&pageSize=4'
    req=urllib.request.Request(url,headers={'User-Agent':'BioBusca-educational-prototype/0.4'})
    with urllib.request.urlopen(req,timeout=8) as res: data=json.load(res)
    return [{'title':r.get('title',''),'journal':r.get('journalTitle',''),'year':r.get('pubYear',''),'doi':r.get('doi',''),'pmid':r.get('pmid',''),'url':f"https://europepmc.org/article/{r.get('source','MED')}/{r.get('id','')}"} for r in data.get('resultList',{}).get('result',[])]
def fetch_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'BioBusca/0.7 (educational local prototype; contact via project maintainer)','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=12) as response:
        return json.load(response)

def clean_article(title,authors,year,journal,doi,url,source,oa,abstract=''):
    doi=(doi or '').replace('https://doi.org/','').replace('http://doi.org/','').strip()
    return {'title':str(title or '')[:450], 'authors':authors[:6], 'year':year,
      'journal':str(journal or '')[:180], 'doi':doi, 'url':url,
      'source':source,'open_access':bool(oa),'abstract':str(abstract or '')[:1800]}

def epmc_search(term,limit=8):
    query=urllib.parse.quote('('+term+') AND OPEN_ACCESS:y')
    url='https://www.ebi.ac.uk/europepmc/webservices/rest/search?query='+query+'&format=json&pageSize='+str(limit)+'&resultType=core'
    data=fetch_json(url)
    out=[]
    for r in data.get('resultList',{}).get('result',[]):
        people=r.get('authorList',{}).get('author',[])
        authors=[(p.get('fullName') or (p.get('firstName','')+' '+p.get('lastName',''))).strip() for p in people]
        url='https://europepmc.org/article/'+urllib.parse.quote(r.get('source','MED'))+'/'+urllib.parse.quote(r.get('id',''))
        out.append(clean_article(r.get('title'),authors,r.get('pubYear'),r.get('journalTitle'),r.get('doi'),url,'Europe PMC',r.get('isOpenAccess')=='Y',re.sub('<[^>]*>',' ',r.get('abstractText',''))))
    return out

def openalex_search(term,limit=10):
    params=urllib.parse.urlencode({'search':term,'per-page':limit,'filter':'is_oa:true'})
    data=fetch_json('https://api.openalex.org/works?'+params)
    out=[]
    for r in data.get('results',[]):
        source=((r.get('primary_location') or {}).get('source') or {})
        loc=r.get('best_oa_location') or r.get('primary_location') or {}
        url=loc.get('landing_page_url') or r.get('doi') or r.get('id')
        inverted=r.get('abstract_inverted_index') or {}
        words=['']*(min(350,max((max(indices) for indices in inverted.values() if indices),default=-1)+1))
        for word,indices in inverted.items():
            for i in indices:
                if i<len(words):words[i]=word
        abstract=' '.join(words)
        out.append(clean_article(r.get('display_name'),[(a.get('author') or {}).get('display_name','') for a in r.get('authorships',[])],r.get('publication_year'),source.get('display_name'),r.get('doi'),url,'OpenAlex',r.get('open_access',{}).get('is_oa',False),abstract))
    return out

def literature(term):
    from concurrent.futures import ThreadPoolExecutor
    providers={'Europe PMC':epmc_search,'OpenAlex':openalex_search}
    articles=[]; errors=[];counts={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={name:pool.submit(fn,term) for name,fn in providers.items()}
        for name,f in futures.items():
            try:
                items=f.result(timeout=15);counts[name]=len(items);articles+=items
            except Exception:
                counts[name]=0;errors.append(name+' indisponível nesta consulta')
    seen=set();unique=[]
    for item in articles:
        key=('doi:'+item['doi'].lower()) if item['doi'] else 'title:'+norm(item['title'])
        if key in seen:continue
        seen.add(key);unique.append(item)
    return {'query':term,'results':unique[:18],'counts':counts,'errors':errors,
      'scielo_url':'https://search.scielo.org/?'+urllib.parse.urlencode({'q':term,'lang':'pt'}),
      'notice':'Registros recuperados automaticamente. Acesso aberto, relevância e afirmações científicas exigem leitura crítica; não há validação automática de conclusões. SciELO: link de pesquisa externa nesta versão, não API integrada.'}

def match(term):
    n=norm(term.strip()); scored=[]
    for key,c in CONCEPTS.items():
        fields=[c['name'],key]+c.get('keywords',[])+c.get('aliases',[])
        score=max([100 if norm(f)==n else 65 if n in norm(f) or norm(f) in n else 0 for f in fields] or [0])
        if score: scored.append({'id':key,'name':c['name'],'area':c['area'],'score':score,'type':'correspondência lexical'})
    return sorted(scored,key=lambda x:-x['score'])[:8]
def semantic(term):
    key=os.getenv('OPENAI_API_KEY',''); model=os.getenv('BIOBUSCA_MODEL','gpt-4.1-mini')
    if not key: return [],'IA não configurada; nenhuma associação livre foi inferida.'
    catalog=[{'id':k,'name':v['name'],'area':v['area'],'keywords':v.get('keywords',[])} for k,v in CONCEPTS.items()]
    prompt='Associe a palavra a até 5 conceitos existentes do catálogo. Não crie conceitos novos. Não force relações; se não houver relação defensável, retorne lista vazia. Cada associação deve incluir id, tipo (direta, indireta, interdisciplinar) e justificativa curta. Retorne SOMENTE JSON {"matches":[{"id":"...","type":"...","reason":"..."}]}.'
    payload={'model':model,'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'term':term,'catalog':catalog},ensure_ascii=False)}],'response_format':{'type':'json_object'},'temperature':0.1}
    req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=25) as res: raw=json.load(res)
    items=json.loads(raw['choices'][0]['message']['content']).get('matches',[])
    valid=[]
    for x in items:
        if x.get('id') in CONCEPTS and x.get('type') in ('direta','indireta','interdisciplinar'):
            valid.append({'id':x['id'],'name':CONCEPTS[x['id']]['name'],'area':CONCEPTS[x['id']]['area'],'type':x['type'],'reason':str(x.get('reason',''))[:220],'status':'hipótese de associação por IA — não validada'})
    return valid[:5],'Associações propostas por IA, pendentes de verificação científica.'
# Grafo de quatro pilares: relações conceituais explícitas e literatura consultada em tempo real.
# Correspondência bibliográfica NÃO é prova de sustentação de uma afirmação.
CONNECTIONS={
 'cafeina':['circadiano','contracao'], 'cafe':['cafeina','circadiano'],
 'futebol':['contracao','mitocondria'], 'praia':['restinga','osmose'],
 'chocolate':['cacau','mitocondria'], 'celular':['circadiano'],
 'energia':['mitocondria','fotossintese'], 'evolucao':['selecao','meiose']}

def graph(term):
    q=term.strip()[:120]
    if not q: raise ValueError('Informe uma palavra para pesquisar.')
    n=norm(q)
    # Ligações explícitas e auditáveis do catálogo. Nenhuma associação é
    # inferida de uma simples substring ou de títulos bibliográficos.
    direct=[]
    for cid,c in CONCEPTS.items():
        terms=[cid,c['name']]+c.get('aliases',[])+c.get('keywords',[])
        if any(norm(str(t))==n for t in terms): direct.append(cid)
    if not direct:
        # Um termo não cadastrado não deve produzir conexões fictícias.
        return {'query':q,'nodes':[{'id':'search:'+q,'kind':'pesquisa','label':q,'description':'Termo pesquisado; ainda não consta no catálogo científico curado.'}], 'edges':[], 'counts':{},'errors':[], 'notice':'Termo não catalogado. Nenhuma associação científica foi inventada.'}
    selected=list(dict.fromkeys(direct))[:4]
    for cid in list(selected):
        for rel in CONCEPTS[cid].get('related',[]):
            if rel in CONCEPTS and rel not in selected: selected.append(rel)
    selected=selected[:20]
    nodes=[{'id':'search:'+q,'kind':'pesquisa','label':q,'description':'Termo pesquisado pelo estudante'}]
    edges=[]
    for cid in selected:
        c=CONCEPTS[cid]
        nodes.append({'id':'concept:'+cid,'kind':'conceito','label':c['name'],'description':c['area']+' · '+c['sub'],'area':c['area'],'sub':c['sub'],'_keywords':c.get('keywords',[]),'concept_id':cid,'curricular_unit':c.get('curricular_unit'),'bncc_skills':c.get('bncc_skills',[])})
        if cid in direct:
            edges.append({'from':'search:'+q,'to':'concept:'+cid,'type':'correspondência exata de termo ou descritor','status':'catálogo local curado'})
    for cid in selected:
        for rel in CONCEPTS[cid].get('related',[]):
            if rel in selected:
                pair=tuple(sorted([cid,rel]))
                if not any(e.get('pair')==pair for e in edges):
                    edges.append({'from':'concept:'+cid,'to':'concept:'+rel,'type':'relação conceitual declarada','status':'catálogo didático; revisão bibliográfica específica pendente','pair':pair})
    for cid in selected:
        c=CONCEPTS[cid]
        for kw in c.get('keywords',[])[:4]:
            kid='term:'+norm(kw)
            if not any(node['id']==kid for node in nodes):
                nodes.append({'id':kid,'kind':'palavra_chave','label':kw,'description':'Descritor do catálogo local'})
            edges.append({'from':'concept:'+cid,'to':kid,'type':'descritor associado','status':'catálogo local'})
    return {'query':q,'nodes':nodes,'edges':edges,'counts':{},'errors':[],
            'notice':'Conexões didáticas explícitas do catálogo. Artigos bibliográficos não são inseridos como conceitos.'}

class Handler(SimpleHTTPRequestHandler):
    # Somente recursos públicos: não expor código Python, arquivos internos ou cache.
    PUBLIC_FILES={'/', '/index.html', '/mapa.html', '/rede.html'}
    def translate_path(self, path):
        clean=urllib.parse.urlsplit(path).path
        if clean == '/': clean='/mapa.html'
        if clean not in self.PUBLIC_FILES:
            return str(ROOT/'__recurso_nao_publico__')
        return str(ROOT/clean.lstrip('/'))

    def __init__(self,*args,**kwargs): super().__init__(*args,directory=str(ROOT),**kwargs)
    def do_GET(self):
        path=urllib.parse.urlparse(self.path)
        if path.path=='/api/curriculum':
            return self.reply(CURRICULUM)
        if path.path=='/health':
            return self.reply({'status':'ok','service':'BioBusca'})
        if path.path=='/api/scientific':
            from integracao import search
            try:return self.reply(search(urllib.parse.parse_qs(path.query).get('q',[''])[0]))
            except ValueError as e:return self.reply({'error':str(e)})
        if path.path=='/api/enem-2024-answer-index':
            return self.reply(ANSWER_INDEX)
        if path.path=='/api/exam-stats':
            from collections import Counter
            by_concept=Counter(c for q in OFFICIAL for c in q.get('concepts',[]))
            by_year=Counter(str(q.get('year')) for q in OFFICIAL)
            return self.reply({'total_verified_records':len(OFFICIAL),'verified_answer_keys':len(ANSWER_INDEX['records']),'by_concept':dict(by_concept),'by_year':dict(by_year),'denominator_note':'Contagem de itens classificados e importados; NÃO é incidência histórica do ENEM até que haja cobertura completa de edições.'})
        if path.path=='/api/exams':
            return self.reply({**EXAMS,'official_items':OFFICIAL})
        if path.path.startswith('/api/'):
            term=urllib.parse.parse_qs(path.query).get('q',[''])[0].strip()[:120]
            if not term: return self.reply({'error':'Informe um termo.'},400)
            try:
                if path.path=='/api/search':
                    found=match(term); inferred=[]; note='Busca lexical no catálogo local.'
                    if not found:
                        try: inferred,note=semantic(term)
                        except Exception as e: note='Serviço de IA indisponível; nenhuma associação foi inventada.'
                    return self.reply({'query':term,'matches':found,'inferred':inferred,'note':note})
                if path.path=='/api/literature': return self.reply(literature(term))
                if path.path=='/api/graph': return self.reply(graph(term))
                if path.path=='/api/learning-map':
                    return self.reply(self.learning_map(term))
                if path.path=='/api/integrar':
                    from integracao import search as search_scientific
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        map_job=pool.submit(self.learning_map,term)
                        science_job=pool.submit(search_scientific,term)
                        curricular_map=map_job.result()
                        try:
                            science=science_job.result()
                        except Exception as exc:
                            science={'query':term,'providers':{},'error':'Fontes científicas temporariamente indisponíveis'}
                    return self.reply({
                        'version':'3.2-piloto',
                        'query':term,
                        'map':curricular_map,
                        'scientific':science,
                        'curriculum':{
                            'area':CURRICULUM.get('area'),
                            'competencies':CURRICULUM.get('competencies',[]),
                            'skills':CURRICULUM.get('skills',[]),
                            'units':CURRICULUM.get('units',[])
                        },
                        'provenance':{
                            'concepts':'catálogo local estruturado, não inferência dos artigos',
                            'scientific':'consultas online ou cache, sem validação automática de evidências',
                            'questions':'somente questões oficiais verificadas e cadastradas',
                            'curriculum':'sínteses e associações didáticas baseadas na BNCC'
                        }
                    })
                if path.path=='/api/evidence': return self.reply({'query':term,'results':evidence(term),'notice':'Resultados bibliográficos recuperados automaticamente, NÃO revisados individualmente.'})
                return self.reply({'error':'Rota inexistente'},404)
            except Exception: return self.reply({'error':'Fonte externa temporariamente indisponível'},503)
        return super().do_GET()
    def learning_map(self,term):
        g=graph(term)
        selected={n.get('concept_id') for n in g['nodes'] if n.get('kind')=='conceito'}
        questions=[] # Questões autorais demonstrativas não são atribuídas automaticamente
        official=[x for x in OFFICIAL if selected.intersection(x['concepts'])]
        for item in questions:
            qid='exam:'+item['id']
            g['nodes'].append({'id':qid,'kind':'questao','label':item['title'],'description':'Questão autoral demonstrativa; não é prova oficial','exam_id':item['id']})
            for cid in item['concepts']:
                if cid in selected:
                    g['edges'].append({'from':'concept:'+cid,'to':qid,'type':'conceito necessário para resolver','status':'vínculo didático demonstrativo'})
        for item in official:
            qid='official:'+item['id']
            g['nodes'].append({'id':qid,'kind':'questao','label':item['title'],'description':'ENEM oficial: '+str(item['year'])+' / '+item['booklet']+' / questão '+str(item['number']),'exam_id':item['id'],'official':True})
            for cid in item['concepts']:
                if cid in selected:
                    g['edges'].append({'from':'concept:'+cid,'to':qid,'type':'conteúdo da questão oficial','status':'classificação temática declarada'})
        g['exams']=questions
        g['official_exams']=official
        g['official_count_total']=len(OFFICIAL)
        g['edition_index']=EXAMS['edition_index']
        g['official_sources']=EXAMS['sources']
        g['notice']='Relações e escores são heurísticos exploratórios. Apenas itens cadastrados com origem e gabarito conferidos aparecem como oficiais. Nenhum item oficial está pré-cadastrado.'
        return g
    def reply(self,obj,status=200):
        b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
if __name__=='__main__':
    port=int(os.environ.get('PORT','8000'))
    print(f'BioBusca 3.2 web na porta {port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
