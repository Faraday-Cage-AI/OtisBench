"""Disclosed author baselines; no optimality or learned-model performance claim."""
from copy import deepcopy
import re
from .season import rule_policy


def maintenance_policy(observation):
    o=observation;window=None
    for notice in o['notices']:
        match=re.search(r'capacity in weeks (\d+)[–-](\d+)',notice)
        if match:window=tuple(map(int,match.groups()))
    maintenance=o['policy']['maintenance_cents'];minutes=o['policy']['maintenance_minutes']
    if not window or o['week']!=window[1]-3 or o['service_through_week']['mill']>=window[1] or o['cash_cents']<maintenance or o['capacity_minutes']['mill']<minutes:return rule_policy(o)
    reserved=deepcopy(o);reserved['cash_cents']-=maintenance;reserved['capacity_minutes']['mill']-=minutes
    action=rule_policy(reserved);action['maintain']=['mill'];return action
