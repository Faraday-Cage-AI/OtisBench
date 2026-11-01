"""Exact canonical colored directed material/recipe/site graph, ignoring quantities."""
import json
from manufacturing_networks import digest


def canonical(config):
    colors={};edges=set();purchased={o['item'] for o in config['offers']};sites={v['site'] for v in config['items'].values()}
    for site in sites:colors['site:'+site]='site'
    for name,item in config['items'].items():
        node='item:'+name;colors[node]='item:'+str(name in purchased)+':'+str(name in config['orders'])
        edges.add(('site:'+item['site'],node))
    for r in config['recipes']:
        node='recipe:'+r['id'];colors[node]='recipe:'+r['kind']
        edges.update(('item:'+n,node) for n in r['inputs']);edges.update((node,'item:'+n) for n in r['outputs'])
    groups={}
    for node,color in colors.items():groups.setdefault(color,[]).append(node)
    partition=[tuple(nodes) for _,nodes in sorted(groups.items())]
    def refine(blocks):
        while True:
            changed=[]
            for block in blocks:
                bins={}
                for node in block:
                    signature=tuple((sum((v,node) in edges for v in b),sum((node,v) in edges for v in b)) for b in blocks)
                    bins.setdefault(signature,[]).append(node)
                changed.extend(tuple(nodes) for _,nodes in sorted(bins.items()))
            if len(changed)==len(blocks):return changed
            blocks=changed
    def search(blocks):
        blocks=refine(blocks)
        if all(len(b)==1 for b in blocks):
            nodes=[b[0] for b in blocks];index={n:i for i,n in enumerate(nodes)}
            return json.dumps(dict(colors=[colors[n] for n in nodes],edges=sorted((index[a],index[b]) for a,b in edges)),sort_keys=True,separators=(',',':'))
        i=min((i for i,b in enumerate(blocks) if len(b)>1),key=lambda i:len(blocks[i]));block=blocks[i]
        return min(search(blocks[:i]+[(node,),tuple(n for n in block if n!=node)]+blocks[i+1:]) for node in block)
    code=search(partition)
    return dict(signature=digest(json.loads(code)),nodes=len(colors),edges=len(edges),canonical_graph=json.loads(code),
        scope='Exact colored material/recipe/site incidence graph. Item/recipe/site names and all quantities, durations, money and resource assignments are ignored; purchase/order roles and recipe kinds remain. Not a complete world-state/fault graph or novelty/holdout certificate.')
