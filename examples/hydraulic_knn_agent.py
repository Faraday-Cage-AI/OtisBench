"""Offline supervised baseline: fixed 7-neighbor class votes or training priors.

Consumes supplied training labels and predictor vectors only. No file, network,
evaluator, numpy, provider, model API, cycle index or condition-group access.
"""
import heapq
import json
import math
import sys


class Agent:
    def __init__(self): self.fitted = False

    def decide(self, payload):
        if payload['phase'] == 'fit':
            if self.fitted: raise ValueError('refit after evaluation is forbidden')
            self.method = payload['method']; self.levels = payload['task']['target_levels']
            rows = payload['training_rows']; n = len(rows); d = len(payload['task']['feature_names'])
            if n < 7 or any(len(row['features']) != d for row in rows): raise ValueError('invalid training shape')
            self.mean = [math.fsum(row['features'][j] for row in rows) / n for j in range(d)]
            self.scale = [math.sqrt(math.fsum((row['features'][j] - self.mean[j]) ** 2 for row in rows) / n) or 1 for j in range(d)]
            self.x = [[(v - m) / s for v, m, s in zip(row['features'], self.mean, self.scale)] for row in rows]
            self.y = [row['labels'] for row in rows]
            self.priors = {target: {str(level): (1 + sum(row[target] == level for row in self.y)) / (n + len(levels)) for level in levels} for target, levels in self.levels.items()}
            self.fitted = True; return {'ready': True}
        if not self.fitted: raise ValueError('training required')
        if len(payload['case']['features']) != len(self.mean): raise ValueError('prediction feature shape mismatch')
        if self.method == 'majority': probabilities = self.priors
        else:
            x = [(v - m) / s for v, m, s in zip(payload['case']['features'], self.mean, self.scale)]
            distances = [(sum((a - b) ** 2 for a, b in zip(x, train)), i) for i, train in enumerate(self.x)]
            neighbors = [i for _, i in heapq.nsmallest(7, distances)]
            probabilities = {target: {str(level): (1 + sum(self.y[i][target] == level for i in neighbors)) / (7 + len(levels)) for level in levels} for target, levels in self.levels.items()}
        return {'tool': 'predict', 'arguments': {'probabilities': probabilities}}


if __name__ == '__main__':
    agent = Agent()
    for line in sys.stdin:
        request = json.loads(line); answer = agent.decide(request['payload'])
        print(json.dumps(answer, allow_nan=False), flush=True)
