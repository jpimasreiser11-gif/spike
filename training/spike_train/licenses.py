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


def source_license(src: dict) -> str | None:
    """The license to gate a registry source on: as published on the Hub for a Hub source; for a URL source, which
    the Hub cannot be asked about, the one recorded in datasets.yaml (with the LICENSE file's URL)."""
    return hub_license(src["hub"]) if "hub" in src else src.get("license")


def _hub_license(kind: str, repo: str) -> str | None:
    import httpx

    data = httpx.get(f"https://huggingface.co/api/{kind}/{repo}", timeout=30).raise_for_status().json()
    card = data.get("cardData") or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = lic[0] if lic else None
    if not lic:
        lic = next((t.split(":", 1)[1] for t in data.get("tags", []) if t.startswith("license:")), None)
    return lic


def hub_license(repo: str) -> str | None:
    """Read the license declared on the Hugging Face Hub for a dataset (network)."""
    return _hub_license("datasets", repo)


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
