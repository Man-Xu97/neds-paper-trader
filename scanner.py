"""Read-only Neds race observation; no real or simulated orders."""
import datetime,json,os,pathlib,sys,urllib.parse,urllib.request
from decimal import Decimal
from paper_engine import new_ledger, add_paper_bet, select_lower_odds_favourite_vs_field
from settlement import settle_ledger
ROOT=pathlib.Path(__file__).resolve().parent
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
COUNTRIES=('AU','NZ','GB','IE','US','JP','HK','FR','ZA','SG')
def fetch(category,country):
    q=urllib.parse.urlencode({'country':country,'categories':category,'num_races':20,'bookmakers':'neds'})
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
    if not Decimal('2')<=win<=Decimal('4') or place<Decimal('1.50'):return None
    rid=str(race.get('race_id') or race.get('id') or '')
    runnerid=str(runner.get('runner_id') or runner.get('id') or runner.get('number') or '')
    if not rid or not runnerid:return None
    return {'key':'PLACE:'+rid+':'+runnerid,'race_id':rid,'category':category,
            'runner_id':runnerid,'runner_name':str(runner.get('name') or runner.get('runner_name') or ''),
            'market':'PLACE','win_odds':str(win),'odds':str(place),'places_paid':terms,
            'stake_aud':'10.00','source':'PuntersEdge / Neds','observed_at':now(),
            'start_time':start,'status':'OPEN','settlement':None}

def favourite_field_candidate(race,category,diagnostics=None):
    """Find explicit two-sided quotes; never manufacture a market from win odds."""
    diagnostics=diagnostics if diagnostics is not None else {}
    markets=race.get('markets') or []
    if isinstance(markets,dict):
        markets=list(markets.values())
    if not isinstance(markets,list):markets=[]
    diagnostics['races_checked']=diagnostics.get('races_checked',0)+1
    diagnostics['markets_seen']=diagnostics.get('markets_seen',0)+len(markets)
    for market in markets:
        if not isinstance(market,dict):continue
        name=str(market.get('market_type') or market.get('type') or market.get('name') or market.get('market_name') or '').upper().replace(' ','_').replace('-','_')
        if name not in ('FAVOURITE_VS_FIELD','FAVORITE_VS_FIELD','FAVOURITE_V_FIELD','FAVORITE_V_FIELD'):continue
        diagnostics['matching_markets']=diagnostics.get('matching_markets',0)+1
        selections=market.get('selections') or market.get('outcomes')
        if not isinstance(selections,list) or len(selections)!=2:
            diagnostics['invalid_selections']=diagnostics.get('invalid_selections',0)+1
            continue
        quotes=[]
        for side in selections:
            if not isinstance(side,dict):break
            q=dict(side)
            for field in ('race_id','market_id','favourite_runner_id','odds_timestamp','start_time','source_quote_id','market_status'):
                q.setdefault(field,market.get(field,race.get(field)))
            q['market_type']='FAVOURITE_VS_FIELD'
            q['source']=str(market.get('source') or side.get('source') or '').lower()
            q['side']=str(q.get('side') or q.get('name') or '').upper()
            quotes.append(q)
        if len(quotes)!=2:continue
        chosen=select_lower_odds_favourite_vs_field(quotes)
        if chosen:
            chosen['category']=category
            chosen['source']='neds'
            diagnostics['valid_quotes']=diagnostics.get('valid_quotes',0)+1
            return chosen
        diagnostics['rejected_quotes']=diagnostics.get('rejected_quotes',0)+1
    return None

def result_rows(payload):
    """Normalize common API response envelopes without treating unknown shapes as empty."""
    if isinstance(payload,list): return payload
    if isinstance(payload,dict):
        for key in ('results','races','data','items'):
            value=payload.get(key)
            if isinstance(value,list): return value
            if isinstance(value,dict):
                for nested in ('results','races','items','data'):
                    if isinstance(value.get(nested),list): return value[nested]
    raise ValueError('Unrecognized results API response schema')

def settlement_diagnostics(ledger, results):
    by_id={str(r.get('race_id') or r.get('id')):r for r in results if isinstance(r,dict)}
    diagnostics=[]
    for bet in ledger.get('bets',[]):
        if bet.get('status')!='OPEN':continue
        race=by_id.get(str(bet.get('race_id')))
        if not race: reason='赛果接口未返回该赛事'
        elif str(race.get('status','')).lower() not in ('final','settled','official'): reason='赛事结果尚未标记为最终'
        elif not isinstance(race.get('placings'),list): reason='最终赛果缺少 placings 明细'
        else: reason='赛果字段或参赛者身份无法安全匹配'
        diagnostics.append({'key':bet.get('key'),'runner_name':bet.get('runner_name'),'reason':reason})
    return diagnostics

def main():
    if not os.getenv('PUNTERSEDGE_API_KEY'):raise RuntimeError('Missing GitHub secret PUNTERSEDGE_API_KEY')
    statefile=ROOT/'data/state.json';out=ROOT/'docs/status.json';ledgerfile=ROOT/'data/paper_ledger.json'
    try:ledger=json.loads(ledgerfile.read_text())
    except (OSError,ValueError):ledger=new_ledger()
    created=0
    settled=0
    settlement_error=None
    results=[]
    try:
        query=urllib.parse.urlencode({'hours_back':72,'status':'final','limit':500})
        req=urllib.request.Request('https://api.puntersedge.online/v1/racing/results?'+query,headers={'X-API-Key':os.environ['PUNTERSEDGE_API_KEY'],'Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=25) as response: results=json.load(response)
        results=result_rows(results)
        settled=settle_ledger(ledger,results)
    except Exception as exc:
        settlement_error=str(exc)[:180]
    try:state=json.loads(statefile.read_text())
    except (OSError,ValueError):state={'seen':{}}
    report={'updated_at':now(),'mode':'OBSERVATION_ONLY','source':'PuntersEdge / Neds','live_betting':False,'paper_betting_enabled':False,'bankroll_aud':1000,'stake_aud':10,'settled_bets':0,'profit_aud':0,'place_bets':0,'favourite_vs_field_bets':0,'races_seen_total':0,'new_races':0,'observations':[],'errors':[],'credits_remaining':None,'notice':'只读观察，不生成投注。'}
    report['countries_requested']=list(COUNTRIES)
    report['country_coverage']=[]
    seen_in_scan=set()
    report['market_diagnostics']={}
    for country in COUNTRIES:
        for category in ('horse','greyhound'):
            try:
                races,credits=fetch(category,country)
                report['credits_remaining']=credits or report['credits_remaining']
                if isinstance(races,dict):
                    races=races.get('races',races.get('data',races.get('results')))
                if not isinstance(races,list):raise ValueError('Unknown API response schema')
                count=0
                for race in races:
                    if not isinstance(race,dict):continue
                    rid=str(race.get('race_id') or race.get('id') or '')
                    if not rid:continue
                    key=category+':'+rid
                    if key in seen_in_scan:continue
                    seen_in_scan.add(key)
                    count+=1
                    candidate=favourite_field_candidate(race,category,report['market_diagnostics'])
                    if candidate and add_paper_bet(ledger,candidate):created+=1
                    if key not in state['seen']:
                        state['seen'][key]=now();report['new_races']+=1
                    report['observations'].append({'race_id':rid,'category':category,'country':country,'venue':str(race.get('venue') or '')[:80],'race_number':race.get('race_number'),'start_time':race.get('start_time') or race.get('jump_time')})
                report['country_coverage'].append({'country':country,'category':category,'races':count,'status':'queried'})
            except Exception as exc:
                message=str(exc)[:180]
                report['errors'].append(country+'/'+category+': '+message)
                report['country_coverage'].append({'country':country,'category':category,'races':0,'status':'error','reason':message})
    report['races_seen_total']=len(state['seen'])
    report['market_diagnostics']['explanation']='markets_seen=0 means the API returned no market objects; matching_markets=0 means no explicit Favourite vs Field market was identified. Rejected quotes need source field/schema verification.'
    report['research_market']='FAVOURITE_VS_FIELD'
    report['verified_favourite_vs_field_quotes']=created
    report['mode']='FAVOURITE_VS_FIELD_RESEARCH'
    report['paper_betting_enabled']=True
    report['bankroll_aud']=ledger['cash_aud']
    report['new_settlements']=settled
    report['results_returned']=len(results)
    report['settlement_diagnostics']=settlement_diagnostics(ledger,results) if not settlement_error else [{'reason':'赛果接口错误：'+settlement_error}]
    report['settlement_checked_at']=now()
    report['settlement_error']=settlement_error
    report['settled_bets']=sum(b.get('status') in ('WON','LOST') for b in ledger['bets'])
    report['profit_aud']=str(sum((Decimal(str(b['settlement']['profit_aud'])) for b in ledger['bets'] if b.get('settlement') and b.get('status') in ('WON','LOST')),Decimal('0')))
    # Place-odds cohort analysis, by racing category; only settled bets enter ROI.
    bands=[('1.50–1.79',Decimal('1.50'),Decimal('1.80')),('1.80–1.99',Decimal('1.80'),Decimal('2.00')),('2.00+',Decimal('2.00'),None)]
    report['place_odds_analysis']=[]
    for category in ('horse','greyhound'):
        for label,lower,upper in bands:
            bets=[]
            for b in ledger['bets']:
                if b.get('category')!=category or b.get('market')!='PLACE':continue
                try: odds=Decimal(str(b.get('odds')))
                except Exception:continue
                if odds>=lower and (upper is None or odds<upper):bets.append(b)
            finished=[b for b in bets if b.get('status') in ('WON','LOST') and b.get('settlement')]
            wins=sum(b['status']=='WON' for b in finished)
            staked=sum((Decimal(str(b.get('stake_aud',1))) for b in finished),Decimal('0'))
            profit=sum((Decimal(str(b['settlement']['profit_aud'])) for b in finished),Decimal('0'))
            report['place_odds_analysis'].append({'category':category,'band':label,'bets':len(bets),'settled':len(finished),'open':len(bets)-len(finished),'wins':wins,'hit_rate_pct':round(100*wins/len(finished),2) if finished else None,'profit_aud':str(profit),'roi_pct':round(float(100*profit/staked),2) if staked else None})
    report['wins']=sum(b.get('status')=='WON' for b in ledger['bets'])
    report['losses']=sum(b.get('status')=='LOST' for b in ledger['bets'])
    report['place_bets']=len([b for b in ledger['bets'] if b.get('market')=='PLACE'])
    report['favourite_vs_field_bets']=len([b for b in ledger['bets'] if b.get('market')=='FAVOURITE_VS_FIELD'])
    report['paper_bets_open']=len([b for b in ledger['bets'] if b.get('status')=='OPEN'])
    report['new_paper_bets']=created
    report['recent_paper_bets']=ledger['bets'][-15:]
    report['notice']='按国家逐一查询全球赛事；仅对接口明确提供且验证通过的 Favourite vs Field 双边市场生成 A$10 虚拟投注，选择较低赔率。国家覆盖以 country_coverage 为准；自动结算尚不支持该市场。'
    ledgerfile.parent.mkdir(exist_ok=True)
    ledgerfile.write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
    statefile.parent.mkdir(exist_ok=True);out.parent.mkdir(exist_ok=True)
    statefile.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Observed',len(report['observations']),'races; errors:',report['errors'])
    if report['errors'] and not report['observations']:sys.exit(1)
if __name__=='__main__':main()
