"""Strict A$10 paper-bet ledger. No bookmaker order functionality.
Only accepts explicitly normalized, timestamped, independently sourced market quotes.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
STAKE=Decimal("10.00")
def utc(value):
    if not isinstance(value,str): raise ValueError("timestamp required")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None: raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)
def place_quote(quote, now=None):
    """Return normalized Place candidate or None. No guessed odds or rules."""
    try:
        now=now or datetime.now(timezone.utc)
        if quote.get("market_type")!="PLACE" or quote.get("source")!="neds":
            return None
        if not all(quote.get(k) for k in ("race_id","runner_id","runner_name","market_id","odds_timestamp","start_time","place_terms","source_quote_id")):
            return None
        observed=utc(quote["odds_timestamp"]);start=utc(quote["start_time"])
        if not (observed<=now<start and (now-observed).total_seconds()<=120):
            return None
        if quote.get("market_status")!="OPEN" or quote.get("runner_status")!="ACTIVE":
            return None
        price=Decimal(str(quote["place_odds"]))
        if not (Decimal("1.50")<=price<=Decimal("1000")):return None
        return {"key":"PLACE:"+str(quote["market_id"])+":"+str(quote["runner_id"]),
                "race_id":str(quote["race_id"]),"runner_id":str(quote["runner_id"]),
                "runner_name":str(quote["runner_name"]),"market":"PLACE",
                "odds":str(price),"stake_aud":"10.00","source_quote_id":str(quote["source_quote_id"]),
                "odds_timestamp":observed.isoformat(),"place_terms":quote["place_terms"],
                "status":"OPEN","settlement":None}
    except (ValueError,TypeError,InvalidOperation,KeyError):return None
def favourite_field_quote(quote,now=None):
    """Only explicit two-sided FAVOURITE_VS_FIELD market; never synthesize prices."""
    try:
        now=now or datetime.now(timezone.utc)
        if quote.get("market_type")!="FAVOURITE_VS_FIELD" or quote.get("source")!="neds":return None
        if quote.get("market_status")!="OPEN":return None
        if not all(quote.get(k) for k in ("race_id","market_id","side","favourite_runner_id","odds_timestamp","start_time","source_quote_id")):return None
        if quote["side"] not in ("FAVOURITE","FIELD"):return None
        observed=utc(quote["odds_timestamp"]);start=utc(quote["start_time"])
        if not (observed<=now<start and (now-observed).total_seconds()<=120):return None
        price=Decimal(str(quote["odds"]))
        if not Decimal("1.01")<=price<=Decimal("1000"):return None
        return {"key":"FAVOURITE_VS_FIELD:"+str(quote["market_id"])+":"+quote["side"],
                "race_id":str(quote["race_id"]),"market":"FAVOURITE_VS_FIELD",
                "side":quote["side"],"favourite_runner_id":str(quote["favourite_runner_id"]),
                "odds":str(price),"stake_aud":"10.00","source_quote_id":str(quote["source_quote_id"]),
                "odds_timestamp":observed.isoformat(),"status":"OPEN","settlement":None}
    except (ValueError,TypeError,InvalidOperation,KeyError):return None
def add_paper_bet(ledger,candidate):
    """Idempotent; cash is reserved immediately; no credit or negative balance."""
    if candidate is None or candidate["key"] in {x["key"] for x in ledger["bets"]}:return False
    if Decimal(str(ledger["cash_aud"]))<STAKE:return False
    ledger["cash_aud"]=str(Decimal(str(ledger["cash_aud"]))-STAKE)
    ledger["bets"].append(candidate)
    return True
def new_ledger():return {"cash_aud":"1000.00","bets":[]}


def select_lower_odds_favourite_vs_field(quotes, now=None):
    """Select the cheaper side only when BOTH real quotes identify one market.
    Tied, stale, incomplete or mismatched quotes produce no selection.
    """
    if not isinstance(quotes,(list,tuple)) or len(quotes)!=2:return None
    by_side={}
    for q in quotes:
        if not isinstance(q,dict) or q.get("side") in by_side:return None
        normalized=favourite_field_quote(q,now)
        if normalized is None:return None
        by_side[q["side"]]=normalized
    if set(by_side)!={"FAVOURITE","FIELD"}:return None
    a,b=by_side["FAVOURITE"],by_side["FIELD"]
    if not all(a[k]==b[k] for k in ("race_id","favourite_runner_id","odds_timestamp")):return None
    if quotes[0].get("market_id")!=quotes[1].get("market_id"):return None
    if Decimal(a["odds"])==Decimal(b["odds"]):return None
    return min((a,b),key=lambda x:Decimal(x["odds"]))
