"""Read-only Neds race observation; no real or simulated orders."""
import datetime,json,os,pathlib,sys,urllib.parse,urllib.request
from decimal import Decimal
from paper_engine import new_ledger, add_paper_bet
from settlement import settle_ledger
ROOT=pathlib.Path(__file__).resolve().parent
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def fetch(category):
    q=urllib.parse.urlencode({'country':'AU','categories':category,'num_races':20,'bookmakers':'neds'})
    url='https://api.puntersedge.online/v1/racing/next-to-go?'+q
    req=urllib.request.Request(url,headers={'X-API-Key':os.environ['PUNTERSEDGE_API_KEY'],'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as res:return json.load(res),res.headers.get('x-credits-remaining')
def priced_runners(race):
    runners=race.get('runners') or []
    if not isinstance(runners,list):return []
    out=[]
    for runner in runners:
        if not isinstance(runner,dict) or runner.get('scratched') or runner.get('is_scratched'):continue
        books=runner.get('bookmakers') or runner.get('prices') or runner.get('odds') or {}
        if isinstance(books,dict):
            book=books.get('neds')
        elif isinstance(books,list):
            book=next((b for b in books if isinstance(b,dict) and str(b.get('bookmaker') or b.get('key') or b.get('name') or '').lower()=='neds'),None)
        else:book=None
        if not isinstance(book,dict):continue
        win=book.get('win_price')
        place=book.get('place_price')
        if win is None or place is None:continue
        try:
            win=Decimal(str(win));place=Decimal(str(place))
            if win<=1 or place<=1:continue
        except Exception:continue
        out.append((runner,book,win,place))
    return out
def make_bet(race,category):
    """Conservative: require real Neds win/place prices, confirmed place terms and fresh quote."""
    if race.get('stale') is True:return None
    try:
        if float(race.get('data_age_seconds',99999))>120:return None
    except Exception:return None
    start=race.get('start_time') or race.get('jump_time')
    try:
        jump=datetime.datetime.fromisoformat(start.replace('Z','+00:00'))
        if not (datetime.datetime.now(datetime.timezone.utc)<jump):return None
    except Exception:return None
    terms=race.get('places_paid') or race.get('place_terms')
    if not isinstance(terms,int) or terms<2:return None
    choices=priced_runners(race)
    # Only favourite, and only within the pre-agreed Win 2.00-4.00 candidate band.
    if not choices:return None
    choices.sort(key=lambda x:x[2])
    runner,book,win,place=choices[0]
    if not Decimal('2')<=win<=Decimal('4'):return None
    rid=str(race.get('race_id') or race.get('id') or '')
    runnerid=str(runner.get('runner_id') or runner.get('id') or runner.get('number') or '')
    if not rid or not runnerid:return None
    return {'key':'PLACE:'+rid+':'+runnerid,'race_id':rid,'category':category,
            'runner_id':runnerid,'runner_name':str(runner.get('name') or runner.get('runner_name') or ''),
            'market':'PLACE','win_odds':str(win),'odds':str(place),'places_paid':terms,
            'stake_aud':'1.00','source':'PuntersEdge / Neds','observed_at':now(),
            'start_time':start,'status':'OPEN','settlement':None}
def main():
    if not os.getenv('PUNTERSEDGE_API_KEY'):raise RuntimeError('Missing GitHub secret PUNTERSEDGE_API_KEY')
    statefile=ROOT/'data/state.json';out=ROOT/'docs/status.json';ledgerfile=ROOT/'data/paper_ledger.json'
    try:ledger=json.loads(ledgerfile.read_text())
    except (OSError,ValueError):ledger=new_ledger()
    created=0
    settled=0
    settlement_error=None
    try:
        query=urllib.parse.urlencode({'hours_back':24,'country':'AU','status':'final','limit':200})
        req=urllib.request.Request('https://api.puntersedge.online/v1/racing/results?'+query,headers={'X-API-Key':os.environ['PUNTERSEDGE_API_KEY'],'Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=25) as response: results=json.load(response)
        if isinstance(results,list): settled=settle_ledger(ledger,results)
        else: settlement_error='Unexpected results response shape'
    except Exception as exc:
        settlement_error=str(exc)[:180]
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
                candidate=make_bet(race,category)
                if candidate and add_paper_bet(ledger,candidate):created+=1
                rid=str(race.get('race_id') or race.get('id') or '')
                if not rid:continue
                key=category+':'+rid
                if key not in state['seen']:
                    state['seen'][key]=now();report['new_races']+=1
                report['observations'].append({'race_id':rid,'category':category,'venue':str(race.get('venue') or '')[:80],'race_number':race.get('race_number'),'start_time':race.get('start_time') or race.get('jump_time')})
        except Exception as exc:report['errors'].append(category+': '+str(exc)[:180])
    report['races_seen_total']=len(state['seen'])
    report['mode']='PAPER_BETTING_PENDING_SETTLEMENT'
    report['paper_betting_enabled']=True
    report['bankroll_aud']=ledger['cash_aud']
    report['new_settlements']=settled
    report['settlement_error']=settlement_error
    report['settled_bets']=sum(b.get('status') in ('WON','LOST') for b in ledger['bets'])
    report['profit_aud']=str(sum((Decimal(str(b['settlement']['profit_aud'])) for b in ledger['bets'] if b.get('settlement') and b.get('status') in ('WON','LOST')),Decimal('0')))
    report['wins']=sum(b.get('status')=='WON' for b in ledger['bets'])
    report['losses']=sum(b.get('status')=='LOST' for b in ledger['bets'])
    report['place_bets']=len([b for b in ledger['bets'] if b.get('market')=='PLACE'])
    report['favourite_vs_field_bets']=len([b for b in ledger['bets'] if b.get('market')=='FAVOURITE_VS_FIELD'])
    report['paper_bets_open']=len([b for b in ledger['bets'] if b.get('status')=='OPEN'])
    report['new_paper_bets']=created
    report['recent_paper_bets']=ledger['bets'][-15:]
    report['notice']='只生成可核实 Neds Place 赔率的 A$1 虚拟下注；已接入保守赛果核对，无法可靠匹配的赛事继续待结算。Favourite vs Field 暂停，避免虚构市场。'
    ledgerfile.parent.mkdir(exist_ok=True)
    ledgerfile.write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
    statefile.parent.mkdir(exist_ok=True);out.parent.mkdir(exist_ok=True)
    statefile.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Observed',len(report['observations']),'races; errors:',report['errors'])
    if report['errors'] and not report['observations']:sys.exit(1)
if __name__=='__main__':main()
