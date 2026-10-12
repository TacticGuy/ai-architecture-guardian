"""The fusion model: shrink each embedding with PCA, then a small classifier on top.

Why so small: v3 has only 15 training PRs. A 64 + 768 number input would let any model
memorise them, so each input is first squeezed to a few PCA numbers (fitted on the training
rows only), and the default classifier is logistic regression (a weighted sum turned into a
probability). ``kind="mlp"`` adds one hidden layer for when there is more data.

Everything is deterministic: the same inputs always give the same model and numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import torch

INPUTS = ("gnn", "diff")


# --- PCA -------------------------------------------------------------------------------------

@dataclass
class Projection:
    """Centre on the training mean, project onto the top components, scale each to std 1."""
    mean: torch.Tensor          # [dim]
    components: torch.Tensor    # [dim, k]
    scale: torch.Tensor         # [k]

    def transform(self, matrix: torch.Tensor) -> torch.Tensor:
        return ((matrix.double() - self.mean) @ self.components) / self.scale

    def to_state(self) -> dict[str, torch.Tensor]:
        return {"mean": self.mean, "components": self.components, "scale": self.scale}

    @classmethod
    def from_state(cls, state: dict[str, torch.Tensor]) -> "Projection":
        return cls(state["mean"], state["components"], state["scale"])


def fit_projection(train: torch.Tensor, dims: int) -> Projection:
    """PCA fitted on the training rows only. Uses at most ``rows - 1`` components."""
    train = train.double()
    k = max(1, min(dims, train.shape[0] - 1, train.shape[1]))
    mean = train.mean(dim=0)
    _, _, vh = torch.linalg.svd(train - mean, full_matrices=False)
    components = vh[:k].T.contiguous()
    # SVD may return a component or its mirror image; fix the sign so results are reproducible.
    biggest = components.abs().argmax(dim=0)
    signs = torch.sign(components[biggest, torch.arange(k)])
    components = components * torch.where(signs == 0, torch.ones_like(signs), signs)
    scale = ((train - mean) @ components).std(dim=0).clamp(min=1e-8)
    return Projection(mean, components, scale)


# --- classifiers -----------------------------------------------------------------------------

def _class_weights(labels: torch.Tensor) -> torch.Tensor:
    """Give both classes equal total weight (only 4 of 15 training PRs are 'safe')."""
    labels = labels.double()
    positives = float(labels.sum())
    negatives = float(labels.numel() - positives)
    if positives == 0 or negatives == 0:
        raise ValueError("training rows contain only one class; cannot train a classifier")
    count = labels.numel()
    return torch.where(labels == 1, count / (2 * positives), count / (2 * negatives))


def fit_logistic_regression(features: torch.Tensor, labels: torch.Tensor, c: float = 1.0) -> dict[str, torch.Tensor]:
    """L2-regularised, class-balanced logistic regression (same objective as scikit-learn's
    ``LogisticRegression(C=c, class_weight="balanced")``), solved with L-BFGS."""
    features, targets = features.double(), labels.double()
    weights_per_row = _class_weights(labels)
    count = features.shape[0]
    weight = torch.zeros(features.shape[1], dtype=torch.float64, requires_grad=True)
    bias = torch.zeros(1, dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.LBFGS([weight, bias], lr=1.0, max_iter=1000, tolerance_grad=1e-10,
                                  tolerance_change=1e-14, line_search_fn="strong_wolfe")

    def closure() -> torch.Tensor:
        optimizer.zero_grad()
        logits = features @ weight + bias
        loss = (weights_per_row * torch.nn.functional.binary_cross_entropy_with_logits(
            logits, targets, reduction="none")).sum() / count + weight.dot(weight) / (2 * c * count)
        loss.backward()
        return loss

    optimizer.step(closure)
    return {"weight": weight.detach().clone(), "bias": bias.detach().clone()}


def fit_mlp(features: torch.Tensor, labels: torch.Tensor, hidden: int = 16, epochs: int = 300,
            weight_decay: float = 1e-2, seed: int = 42) -> dict[str, torch.Tensor]:
    """One hidden layer, full-batch Adam, fixed epochs (no early stopping on a tiny validation set)."""
    generator = torch.Generator().manual_seed(seed)
    dim = features.shape[1]
    params = {
        "w1": (torch.randn(dim, hidden, generator=generator, dtype=torch.float64) / dim ** 0.5).requires_grad_(),
        "b1": torch.zeros(hidden, dtype=torch.float64, requires_grad=True),
        "w2": (torch.randn(hidden, generator=generator, dtype=torch.float64) / hidden ** 0.5).requires_grad_(),
        "b2": torch.zeros(1, dtype=torch.float64, requires_grad=True),
    }
    optimizer = torch.optim.Adam(params.values(), lr=0.01, weight_decay=weight_decay)
    weights_per_row, targets = _class_weights(labels), labels.double()
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = _mlp_logits(params, features.double())
        loss = (weights_per_row * torch.nn.functional.binary_cross_entropy_with_logits(
            logits, targets, reduction="none")).mean()
        loss.backward()
        optimizer.step()
    return {name: value.detach().clone() for name, value in params.items()}


def _mlp_logits(params: dict[str, torch.Tensor], features: torch.Tensor) -> torch.Tensor:
    return torch.relu(features @ params["w1"] + params["b1"]) @ params["w2"] + params["b2"]


# --- the fusion model ------------------------------------------------------------------------

@dataclass
class FusionModel:
    inputs: tuple[str, ...]                       # ("gnn",), ("diff",) or ("gnn", "diff")
    kind: str = "logreg"                          # "logreg" or "mlp"
    pca_dims: int = 8
    c: float = 1.0
    seed: int = 42
    projections: dict[str, Projection] = field(default_factory=dict)
    params: dict[str, torch.Tensor] = field(default_factory=dict)
    threshold: float = 0.5

    def __post_init__(self) -> None:
        if not self.inputs or any(name not in INPUTS for name in self.inputs):
            raise ValueError(f"inputs must be chosen from {INPUTS}, got {self.inputs}")
        if self.kind not in ("logreg", "mlp"):
            raise ValueError(f"unknown model kind {self.kind!r}")

    def features(self, matrices: dict[str, torch.Tensor]) -> torch.Tensor:
        return torch.cat([self.projections[name].transform(matrices[name]) for name in self.inputs], dim=1)

    def fit(self, matrices: dict[str, torch.Tensor], labels: torch.Tensor) -> "FusionModel":
        """``matrices`` and ``labels`` must contain the TRAINING rows only."""
        self.projections = {name: fit_projection(matrices[name], self.pca_dims) for name in self.inputs}
        features = self.features(matrices)
        if self.kind == "logreg":
            self.params = fit_logistic_regression(features, labels, self.c)
        else:
            self.params = fit_mlp(features, labels, seed=self.seed)
        return self

    @torch.no_grad()
    def predict_proba(self, matrices: dict[str, torch.Tensor]) -> torch.Tensor:
        features = self.features(matrices)
        if self.kind == "logreg":
            logits = features @ self.params["weight"] + self.params["bias"]
        else:
            logits = _mlp_logits(self.params, features)
        return torch.sigmoid(logits)

    def to_state(self) -> dict[str, Any]:
        """Only tensors, numbers and strings, so ``torch.load(weights_only=True)`` can read it."""
        return {"inputs": list(self.inputs), "kind": self.kind, "pca_dims": self.pca_dims, "c": self.c,
                "seed": self.seed, "threshold": self.threshold, "params": dict(self.params),
                "projections": {name: projection.to_state() for name, projection in self.projections.items()}}

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "FusionModel":
        model = cls(tuple(state["inputs"]), state["kind"], state["pca_dims"], state["c"], state["seed"])
        model.projections = {name: Projection.from_state(value) for name, value in state["projections"].items()}
        model.params, model.threshold = dict(state["params"]), float(state["threshold"])
        return model
