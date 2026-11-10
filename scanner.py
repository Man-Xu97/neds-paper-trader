"""Read-only Neds race observation; no real or simulated orders."""
import datetime,json,os,pathlib,sys,urllib.parse,urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def fetch(category):
    q=urllib.parse.urlencode({'country':'AU','categories':category,'num_races':20,'bookmakers':'neds'})
    url='https://api.puntersedge.online/v1/racing/next-to-go?'+q
    req=urllib.request.Request(url,headers={'X-API-Key':os.environ['PUNTERSEDGE_API_KEY'],'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as res:return json.load(res),res.headers.get('x-credits-remaining')
def main():
    if not os.getenv('PUNTERSEDGE_API_KEY'):raise RuntimeError('Missing GitHub secret PUNTERSEDGE_API_KEY')
    statefile=ROOT/'data/state.json';out=ROOT/'docs/status.json'
    try:state=json.loads(statefile.read_text())
    except (OSError,ValueError):state={'seen':{}}
    report={'updated_at':now(),'mode':'OBSERVATION_ONLY','source':'PuntersEdge / Neds','live_betting':False,'paper_betting_enabled':False,'bankroll_aud':1000,'stake_aud':1,'settled_bets':0,'profit_aud':0,'place_bets':0,'favourite_vs_field_bets':0,'races_seen_total':0,'new_races':0,'observations':[],'errors':[],'credits_remaining':None,'notice':'只读观察，不生成投注。'}
    for category in ['horse','greyhound']:
        try:
            races,credits=fetch(category)
            report['credits_remaining']=credits or report['credits_remaining']
            if isinstance(races,dict):
                races=races.get('races',races.get('data',races.get('results')))
            if not isinstance(races,list):raise ValueError('Unknown API response schema; inspect docs and adjust parser')
            for race in races:
                if not isinstance(race,dict):continue
                rid=str(race.get('race_id') or race.get('id') or '')
                if not rid:continue
                key=category+':'+rid
                if key not in state['seen']:
                    state['seen'][key]=now();report['new_races']+=1
                report['observations'].append({'race_id':rid,'category':category,'venue':str(race.get('venue') or '')[:80],'race_number':race.get('race_number'),'start_time':race.get('start_time') or race.get('jump_time')})
        except Exception as exc:report['errors'].append(category+': '+str(exc)[:180])
    report['races_seen_total']=len(state['seen'])
    statefile.parent.mkdir(exist_ok=True);out.parent.mkdir(exist_ok=True)
    statefile.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Observed',len(report['observations']),'races; errors:',report['errors'])
    if report['errors'] and not report['observations']:sys.exit(1)
if __name__=='__main__':main()
