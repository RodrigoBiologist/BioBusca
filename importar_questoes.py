"""Importador de questões oficiais verificadas, em CSV UTF-8.
Uso: py importar_questoes.py arquivo.csv
Não verifica automaticamente o conteúdo do PDF; exija conferência humana da origem e do gabarito.
"""
import csv,json,re,sys,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REQUIRED=['id','institution','year','booklet','number','title','answer','source_url','answer_source_url','concepts','verification']
CATALOG=json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))
TARGET=ROOT/'official_questions.json'
def load(path):
    with open(path,encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or any(k not in reader.fieldnames for k in REQUIRED):
            raise ValueError('Colunas obrigatórias: '+', '.join(REQUIRED))
        return list(reader)
def validate(r):
    if any(not r[k].strip() for k in REQUIRED):raise ValueError('Há campo obrigatório vazio')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{4,70}',r['id']):raise ValueError('ID inválido')
    if r['institution'].strip().upper()!='ENEM':raise ValueError('Este importador inicial aceita apenas ENEM')
    y=int(r['year']);number=int(r['number'])
    if not (2009<=y<=2100 and 1<=number<=180):raise ValueError('Ano ou número inválido')
    if r['answer'].strip().upper() not in 'ABCDE' or len(r['answer'].strip())!=1:raise ValueError('Gabarito deve ser A, B, C, D ou E')
    for field in ('source_url','answer_source_url'):
        u=urllib.parse.urlparse(r[field].strip())
        if u.scheme!='https' or u.hostname not in ('gov.br','www.gov.br','download.inep.gov.br','inep.gov.br'):
            raise ValueError(field+' deve apontar para endereço oficial INEP')
    if r['verification'].strip().lower()!='conferido':raise ValueError('verification deve ser conferido, após comparação com PDF oficial')
    concepts=[c.strip() for c in r['concepts'].split(';') if c.strip()]
    if not concepts or any(c not in CATALOG for c in concepts):raise ValueError('Conceitos não encontrados no catalog.json')
    return {'id':r['id'].strip(),'institution':'ENEM','year':y,'booklet':r['booklet'].strip(),'number':number,'title':r['title'].strip(),'answer':r['answer'].strip().upper(),'source_url':r['source_url'].strip(),'answer_source_url':r['answer_source_url'].strip(),'concepts':concepts,'verified_official':True,'verification':'Conferência declarada pelo responsável pela importação; não auditada automaticamente'}
def main():
    if len(sys.argv)!=2:raise SystemExit('Uso: py importar_questoes.py arquivo.csv')
    rows=load(sys.argv[1]);new=[]
    for i,row in enumerate(rows,2):
        try:new.append(validate(row))
        except Exception as exc:raise SystemExit(f'Linha {i}: {exc}')
    current=json.loads(TARGET.read_text(encoding='utf-8'))
    ids=[x['id'] for x in current]+[x['id'] for x in new]
    if len(ids)!=len(set(ids)):raise SystemExit('IDs duplicados; nenhum item foi importado')
    TARGET.write_text(json.dumps(current+new,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(new)} questões importadas. Reinicie o servidor para atualizar o mapa.')
if __name__=='__main__':main()
