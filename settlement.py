"""Conservative paper settlement from final PuntersEdge race results only."""
from decimal import Decimal
from datetime import datetime, timezone

def settle_ledger(ledger, results):
    """Return number settled. Never infer losses from missing/incomplete results."""
    by_id = {str(r.get("race_id")): r for r in results if isinstance(r,dict) and r.get("race_id") and str(r.get("status","")).lower() in ("final","settled")}
    count=0
    for bet in ledger.get("bets",[]):
        if bet.get("status")!="OPEN" or bet.get("market")!="PLACE": continue
        race=by_id.get(str(bet.get("race_id")))
        if not race: continue
        terms=bet.get("places_paid")
        if not isinstance(terms,int) or terms<1: continue
        # Avoid false losses if scratches, dead heats, incomplete placings, or terms differ.
        if race.get("scratchings") or race.get("dead_heat") or race.get("dead_heats"): continue
        result_terms=race.get("places_paid")
        if isinstance(result_terms,int) and result_terms!=terms: continue
        placings=race.get("placings")
        if not isinstance(placings,list): continue
        positions={}
        for p in placings:
            if not isinstance(p,dict): continue
            number=p.get("number",p.get("runner_number"))
            pos=p.get("position")
            if number is None or isinstance(pos,bool): continue
            try: pos=int(pos)
            except (ValueError,TypeError): continue
            if pos>0: positions[str(number)]=pos
        # Must have the full paid set, so missing results do not become losses.
        if not all(i in positions.values() for i in range(1,terms+1)): continue
        runner=str(bet.get("runner_id",""))
        # Runner IDs are not necessarily saddlecloth numbers. Only settle when the
        # result explicitly provides matching runner_id, or a verified runner number.
        matching=[p for p in placings if isinstance(p,dict) and p.get("runner_id") is not None and str(p["runner_id"])==runner]
        if not matching:\n            name=str(bet.get("runner_name","")).strip().casefold()\n            matching=[p for p in placings if isinstance(p,dict) and name and str(p.get("name","")).strip().casefold()==name and str(p.get("number",p.get("runner_number","")))==runner]\n        if not matching: continue
        try: position=int(matching[0]["position"])
        except (KeyError,ValueError,TypeError): continue
        if position<=0: continue
        won=position<=terms
        try:
            stake=Decimal(str(bet["stake_aud"]))
            odds=Decimal(str(bet["odds"]))
            if stake<=0 or odds<=1: continue
        except Exception: continue
        payout=(stake*odds if won else Decimal("0")).quantize(Decimal("0.01"))
        ledger["cash_aud"]=str((Decimal(str(ledger["cash_aud"]))+payout).quantize(Decimal("0.01")))
        bet["status"]="WON" if won else "LOST"
        bet["settlement"]={"position":position,"payout_aud":str(payout),"profit_aud":str(payout-stake),"source":"PuntersEdge final results","settled_at":datetime.now(timezone.utc).isoformat()}
        count+=1
    return count
