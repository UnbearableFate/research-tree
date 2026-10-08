"""Optimizers; a method is a new entry here (or a new option of one)."""
from __future__ import annotations

import math


class SGD:
    def __init__(self, lr: float, n: int):
        self.lr = lr

    def step(self, params, grads, t):
        return [p - self.lr * g for p, g in zip(params, grads)]


class Momentum:
    def __init__(self, lr: float, n: int, beta: float = 0.9):
        self.lr, self.beta, self.v = lr, beta, [0.0] * n

    def step(self, params, grads, t):
        self.v = [self.beta * v + g for v, g in zip(self.v, grads)]
        return [p - self.lr * v for p, v in zip(params, self.v)]


class Adam:
    def __init__(self, lr: float, n: int, b1: float = 0.9, b2: float = 0.999, eps: float = 1e-8):
        self.lr, self.b1, self.b2, self.eps = lr, b1, b2, eps
        self.m, self.v = [0.0] * n, [0.0] * n

    def step(self, params, grads, t):
        t += 1
        self.m = [self.b1 * m + (1 - self.b1) * g for m, g in zip(self.m, grads)]
        self.v = [self.b2 * v + (1 - self.b2) * g * g for v, g in zip(self.v, grads)]
        mh = [m / (1 - self.b1 ** t) for m in self.m]
        vh = [v / (1 - self.b2 ** t) for v in self.v]
        return [p - self.lr * a / (math.sqrt(c) + self.eps) for p, a, c in zip(params, mh, vh)]


OPTIMIZERS = {"sgd": SGD, "momentum": Momentum, "adam": Adam}
