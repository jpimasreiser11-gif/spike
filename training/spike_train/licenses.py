"""License policy for training data and model weights."""

from __future__ import annotations

# Licenses that allow commercial use and redistribution of derived model weights. Not llama3.1: its section 1.b.i
# makes any distributed model trained on Llama outputs start its name with "Llama" (docs/RESEARCH.md).
TRAIN_ALLOWLIST = {"apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "cc-by-4.0", "cc0-1.0", "odc-by"}
# Licenses acceptable for evaluation only (results may be published; data is never trained on).
EVAL_ALLOWLIST = TRAIN_ALLOWLIST | {"llama3.1", "cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nc-sa-4.0"}


def normalize(license_id: str | None) -> str:
    return (license_id or "").strip().lower()


def check(license_id: str | None, role: str) -> tuple[bool, str]:
    lic = normalize(license_id)
    if role == "excluded":
        return False, "excluded by SPIKE policy (see datasets.yaml provenance)"
    allowed = TRAIN_ALLOWLIST if role == "train" else EVAL_ALLOWLIST
    if not lic:
        return False, "no license declared"
    if lic not in allowed:
        return False, f"license '{lic}' is not allowed for role '{role}'"
    return True, lic


BLOCKED_STATUS = {"unverified": "license is unverified; Claude must review license and provenance before use",
                  "rejected": "license review rejected this source (see its provenance in datasets.yaml)"}


def blocked(src: dict, name: str = "source") -> None:
    """SystemExit, before any network access, for a source whose license review is pending or was rejected."""
    reason = BLOCKED_STATUS.get(src.get("license_status", ""))
    if reason:
        raise SystemExit(f"refusing {name}: {reason}")


def source_license(src: dict) -> str | None:
    """The license to gate a registry source on: as published on the Hub for a Hub source; for a URL source, which
    the Hub cannot be asked about, the one recorded in datasets.yaml (with the LICENSE file's URL)."""
    blocked(src)
    if "hub" not in src:
        return src.get("license")
    from .sources import hub_revision

    revision = hub_revision(src)  # a pinned Hub source is gated on the license at that commit
    return hub_license(src["hub"], revision) if revision else hub_license(src["hub"])


def _hub_license(kind: str, repo: str, revision: str | None = None) -> str | None:
    import httpx

    url = f"https://huggingface.co/api/{kind}/{repo}" + (f"/revision/{revision}" if revision else "")
    data = httpx.get(url, timeout=30).raise_for_status().json()
    card = data.get("cardData") or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    if not lic:
        lic = next((t.split(":", 1)[1] for t in data.get("tags", []) if t.startswith("license:")), None)
    return lic


def hub_license(repo: str, revision: str | None = None) -> str | None:
    """Read the license declared on the Hugging Face Hub for a dataset (network), at `revision` when given."""
    return _hub_license("datasets", repo, revision)


def hub_model_license(repo: str) -> str | None:
    """Read the license declared on the Hugging Face Hub for a model (network)."""
    return _hub_license("models", repo)


def teacher_license(repo: str, kind: str = "teacher") -> str:
    """The Hub license of a distillation teacher (`kind` names another kind of generator in the message, e.g. the base
    model writing its own replay) if its outputs may train released weights; ValueError otherwise.

    An unreadable or missing license is a refusal, the same as for a dataset: the generator's terms travel with
    every example it wrote."""
    import httpx

    try:
        lic = hub_model_license(repo)
    except httpx.HTTPError as exc:
        raise ValueError(f"{kind} '{repo}': cannot read its license on the Hugging Face Hub ({exc})") from exc
    ok, reason = check(lic, "train")
    if not ok:
        raise ValueError(f"{kind} '{repo}': {reason}")
    return reason
