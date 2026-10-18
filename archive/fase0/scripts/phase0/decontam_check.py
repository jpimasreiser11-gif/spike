#!/usr/bin/env python3
"""Fail-closed, metadata-only report for S4 dataset overlap screening.

Input may contain reviewed text, but output never contains text, row identifiers,
family names, input paths, input fingerprints, or excerpts. No dataset is fetched,
trained on, or declared legally usable by this screening tool.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata


ROOT = Path(__file__).resolve().parents[2]
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_MANIFEST_BYTES = 2_000_000
MAX_ROWS = 500
MAX_TEXT_BYTES = 4_096
MAX_META_CHARS = 256
MAX_EVIDENCE_PAIRS = 40

# These are conservative *screening* cutoffs, not a claim of semantic similarity.
WORD_TRIGRAM_JACCARD = 0.75
WORD_TRIGRAM_CONTAINMENT = 0.90
CHAR_FIVE_JACCARD = 0.82
CHAR_FIVE_CONTAINMENT = 0.95
CHAR_CJK_TRIGRAM_JACCARD = 0.82


class InputError(ValueError):
    """Static error codes, never include operator-supplied values."""


def digest(value):
    return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()


def normalize_text(value):
    """NFKC, full casefold, then keep Unicode letters/marks/numbers only.

    Does NOT transliterate accents, replace digits, or claim linguistic equivalence.
    Unicode whitespace, punctuation, symbols, and controls become separators.
    """
    if not isinstance(value, str):
        raise InputError("INVALID_TEXT")
    try:
        folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", value).casefold())
    except (UnicodeError, ValueError):
        raise InputError("INVALID_UNICODE") from None
    return " ".join(
        "".join(ch if unicodedata.category(ch)[0] in "LMN" else " " for ch in folded).split()
    )


def grams(sequence, width):
    if len(sequence) < width:
        return frozenset()
    return frozenset(tuple(sequence[i:i + width]) for i in range(len(sequence) - width + 1))


def features(value):
    normalized = normalize_text(value)
    if not normalized:
        raise InputError("EMPTY_NORMALIZED_TEXT")
    tokens = normalized.split()
    compact = normalized.replace(" ", "")
    return {
        "normalized_sha256": digest(normalized),
        "word_trigrams": grams(tokens, 3) if len(tokens) >= 6 else frozenset(),
        "char_five": grams(compact, 5) if len(compact) >= 25 else frozenset(),
        # CJK/Thai scripts are often written without spaces. Require all records
        # in a comparison to be unsegmented, and sufficient signal length.
        "char_unsegmented": grams(compact, 3) if len(tokens) == 1 and len(compact) >= 12 else frozenset(),
    }


def similarity(a, b):
    """Return reasons for near collision, with only non-content numeric scores."""
    reasons = {}
    for name, jaccard_gate, contain_gate, min_intersection in (
        ("word_trigrams", WORD_TRIGRAM_JACCARD, WORD_TRIGRAM_CONTAINMENT, 3),
        ("char_five", CHAR_FIVE_JACCARD, CHAR_FIVE_CONTAINMENT, 12),
        ("char_unsegmented", CHAR_CJK_TRIGRAM_JACCARD, None, 8),
    ):
        left, right = a[name], b[name]
        if not left or not right:
            continue
        intersection = len(left & right)
        if intersection < min_intersection:
            continue
        jaccard = intersection / (len(left) + len(right) - intersection)
        containment = intersection / min(len(left), len(right))
        if jaccard >= jaccard_gate or (contain_gate is not None and containment >= contain_gate):
            reasons[name] = round(max(jaccard, containment), 6)
    return reasons


def _validate_row(row, split, seen_ids):
    if not isinstance(row, dict):
        raise InputError("INVALID_ROW")
    for field in ("id", "family_id", "rights_reference"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_META_CHARS:
            raise InputError("INVALID_METADATA")
    if row["id"] in seen_ids:
        raise InputError("DUPLICATE_ID")
    seen_ids.add(row["id"])
    if (row.get("license_approved") is not True or row.get("pii_screened") is not True
            or row.get("allowed_use") != split):
        raise InputError("RIGHTS_OR_PII_REVIEW_REQUIRED")
    for field in ("raw_sha256", "normalized_sha256"):
        value = row.get(field)
        if not isinstance(value, str) or HEX_SHA256.fullmatch(value) is None:
            raise InputError("INVALID_SHA256")
    content = row.get("text")
    if not isinstance(content, str):
        # Hash-only input cannot establish that near-duplicate screening happened.
        raise InputError("TEXT_REQUIRED_FOR_NEAR_CHECK")
    try:
        size = len(content.encode("utf-8", errors="strict"))
        if not 1 <= size <= MAX_TEXT_BYTES:
            raise InputError("INVALID_TEXT_LENGTH")
        prepared = features(content)
        if not any(prepared[field] for field in ("word_trigrams", "char_five", "char_unsegmented")):
            # Too little lexical evidence to run ANY configured near-duplicate
            # signal; comparing only hashes would be an incomplete screen.
            raise InputError("INSUFFICIENT_NEAR_DUPLICATE_SIGNAL")
        if row["raw_sha256"] != digest(content) or row["normalized_sha256"] != prepared["normalized_sha256"]:
            raise InputError("HASH_MISMATCH")
    except UnicodeError:
        raise InputError("INVALID_UNICODE") from None
    # All identifiers and content remain internal to the process, never a report.
    prepared.update({
        "id": row["id"], "family_id": normalize_text(row["family_id"]),
        "raw_sha256": row["raw_sha256"], "split": split,
    })
    if not prepared["family_id"]:
        raise InputError("INVALID_FAMILY")
    return prepared


class DisjointSet:
    def __init__(self, count):
        self.parent = list(range(count))

    def root(self, pos):
        while self.parent[pos] != pos:
            self.parent[pos] = self.parent[self.parent[pos]]
            pos = self.parent[pos]
        return pos

    def merge(self, a, b):
        ra, rb = self.root(a), self.root(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def check(data):
    """Reproducible, privacy-preserving screening against train/eval overlap.

    Raises InputError for missing attestation, text or malformed/unverified hashes.
    A clean screening result is NEVER an authorization to train or a F0 gate PASS.
    """
    if not isinstance(data, dict) or data.get("eval_sealed") is not True:
        raise InputError("SEALED_EVAL_REQUIRED")
    train, evaluation = data.get("train"), data.get("eval")
    if not isinstance(train, list) or not isinstance(evaluation, list) or not train or not evaluation:
        raise InputError("TRAIN_AND_EVAL_REQUIRED")
    if len(train) + len(evaluation) > MAX_ROWS:
        raise InputError("TOO_MANY_ROWS")
    seen_ids = set()
    records = [_validate_row(row, split, seen_ids) for split, rows in (("train", train), ("eval", evaluation)) for row in rows]
    structure = DisjointSet(len(records))
    direct_edges = []
    signal_counts = defaultdict(int)

    # Compare all pairs, including within-split matches: near-duplicate / same
    # family chains can connect a train record to an eval record transitively.
    # Input bounds make exhaustive comparisons predictable and fail closed.
    for i, a in enumerate(records):
        for j in range(i + 1, len(records)):
            b = records[j]
            signals = {}
            if a["family_id"] == b["family_id"]:
                signals["family"] = 1.0
            if a["raw_sha256"] == b["raw_sha256"]:
                signals["raw_exact"] = 1.0
            if a["normalized_sha256"] == b["normalized_sha256"]:
                signals["unicode_normalized_exact"] = 1.0
            if not signals:
                signals.update(similarity(a, b))
            if not signals:
                continue
            structure.merge(i, j)
            for signal in signals:
                signal_counts[signal] += 1
            if (i < len(train)) != (j < len(train)):
                direct_edges.append({"train_index": i if i < len(train) else j,
                                     "eval_index": j - len(train) if j >= len(train) else i - len(train),
                                     "signals": dict(sorted(signals.items()))})

    groups = defaultdict(list)
    for index in range(len(records)):
        groups[structure.root(index)].append(index)
    contaminated_eval, contaminated_train = set(), set()
    contaminated_groups = 0
    for group in groups.values():
        train_members = {idx for idx in group if idx < len(train)}
        eval_members = {idx - len(train) for idx in group if idx >= len(train)}
        if train_members and eval_members:
            contaminated_train.update(train_members)
            contaminated_eval.update(eval_members)
            contaminated_groups += 1

    # No raw text, source IDs, family names, digest or user-supplied strings.
    return {
        "schema": "spike.phase0.decontamination.v2",
        "status": "FAIL_CONTAMINATION_DETECTED" if contaminated_groups else "SCREENING_ONLY_NO_DETECTED_OVERLAP",
        "phase0_passed": False, "training_authorized": False,
        "train_count": len(train), "eval_count": len(evaluation),
        "contaminated_train_count": len(contaminated_train),
        "contaminated_eval_count": len(contaminated_eval),
        "contaminated_component_count": contaminated_groups,
        "within_or_cross_split_signal_counts": dict(sorted(signal_counts.items())),
        "direct_cross_split_pairs": len(direct_edges),
        "evidence_pairs": direct_edges[:MAX_EVIDENCE_PAIRS],
        "evidence_pairs_truncated": len(direct_edges) > MAX_EVIDENCE_PAIRS,
        "normalization": "NFKC-casefold-NFKC, Unicode L/M/N, whitespace/punctuation collapsed; v2",
        "configuration": {
            "max_rows": MAX_ROWS, "max_text_bytes": MAX_TEXT_BYTES,
            "word_trigram_jaccard": WORD_TRIGRAM_JACCARD,
            "word_trigram_containment": WORD_TRIGRAM_CONTAINMENT,
            "char_five_jaccard": CHAR_FIVE_JACCARD,
            "char_five_containment": CHAR_FIVE_CONTAINMENT,
            "unsegmented_char_trigram_jaccard": CHAR_CJK_TRIGRAM_JACCARD,
        },
        "limitations": [
            "License/PII flags are operator attestations, not independent legal or PII verification.",
            "Approximate n-gram overlap is not semantic, cross-language, or pretraining contamination proof.",
            "Family derivations depend on correct external family metadata; no input text is retained in output.",
            "No model inference, teacher throughput, training, or completed S4 gate is asserted.",
        ],
    }


def _read_manifest(path):
    try:
        if path.is_symlink():
            raise InputError("INPUT_SYMLINK_REJECTED")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_MANIFEST_BYTES:
                raise InputError("INVALID_INPUT_FILE")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                payload = handle.read(MAX_MANIFEST_BYTES + 1)
            if len(payload) > MAX_MANIFEST_BYTES:
                raise InputError("MANIFEST_TOO_LARGE")
        finally:
            os.close(fd)
        return json.loads(payload.decode("utf-8", errors="strict"))
    except InputError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise InputError("MANIFEST_READ_OR_JSON_ERROR") from None


def _private_report(path, report):
    """Exclusive 0600 creation; reject symlink parents and no overwrites."""
    parent = path.absolute().parent
    # Check symlink components and create only missing directories as 0700.
    parts = list(reversed((parent,) + tuple(parent.parents)))
    for directory in parts:
        try:
            info = os.lstat(directory)
        except FileNotFoundError:
            os.mkdir(directory, mode=0o700)
            info = os.lstat(directory)
        if stat.S_ISLNK(info.st_mode):
            # macOS exposes its normal temp roots through /var -> /private/var
            # and /tmp -> /private/tmp. Accept ONLY these two fixed OS aliases.
            # Other symlink parents can silently redirect a private report.
            system_temp_alias = {"/var": "/private/var", "/tmp": "/private/tmp"}
            if (str(directory) in system_temp_alias
                    and os.path.realpath(directory) == system_temp_alias[str(directory)]):
                continue
            raise InputError("UNSAFE_OUTPUT_PARENT")
        if not stat.S_ISDIR(info.st_mode):
            raise InputError("UNSAFE_OUTPUT_PARENT")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        payload = (json.dumps(report, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # Report bytes are redacted; remove a partial file on I/O failure.
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description="S4 Unicode/near-family check of *already-reviewed* local manifest")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        report = check(_read_manifest(args.manifest))
    except (InputError, UnicodeError) as exc:
        report = {
            "schema": "spike.phase0.decontamination.v2",
            "status": "FAIL_INVALID_MANIFEST", "error_code": str(exc) if isinstance(exc, InputError) else "INVALID_UNICODE",
            "phase0_passed": False, "training_authorized": False,
        }
    output = args.output or ROOT / "reports" / "phase0" / (
        "decontamination-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "-" + str(os.getpid()) + ".json")
    try:
        _private_report(output, report)
    except (OSError, InputError):
        print("FAIL_REPORT_WRITE", file=sys.stderr)
        return 1
    print(report["status"])
    return 0 if report["status"] == "SCREENING_ONLY_NO_DETECTED_OVERLAP" else 1


if __name__ == "__main__":
    sys.exit(main())
