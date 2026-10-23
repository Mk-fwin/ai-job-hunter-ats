import os, re, json, sqlite3, hashlib, hmac
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse
import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title='AI Job Hunter ATS', page_icon='🎯', layout='wide')
APP_DIR = Path(__file__).parent
DB_PATH = os.getenv('ATS_DB_PATH', str(APP_DIR / 'job_hunter.db'))

PROFILE = {'experience_years':4.2, 'salary_min_lpa':12, 'salary_target_lpa':18,
           'locations':['remote','india','bangalore','bengaluru','karnataka','srinagar'],
           'priority':['inside sales','business development','program advisor','executive education','customer success','account executive','sales consultant'],
           'secondary':['growth','product operations','business operations','associate product manager','product analyst'],
           'skills':['consultative sales','inside sales','admissions','lead qualification','pipeline','crm','salesforce','meritto','excel','executive education','customer engagement','stakeholder management','product management','figma']}


def secret(name, default=''):
    try: return st.secrets.get(name, os.getenv(name, default))
    except Exception: return os.getenv(name, default)

# Fail closed: the dashboard must never load without a configured password.
PASSWORD = secret('APP_PASSWORD')
if not PASSWORD:
    st.error('Private dashboard is locked: APP_PASSWORD is not configured in Streamlit Secrets.')
    st.info('In Streamlit Community Cloud, open your app settings → Secrets and add APP_PASSWORD = "your-strong-password". Save and restart the app.')
    st.stop()

if not st.session_state.get('authenticated', False):
    st.title('🔒 AI Job Hunter ATS')
    with st.form('ats_login', clear_on_submit=True):
        entered_password = st.text_input('Private dashboard password', type='password')
        submitted = st.form_submit_button('Unlock')
    if submitted:
        if hmac.compare_digest(entered_password.encode('utf-8'), str(PASSWORD).encode('utf-8')):
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error('Incorrect password')
    st.stop()

if st.sidebar.button('🔒 Log out'):
    st.session_state['authenticated'] = False
    st.rerun()

SUPA_URL = secret('SUPABASE_URL').rstrip('/')
SUPA_KEY = secret('SUPABASE_SERVICE_ROLE_KEY')
CLOUD = bool(SUPA_URL and SUPA_KEY)

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS applications (
          id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, url TEXT,
          location TEXT, source TEXT, salary TEXT, stage TEXT, track TEXT, score INTEGER,
          notes TEXT, applied_date TEXT, followup_date TEXT, created_at TEXT NOT NULL)''')
        con.commit()

def db_request(method, path, payload=None, params=None):
    headers = {'apikey':SUPA_KEY,'Authorization':f'Bearer {SUPA_KEY}', 'Content-Type':'application/json', 'Prefer':'return=representation,resolution=merge-duplicates'}
    response = requests.request(method, f'{SUPA_URL}/rest/v1/{path}', headers=headers,
                                json=payload, params=params, timeout=20)
    response.raise_for_status()
    return response.json() if response.text else []

def get_apps():
    if CLOUD: return db_request('GET','applications',params={'select':'*','order':'created_at.desc'})
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory=sqlite3.Row
        return [dict(r) for r in con.execute('SELECT * FROM applications ORDER BY created_at DESC')]

def save_app(record):
    if CLOUD: db_request('POST','applications',payload=record,params={'on_conflict':'id'},)
    else:
        cols=list(record)
        with sqlite3.connect(DB_PATH) as con:
            con.execute(f"INSERT OR REPLACE INTO applications ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})", list(record.values()))
            con.commit()

def update_app(app_id, fields):
    if CLOUD: db_request('PATCH','applications',payload=fields,params={'id':f'eq.{app_id}'})
    else:
        with sqlite3.connect(DB_PATH) as con:
            con.execute('UPDATE applications SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',list(fields.values())+[app_id]); con.commit()

def delete_app(app_id):
    if CLOUD: db_request('DELETE','applications',params={'id':f'eq.{app_id}'})
    else:
        with sqlite3.connect(DB_PATH) as con: con.execute('DELETE FROM applications WHERE id=?',(app_id,)); con.commit()

def clean_html(html): return BeautifulSoup(html or '', 'html.parser').get_text(' ',strip=True)

def normalize_job(company,title,url,location='',description='',salary='',source='',date=''):
    if not url: return None
    return {'id':hashlib.sha256(url.split('?')[0].rstrip('/').encode()).hexdigest()[:20],
            'company':str(company or 'Unknown'), 'title':str(title or 'Untitled'), 'url':url,
            'location':str(location or 'Not specified'), 'description':clean_html(description)[:16000],
            'salary':str(salary or ''), 'source':source, 'date':str(date or '')}

@st.cache_data(ttl=3600,show_spinner=False)
def fetch_remotive():
    response=requests.get('https://remotive.com/api/remote-jobs',timeout=20,headers={'User-Agent':'JobHunterATS/1.0'})
    response.raise_for_status()
    return [normalize_job(j.get('company_name'),j.get('title'),j.get('url'),j.get('candidate_required_location'),j.get('description'),j.get('salary'), 'Remotive',j.get('publication_date')) for j in response.json().get('jobs',[])]

@st.cache_data(ttl=3600,show_spinner=False)
def fetch_arbeitnow():
    response=requests.get('https://www.arbeitnow.com/api/job-board-api',timeout=20,headers={'User-Agent':'JobHunterATS/1.0'})
    response.raise_for_status()
    return [normalize_job(j.get('company_name'),j.get('title'),j.get('url'),j.get('location'),j.get('description'),'', 'Arbeitnow',j.get('created_at')) for j in response.json().get('data',[])]

@st.cache_data(ttl=3600,show_spinner=False)
def fetch_greenhouse(board):
    board=board.strip().strip('/')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',board): raise ValueError('Invalid Greenhouse board token')
    r=requests.get(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs',params={'content':'true'},timeout=20)
    r.raise_for_status()
    return [normalize_job(board,j.get('title'),j.get('absolute_url'),(j.get('location') or {}).get('name'),j.get('content'),'','Greenhouse',j.get('updated_at')) for j in r.json().get('jobs',[])]

@st.cache_data(ttl=3600,show_spinner=False)
def fetch_lever(site):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',site.strip()): raise ValueError('Invalid Lever site token')
    r=requests.get(f'https://api.lever.co/v0/postings/{site.strip()}',params={'mode':'json'},timeout=20)
    r.raise_for_status()
    return [normalize_job(site,j.get('text'),j.get('hostedUrl'),(j.get('categories') or {}).get('location'),j.get('descriptionPlain') or j.get('description'),'','Lever',j.get('createdAt')) for j in r.json()]

def track(title,description):
    content=(title+' '+description).lower()
    a=sum(bool(re.search(r'\b'+re.escape(k)+r'\b',content)) for k in PROFILE['priority'])
    b=sum(bool(re.search(r'\b'+re.escape(k)+r'\b',content)) for k in PROFILE['secondary'])
    return 'Sales / Education' if a>=b and a else 'Growth / Product' if b else 'Other'

def evaluate(job):
    title=job['title'].lower(); description=job['description'].lower(); body=title+' '+description
    p_hits=[k for k in PROFILE['priority'] if k in title]
    s_hits=[k for k in PROFILE['secondary'] if k in title]
    skill_hits=[k for k in PROFILE['skills'] if k in body]
    # A transparent relevance heuristic, not a company ATS score.
    role=min(35, 35 if p_hits else 24 if s_hits else 9 if any(k in body for k in PROFILE['priority']) else 0)
    skills=min(25,round(len(skill_hits)/7*25))
    salary=10 # unknown is neutral; don't invent pay
    salary_text=job.get('salary','')
    if salary_text:
        salary=12 # disclosed salary, currency not assumed comparable
    loc=job.get('location','').lower()
    location=10 if any(x in loc for x in PROFILE['locations']) else 3 if not loc or loc=='not specified' else 0
    career=10 if p_hits else 8 if s_hits else 2
    score=int(min(100,role+skills+salary+location+career))
    reasons=[]
    if p_hits or s_hits: reasons.append('Title aligns with '+', '.join((p_hits or s_hits)[:2]))
    if skill_hits: reasons.append('JD mentions '+', '.join(skill_hits[:5]))
    if location==0: reasons.append('Location may not match your preferences')
    if not salary_text: reasons.append('Salary not published; verify with recruiter')
    if not (p_hits or s_hits): reasons.append('Job title is outside your priority roles')
    return score, reasons, track(job['title'],job['description'])

def add_record(company,title,url='',location='',source='Manual',salary='',stage='Saved',track_name='Sales / Education',score=0,notes='',applied_date='',followup_date=''):
    id=hashlib.sha256((url.strip() or company.strip().lower()+'|'+title.strip().lower()).encode()).hexdigest()[:20]
    save_app({'id':id,'company':company.strip(),'title':title.strip(),'url':url.strip(),
              'location':location,'source':source,'salary':salary,'stage':stage,'track':track_name,
              'score':int(score),'notes':notes,'applied_date':applied_date,'followup_date':followup_date,
              'created_at':datetime.now(timezone.utc).isoformat()})

if not CLOUD: init_db()
st.title('🎯 AI Job Hunter ATS')
st.caption('Discover → rank → shortlist → apply → track. Scores are heuristic estimates, not employer ATS scores.')
st.sidebar.success('☁️ Supabase connected' if CLOUD else '💻 Local SQLite storage')
st.sidebar.caption('Cloud hosting without Supabase may lose saved records on restart. See README.')
page=st.sidebar.radio('Navigation',['Dashboard','Discover jobs','Application pipeline','Add application','Resume vs JD','Settings'])

if page=='Dashboard':
    try: apps=get_apps()
    except Exception as e: st.error(f'Database error: {e}'); st.stop()
    counts={s:sum(a['stage']==s for a in apps) for s in ['Saved','Applied','Screening','Interview','Offer','Rejected']}
    cols=st.columns(4)
    for c,(label,value) in zip(cols,[('Total tracked',len(apps)),('Applied',counts['Applied']),('Interviews',counts['Interview']),('Offers',counts['Offer'])]): c.metric(label,value)
    st.subheader('Recruitment funnel')
    st.bar_chart(pd.DataFrame({'Applications':counts}))
    st.subheader('Upcoming follow-ups')
    upcoming=[a for a in apps if a.get('followup_date') and a['stage'] not in ['Offer','Rejected']]
    upcoming.sort(key=lambda x:x['followup_date'])
    if upcoming: st.dataframe(pd.DataFrame(upcoming)[['company','title','stage','followup_date','notes']],hide_index=True,use_container_width=True)
    else: st.info('No follow-ups scheduled yet.')
    st.subheader('Recent applications')
    if apps: st.dataframe(pd.DataFrame(apps)[['company','title','stage','track','score','applied_date']],hide_index=True,use_container_width=True)
    else: st.info('No applications saved yet. Add your Emeritus application in “Add application”.')

elif page=='Discover jobs':
    st.info('Public job feeds may be heavily skewed toward tech/remote roles. They do not cover all Indian employers or LinkedIn listings.')
    c1,c2=st.columns(2)
    with c1:
        sources=st.multiselect('Job feeds',['Remotive','Arbeitnow','Greenhouse','Lever'],default=['Remotive','Arbeitnow'])
        keywords=st.text_input('Search title or description','sales OR business development OR customer success')
    with c2:
        greenhouse=st.text_input('Greenhouse board tokens (comma-separated)',placeholder='e.g. companyname')
        lever=st.text_input('Lever site tokens (comma-separated)',placeholder='e.g. companyname')
        min_score=st.slider('Minimum relevance score',0,100,40)
    if st.button('🔎 Fetch and rank jobs',type='primary'):
        jobs=[]; errors=[]
        for source, fn in [('Remotive',fetch_remotive),('Arbeitnow',fetch_arbeitnow)]:
            if source in sources:
                try: jobs.extend(fn())
                except Exception as e: errors.append(f'{source}: {e}')
        if 'Greenhouse' in sources:
            for board in [x.strip() for x in greenhouse.split(',') if x.strip()]:
                try: jobs.extend(fetch_greenhouse(board))
                except Exception as e: errors.append(f'Greenhouse {board}: {e}')
        if 'Lever' in sources:
            for site in [x.strip() for x in lever.split(',') if x.strip()]:
                try: jobs.extend(fetch_lever(site))
                except Exception as e: errors.append(f'Lever {site}: {e}')
        unique={j['id']:j for j in jobs if j}
        tokens=[t.strip().lower() for t in re.split(r'\s+OR\s+|,',keywords,flags=re.I) if t.strip()]
        result=[]
        for j in unique.values():
            if tokens and not any(t in (j['title']+' '+j['description']).lower() for t in tokens): continue
            score,reasons,jobtrack=evaluate(j)
            if score>=min_score: result.append({**j,'score':score,'reasons':reasons,'track':jobtrack})
        result.sort(key=lambda j:j['score'],reverse=True)
        st.session_state['discover_results']=result[:200]
        st.session_state['discover_errors']=errors
    for e in st.session_state.get('discover_errors',[]): st.warning(e)
    results=st.session_state.get('discover_results',[])
    if results: st.success(f'{len(results)} ranked matches (up to 200 shown)')
    for j in results:
        with st.expander(f"{j['score']}/100 · {j['title']} — {j['company']} ({j['location']})"):
            st.write('**Source:**',j['source'],'| **Salary:**',j['salary'] or 'Not published','| **Track:**',j['track'])
            for r in j['reasons']: st.write('• '+r)
            st.markdown(f"[Open original posting]({j['url']})")
            st.caption(j['description'][:1000]+('…' if len(j['description'])>1000 else ''))
            if st.button('Save to pipeline',key='save_'+j['id']):
                try:
                    add_record(j['company'],j['title'],j['url'],j['location'],j['source'],j['salary'],track_name=j['track'],score=j['score'])
                    st.success('Saved to pipeline')
                except Exception as e: st.error(f'Unable to save: {e}')
    if not results and 'discover_results' in st.session_state: st.info('No matches. Try fewer keywords or lower the score threshold.')

elif page=='Application pipeline':
    apps=get_apps()
    stages=['Saved','Applied','Screening','Interview','Offer','Rejected']
    if not apps: st.info('No applications yet. Add one or save a discovered job.')
    else:
        stage_filter=st.multiselect('Filter stages',stages,default=stages)
        track_filter=st.selectbox('Career track',['All','Sales / Education','Growth / Product','Other'])
        selected=[a for a in apps if a['stage'] in stage_filter and (track_filter=='All' or a['track']==track_filter)]
        for a in selected:
            with st.expander(f"{a['company']} · {a['title']} · {a['stage']}"):
                if a.get('url'): st.markdown(f"[Open job posting]({a['url']})")
                st.caption(f"{a.get('track','')} | Match {a.get('score') or 'N/A'} | {a.get('location') or 'Location unknown'}")
                with st.form('edit_'+a['id']):
                    stage=st.selectbox('Stage',stages,index=stages.index(a['stage']))
                    notes=st.text_area('Notes',value=a.get('notes') or '')
                    date=st.text_input('Applied date (YYYY-MM-DD)',value=a.get('applied_date') or '')
                    follow=st.text_input('Follow-up date (YYYY-MM-DD)',value=a.get('followup_date') or '')
                    if st.form_submit_button('Update application'):
                        try:
                            for v in [date,follow]:
                                if v: datetime.strptime(v,'%Y-%m-%d')
                            update_app(a['id'],{'stage':stage,'notes':notes,'applied_date':date,'followup_date':follow}); st.success('Updated'); st.rerun()
                        except ValueError: st.error('Use YYYY-MM-DD for dates')
                if st.button('Delete record',key='delete_'+a['id']): delete_app(a['id']); st.rerun()
        csv=pd.DataFrame(apps).to_csv(index=False).encode('utf-8')
        st.download_button('Export applications CSV',csv,'applications.csv','text/csv')

elif page=='Add application':
    st.subheader('Add a job or application')
    if st.button('Prefill Emeritus Program Advisor'):
        st.session_state['prefill_emeritus']=True
    prefill=st.session_state.get('prefill_emeritus',False)
    with st.form('new_application',clear_on_submit=False):
        c1,c2=st.columns(2)
        with c1:
            company=st.text_input('Company *',value='Emeritus' if prefill else '')
            title=st.text_input('Job title *',value='Program Advisor' if prefill else '')
            url=st.text_input('Job URL',value='')
            location=st.text_input('Location',value='India' if prefill else '')
            source=st.selectbox('Source',['LinkedIn','Company career page','Remotive','Arbeitnow','Greenhouse','Lever','Other'])
        with c2:
            stage=st.selectbox('Stage',['Saved','Applied','Screening','Interview','Offer','Rejected'],index=1 if prefill else 0)
            track_name=st.selectbox('Track',['Sales / Education','Growth / Product','Other'])
            salary=st.text_input('Salary (as advertised, if known)')
            applied=st.text_input('Applied date YYYY-MM-DD',value='2026-10-23' if prefill else '')
            follow=st.text_input('Follow-up date YYYY-MM-DD')
        notes=st.text_area('Notes',value='Applied via LinkedIn; awaiting shortlist. Expected CTC ₹14 LPA if entered as discussed.' if prefill else '')
        if st.form_submit_button('Save application',type='primary'):
            if not company.strip() or not title.strip(): st.error('Company and title are required')
            else:
                try:
                    for d in [applied,follow]:
                        if d: datetime.strptime(d,'%Y-%m-%d')
                    add_record(company,title,url,location,source,salary,stage,track_name,notes=notes,applied_date=applied,followup_date=follow)
                    st.success('Application saved')
                except ValueError: st.error('Dates must use YYYY-MM-DD')
                except Exception as e: st.error(f'Could not save: {e}')

elif page=='Resume vs JD':
    st.subheader('Resume vs job description')
    st.caption('This is a transparent keyword comparison, not an employer ATS simulation. No resume content is sent to an AI API.')
    upload=st.file_uploader('Upload your resume',type=['pdf','docx','txt'])
    jd=st.text_area('Paste job description',height=220)
    resume=''
    if upload:
        try:
            if upload.name.lower().endswith('.pdf'):
                from pypdf import PdfReader
                resume=' '.join(page.extract_text() or '' for page in PdfReader(upload).pages)
            elif upload.name.lower().endswith('.docx'):
                from docx import Document
                resume=' '.join(p.text for p in Document(upload).paragraphs)
            else: resume=upload.getvalue().decode('utf-8')
            st.caption(f'Extracted {len(resume)} characters from your resume.')
        except Exception as e: st.error(f'Unable to read resume: {e}')
    if st.button('Compare resume and JD'):
        if not resume.strip() or not jd.strip(): st.warning('Upload a readable resume and paste a JD first.')
        else:
            terms=['inside sales','consultative sales','business development','crm','salesforce','meritto','executive education','lead generation','pipeline management','customer success','excel','stakeholder management','product management','growth','user research','figma','international sales','lead qualification','cold calling','revenue']
            jd_terms=[t for t in terms if t in jd.lower()]
            hits=[t for t in jd_terms if t in resume.lower()]
            misses=[t for t in jd_terms if t not in resume.lower()]
            st.metric('Keyword coverage (selected terms)',f'{round(len(hits)/len(jd_terms)*100)}%' if jd_terms else 'N/A')
            st.write('**Matched terms:**',', '.join(hits) or 'None from reference vocabulary')
            st.write('**Not found in resume:**',', '.join(misses) or 'None')
            st.warning('Only add missing terms if they accurately describe your real experience. A keyword match is not a hiring prediction.')

elif page=='Settings':
    st.subheader('Deployment and data')
    st.write('Database:', 'Supabase PostgreSQL' if CLOUD else 'Local SQLite')
    st.write('Job sources: Remotive, Arbeitnow, Greenhouse boards, Lever sites')
    st.write('Scoring: transparent role/skill/location heuristic; salary is neutral when not published.')
    st.write('Profile defaults: 4.2 years experience; target ₹12–18 LPA; remote/India/Bengaluru preferred.')
    st.write('The app does not scrape LinkedIn, submit job applications, or automatically message recruiters.')
    st.caption('Configure APP_PASSWORD, SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in Streamlit secrets for private, persistent cloud deployment.')
