"""Points 9-11: turn one pull-request diff into one fixed-size embedding.

A pretrained code model (default ``microsoft/codereviewer``, trained on real code-review
diffs) reads the diff and returns one vector per PR. Nothing is trained here: the model
is used as-is, in evaluation mode, so the same diff always gives the same vector.

Pipeline for one diff:
1. split the unified diff into per-file sections;
2. keep only files the static-analysis graph also analyses (same rule as Steps 2-4,
   so tests, docs, setup.py, ... are dropped); if nothing is left, fall back to the
   full diff and record that;
3. turn diff lines into model text (CodeReviewer's <add>/<del>/<keep> line markers when
   the tokenizer knows them, otherwise the raw ``+``/``-`` lines);
4. split the tokens into overlapping windows that fit the model (512 tokens);
5. embed each window (mean of its token vectors) and average the windows, weighted by
   their token counts, into one vector.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
import re
from typing import Any, Protocol

import torch

from src.analysis.ast_parser import _include_file

DEFAULT_MODEL = "microsoft/codereviewer"

_FILE_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_SKIP_PREFIXES = ("index ", "--- ", "+++ ", "new file mode", "deleted file mode", "old mode", "new mode",
                  "similarity index", "rename from", "rename to", "copy from", "copy to", "Binary files")
_MARKERS = ("<add>", "<del>", "<keep>")


@dataclass(frozen=True)
class EncoderSettings:
    """Everything that changes the numbers. Stored with the embeddings so runs never mix."""

    max_tokens: int = 512        # model input limit, including special tokens
    stride: int = 384            # tokens between window starts (overlap = window - stride)
    max_chunks: int = 32         # cap for huge diffs; extra text is dropped and flagged
    batch_size: int = 8          # windows per forward pass (speed only, not results)
    graph_files_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("batch_size")  # does not affect results
        return values


@dataclass
class PreparedDiff:
    text: str
    files_used: list[str] = field(default_factory=list)
    files_dropped: list[str] = field(default_factory=list)
    fallback_full_diff: bool = False


@dataclass
class EncodedDiff:
    vector: torch.Tensor          # float32 [dim]
    num_tokens: int
    num_chunks: int
    truncated: bool
    files_used: list[str]
    files_dropped: list[str]
    fallback_full_diff: bool


class TokenizerLike(Protocol):
    pad_token_id: int | None

    def __call__(self, text: str, add_special_tokens: bool = ...) -> Any: ...

    def get_vocab(self) -> dict[str, int]: ...


def split_diff_by_file(diff_text: str) -> list[tuple[str, list[str]]]:
    """Return ``[(path, body_lines)]`` for each file section of a unified ``git diff``."""
    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in diff_text.splitlines():
        header = _FILE_HEADER.match(line)
        if header:
            current = []
            sections.append((header.group(2), current))
        elif current is not None:
            current.append(line)
    return sections


def graph_includes_path(path: str, analysis_settings: dict[str, Any]) -> bool:
    """True when Steps 2-4 would analyse this file, using the exact same rule."""
    root = Path("/repository")
    return _include_file(root / PurePosixPath(path), root,
                         set(analysis_settings["excluded_directory_names"]),
                         set(analysis_settings.get("excluded_file_names", [])),
                         bool(analysis_settings["include_tests"]))


def prepare_diff(diff_text: str, analysis_settings: dict[str, Any] | None, use_markers: bool,
                 graph_files_only: bool = True) -> PreparedDiff:
    """Select the file sections to encode and convert them to model text."""
    sections = split_diff_by_file(diff_text)
    if graph_files_only and analysis_settings is not None:
        kept = [(path, body) for path, body in sections if graph_includes_path(path, analysis_settings)]
        dropped = [path for path, _ in sections if not graph_includes_path(path, analysis_settings)]
    else:
        kept, dropped = sections, []
    fallback = bool(sections) and not kept
    if fallback:  # e.g. a PR that only changes tests: encode everything rather than nothing
        kept, dropped = sections, []
    lines = [converted for _, body in kept for converted in _convert_lines(body, use_markers)]
    return PreparedDiff(text="\n".join(lines), files_used=[path for path, _ in kept],
                        files_dropped=dropped, fallback_full_diff=fallback)


def _convert_lines(body: list[str], use_markers: bool) -> list[str]:
    converted: list[str] = []
    for line in body:
        if line.startswith(_SKIP_PREFIXES) or line.startswith("@@") or line.startswith("\\ No newline"):
            continue
        if not use_markers:
            converted.append(line)
        elif line.startswith("+"):
            converted.append("<add>" + line[1:])
        elif line.startswith("-"):
            converted.append("<del>" + line[1:])
        else:
            converted.append("<keep>" + line[1:])
    return converted


class DiffEncoder:
    """Embed diffs with a frozen pretrained encoder. ``tokenizer``/``model`` can be injected for tests."""

    def __init__(self, tokenizer: Any, model: Any, model_name: str, settings: EncoderSettings,
                 device: str = "cpu") -> None:
        if settings.max_tokens < 8 or not 0 < settings.stride or settings.max_chunks < 1:
            raise ValueError(f"Invalid encoder settings: {settings}")
        self.tokenizer, self.model, self.model_name, self.settings = tokenizer, model, model_name, settings
        self.device = torch.device(device)
        self.model.to(self.device)
        self.model.eval()
        self.prefix_ids, self.suffix_ids = _special_token_frame(tokenizer)
        self.window = settings.max_tokens - len(self.prefix_ids) - len(self.suffix_ids)
        if self.window < 1:
            raise ValueError("max_tokens is too small for this tokenizer's special tokens")
        self.stride = min(settings.stride, self.window)
        vocabulary = tokenizer.get_vocab()
        self.use_markers = all(marker in vocabulary for marker in _MARKERS)
        self.dim = _hidden_size(model)

    @classmethod
    def from_pretrained(cls, model_name: str = DEFAULT_MODEL, settings: EncoderSettings | None = None,
                        device: str = "cpu") -> "DiffEncoder":
        """Download (first time) and load a Hugging Face model. Encoder-decoder models
        such as CodeReviewer (T5) use only their encoder."""
        try:
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ImportError("transformers is not installed. Run: pip install -r requirements.txt") from exc
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        if getattr(model.config, "is_encoder_decoder", False):
            model = model.get_encoder()
        return cls(tokenizer, model, model_name, settings or EncoderSettings(), device)

    def describe(self) -> dict[str, Any]:
        """Settings recorded next to the embeddings; a mismatch means the numbers are not comparable."""
        return {"model_name": self.model_name, "dim": self.dim, "line_format": "markers" if self.use_markers else "raw",
                **self.settings.to_dict()}

    def encode_diff(self, diff_text: str, analysis_settings: dict[str, Any] | None,
                    allow_fallback: bool = True) -> EncodedDiff:
        """Embed one diff. With ``allow_fallback=False`` a diff that has no file the graph
        analyses (e.g. tests only) raises ``ValueError`` instead of using the full diff."""
        prepared = prepare_diff(diff_text, analysis_settings, self.use_markers, self.settings.graph_files_only)
        if not allow_fallback and (prepared.fallback_full_diff or not prepared.text.strip()):
            raise ValueError("no eligible production diff (only test/doc/excluded files changed)")
        vector, num_tokens, num_chunks, truncated = self.encode_text(prepared.text)
        return EncodedDiff(vector, num_tokens, num_chunks, truncated, prepared.files_used,
                           prepared.files_dropped, prepared.fallback_full_diff)

    @torch.no_grad()
    def encode_text(self, text: str) -> tuple[torch.Tensor, int, int, bool]:
        """Return ``(vector[dim], num_tokens, num_chunks, truncated)``."""
        ids = list(self.tokenizer(text, add_special_tokens=False)["input_ids"]) if text else []
        starts = list(range(0, max(len(ids) - self.window, 0) + 1, self.stride))
        if starts[-1] + self.window < len(ids):  # make sure the tail is covered
            starts.append(len(ids) - self.window)
        truncated = len(starts) > self.settings.max_chunks
        starts = starts[: self.settings.max_chunks]
        chunks = [self.prefix_ids + ids[start:start + self.window] + self.suffix_ids for start in starts]

        pad = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else 0
        total = torch.zeros(self.dim, dtype=torch.float64)
        weight = 0.0
        for begin in range(0, len(chunks), self.settings.batch_size):
            batch = chunks[begin:begin + self.settings.batch_size]
            width = max(len(chunk) for chunk in batch)
            input_ids = torch.full((len(batch), width), pad, dtype=torch.long)
            mask = torch.zeros((len(batch), width), dtype=torch.long)
            for row, chunk in enumerate(batch):
                input_ids[row, :len(chunk)] = torch.tensor(chunk, dtype=torch.long)
                mask[row, :len(chunk)] = 1
            hidden = self.model(input_ids=input_ids.to(self.device),
                                attention_mask=mask.to(self.device)).last_hidden_state.float().cpu()
            counts = mask.sum(dim=1, keepdim=True).clamp(min=1)
            chunk_vectors = (hidden * mask.unsqueeze(-1)).sum(dim=1) / counts  # mean over real tokens
            total += (chunk_vectors.double() * counts.double()).sum(dim=0)   # weight by chunk length
            weight += float(counts.sum())
        return (total / weight).float(), len(ids), len(chunks), truncated


def _special_token_frame(tokenizer: Any) -> tuple[list[int], list[int]]:
    """Find the special tokens the tokenizer puts before/after a sequence (e.g. <s> ... </s>)."""
    probe = "def probe():"
    plain = list(tokenizer(probe, add_special_tokens=False)["input_ids"])
    full = list(tokenizer(probe, add_special_tokens=True)["input_ids"])
    for start in range(len(full) - len(plain) + 1):
        if full[start:start + len(plain)] == plain:
            return full[:start], full[start + len(plain):]
    return [], []


def _hidden_size(model: Any) -> int:
    config = getattr(model, "config", None)
    for name in ("hidden_size", "d_model", "dim"):
        value = getattr(config, name, None)
        if isinstance(value, int) and value > 0:
            return value
    raise ValueError("Could not determine the model's embedding size from its config")
