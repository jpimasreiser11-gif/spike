#!/usr/bin/env python3
"""200 deterministic financial arithmetic TEST fixtures for S3 pipeline shape.

These templates were drafted with an assistant, so DO NOT USE them for model
training unless their exact source/terms are independently approved. Fixture
generation is no proof of a licensed training dataset, trained role or S3 PASS.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random
import sys

ONE_CENT = Decimal("0.01")


def money(amount):
    return amount.quantize(ONE_CENT, rounding=ROUND_HALF_UP)


def create(seed=42, total=200):
    if total != 200:
        raise ValueError("S3 pilot exactly 200 examples")
    rng = random.Random(seed)
    entries = []
    for index in range(total):
        count = rng.randint(1, 20)
        price = Decimal(rng.randint(120, 50000)) / 100
        discount = rng.choice((0, 5, 10, 15, 20))
        tax = rng.choice((0, 4, 10, 21))
        subtotal = money(price * count)
        discounted = money(subtotal * (Decimal(100 - discount) / 100))
        tax_amount = money(discounted * (Decimal(tax) / 100))
        result = money(discounted + tax_amount)
        # These are deliberately hypothetical transactions, not legal advice about tax.
        questions = (
            f"Factura ficticia: {count} unidades a {price:.2f} EUR cada una. "
            f"Descuento del {discount}% sobre subtotal e impuesto hipotético del {tax}% "
            "sobre el importe descontado. Redondea cada paso a céntimos. ¿Total?",
            f"Calculate this hypothetical invoice: {count} units at {price:.2f} EUR, "
            f"{discount}% discount then {tax}% notional tax on the discounted balance. "
            "Round each step to cents. What is the final total?",
            f"Factura inventada: {count} unitats de {price:.2f} EUR, descompte del "
            f"{discount}% i tribut hipotètic del {tax}% sobre el descompte aplicat. "
            "Arrodoneix cada pas a cèntims. Quin és el total?",
        )
        question = questions[index % len(questions)]
        answer = (f"Subtotal: {subtotal:.2f} EUR; tras descuento: {discounted:.2f} EUR; "
                  f"impuesto: {tax_amount:.2f} EUR; total: {result:.2f} EUR.")
        entries.append({
            "source_id": f"spike-original-s3-{index:03d}",
            "family_id": f"synthetic-invoice-{index:03d}",
            "split": "train" if index < 180 else "valid",
            "messages": [{"role": "user", "content": question},
                         {"role": "assistant", "content": answer}],
            "arithmetic": {"quantity": count, "price": f"{price:.2f}",
                           "discount_percent": discount, "tax_percent": tax,
                           "result_eur": f"{result:.2f}"},
        })
    if len({r["messages"][0]["content"] for r in entries}) != total:
        raise ValueError("duplicate prompts generated; change seed")
    return entries


def serialize(entries, split):
    return "".join(json.dumps(
        {"messages": row["messages"]}, ensure_ascii=False, sort_keys=True) + "\n"
        for row in entries if row["split"] == split).encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate 200 synthetic local verified finance examples")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = create(seed=args.seed)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = {"train": out / "train.jsonl", "valid": out / "valid.jsonl"}
    if any(path.exists() or path.is_symlink() for path in [*paths.values(), out / "manifest.json"]):
        parser.error("output files already exist; use an empty new directory")
    outputs = {split: serialize(rows, split) for split in paths}
    manifest = {
        "schema": "spike.phase0.s3-pilot-data.v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed, "total": len(rows), "train": 180, "valid": 20,
        "content_provenance": "synthetic_from_project_authored_decimal_calculator",
        "prompt_templates_origin": "assistant-drafted_repository_source",
        "training_permitted": False,
        "requires_legal_review_before_training": True,
        "no_real_people_or_business_transactions": True,
        "no_model_trained": True, "not_final_eval_dataset": True,
        "limits": "Invoice arithmetic only, not professional domain data or evidence of expertise.",
        "files": {split: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
                  for split, content in outputs.items()},
    }
    for split, content in outputs.items():
        paths[split].write_bytes(content)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_directory": str(out), "manifest": manifest}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
