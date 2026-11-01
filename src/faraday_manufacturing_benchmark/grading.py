"""Typed numerical grading with explicit tolerances and family-balanced summaries."""
from __future__ import annotations
import math
from collections import defaultdict
from .calculations import SOLVERS


def equal(actual,expected,atol,rtol):
    if isinstance(expected,bool):return type(actual) is bool and actual==expected
    if expected is None:return actual is None
    if isinstance(expected,int):return type(actual) in (int,float) and math.isfinite(actual) and actual==expected
    if isinstance(expected,float):
        return type(actual) in (int,float) and math.isfinite(actual) and math.isclose(actual,expected,abs_tol=atol,rel_tol=rtol)
    if isinstance(expected,str):return type(actual) is str and actual==expected
    if isinstance(expected,list):return isinstance(actual,list) and len(actual)==len(expected) and all(equal(a,b,atol,rtol) for a,b in zip(actual,expected))
    if isinstance(expected,dict):return isinstance(actual,dict) and actual.keys()==expected.keys() and all(equal(actual[k],v,atol,rtol) for k,v in expected.items())
    return False


def grade(task,answer):
    expected=SOLVERS[task['family']](task['inputs'])
    if set(expected)!=set(task['output_fields']):raise ValueError('calculation and task contract disagree: '+task['id'])
    typed=isinstance(answer,dict) and set(answer)==set(expected)
    checks={k:isinstance(answer,dict) and k in answer and equal(answer[k],v,task['absolute_tolerance'],task['relative_tolerance']) for k,v in expected.items()}
    strict=typed and all(checks.values())
    return dict(task_id=task['id'],family=task['family'],domain=task['domain'],strict_success=strict,
                score=100*sum(checks.values())/len(checks) if typed else 0,checks=checks,schema_matches=typed)


def summarize(results):
    if not results:raise ValueError('cannot summarize an empty selection')
    families=defaultdict(list);domains=defaultdict(list)
    for r in results:families[r['family']].append(r);domains[r['domain']].append(r)
    def group(rows):return dict(tasks=len(rows),strict_successes=sum(r['strict_success'] for r in rows),mean_score=sum(r['score'] for r in rows)/len(rows))
    return dict(tasks=len(results),strict_successes=sum(r['strict_success'] for r in results),
                macro_family_strict_rate=sum(sum(r['strict_success'] for r in rows)/len(rows) for rows in families.values())/len(families),
                families={k:group(v) for k,v in sorted(families.items())},domains={k:group(v) for k,v in sorted(domains.items())})
