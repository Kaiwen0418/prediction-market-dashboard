"""Outcome premium paid per observed contract, independent of YES quote direction."""
from decimal import Decimal


def cash_price(t):
    if 'cash_price' in t:
        return Decimal(t['cash_price']) if t['cash_price'] is not None else None
    price=Decimal(t['price'])
    if t.get('venue')=='kalshi':
        if t.get('direction') is None:return None
        return Decimal(1)-price if t['direction']==-1 else price
    return price


def cash(t):
    price=cash_price(t)
    return price*Decimal(t['quantity']) if price is not None else None


def cash_sql(document='document',venue='venue'):
    # Identifiers are supplied only by internal SQL builders, never by API input.
    return f"""((CASE WHEN {document} ? 'cash_price' THEN ({document}->>'cash_price')::numeric
        WHEN {venue}='kalshi' AND {document}->>'direction'='-1' THEN 1-({document}->>'price')::numeric
        WHEN {venue}='kalshi' AND ({document}->>'direction' IS NULL) THEN NULL
        ELSE ({document}->>'price')::numeric END)*({document}->>'quantity')::numeric)"""
