"""Synthetic data exclusively; no real datasets or model results."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
import decontam_check


ALPHA = "The diligent researcher compares sixteen independent numerical results before completing a written report."
BETA = "A ceramic artist carefully prepares fresh colored patterns for the community exhibition near the river."
GAMMA = "A botanist catalogs the flowers along the mountain hiking trail while keeping detailed field notes."


def row(identifier, family, text, use):
    return {
        "id": identifier, "family_id": family, "rights_reference": "synthetic-owned-test-only",
        "raw_sha256": decontam_check.digest(text),
        "normalized_sha256": decontam_check.digest(decontam_check.normalize_text(text)),
        "license_approved": True, "pii_screened": True, "allowed_use": use, "text": text,
    }


def manifest(train=None, evaluation=None):
    return {
        "eval_sealed": True,
        "train": train if train is not None else [row("training", "t-family", ALPHA, "train")],
        "eval": evaluation if evaluation is not None else [row("holdout", "e-family", BETA, "eval")],
    }


class DecontaminationTests(unittest.TestCase):
    def test_clean_result_only_screening_not_f0_pass(self):
        result = decontam_check.check(manifest())
        self.assertEqual(result["status"], "SCREENING_ONLY_NO_DETECTED_OVERLAP")
        self.assertFalse(result["phase0_passed"])
        self.assertFalse(result["training_authorized"])
        self.assertEqual(result["direct_cross_split_pairs"], 0)
        self.assertIn("pretraining", str(result["limitations"]))

    def test_full_unicode_nfkc_casefold_punctuation_whitespace(self):
        self.assertEqual(decontam_check.normalize_text("ＦＯＯ\u00a0BAR—１２３\nFiNe"), "foo bar 123 fine")
        self.assertEqual(decontam_check.normalize_text("Straße"), "strasse")
        self.assertEqual(decontam_check.normalize_text("Café"), decontam_check.normalize_text("Cafe\u0301"))

    def test_unicode_equivalence_exact_overlap(self):
        train_text = "ＦＯＯ  Café — independent collection of newly invented demonstrations in the laboratory"
        eval_text = "foo cafe\u0301 independent collection of newly invented demonstrations in the laboratory"
        data = manifest([row("a", "f1", train_text, "train")], [row("b", "f2", eval_text, "eval")])
        result = decontam_check.check(data)
        self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")
        self.assertIn("unicode_normalized_exact", result["evidence_pairs"][0]["signals"])

    def test_exact_raw_and_normalized_collisions(self):
        data = manifest([row("t", "one", ALPHA, "train")], [row("e", "two", ALPHA, "eval")])
        result = decontam_check.check(data)
        self.assertEqual(result["contaminated_eval_count"], 1)
        self.assertIn("raw_exact", result["evidence_pairs"][0]["signals"])

    def test_same_family_different_text_rejected(self):
        result = decontam_check.check(manifest([row("t", "same family", ALPHA, "train")],
                                               [row("e", "same family", GAMMA, "eval")]))
        self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")
        self.assertIn("family", result["evidence_pairs"][0]["signals"])

    def test_unrelated_families_near_word_trigram_detection(self):
        base = "The small research team reviewed many old archival documents before writing a detailed historical report about the village."
        derived = "The small research team reviewed many old archival documents before writing a detailed historical report about the valley."
        result = decontam_check.check(manifest([row("t", "f1", base, "train")],
                                               [row("e", "f2", derived, "eval")]))
        self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")
        self.assertIn("word_trigrams", result["evidence_pairs"][0]["signals"])

    def test_long_document_contains_eval_question(self):
        short = "The careful gardener records every seasonal change in the distant meadow across several weeks of observation."
        long = "Historical context with various unrelated information about astronomy and geography. " + short + " Extra documentation added for a different purpose."
        result = decontam_check.check(manifest([row("t", "f1", long, "train")],
                                               [row("e", "f2", short, "eval")]))
        self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")

    def test_unsegmented_cjk_near_text_detection(self):
        src = "東京の図書館で毎週歴史資料を丁寧に調査する学生たちが集まっています"
        variant = "東京の図書館で毎週歴史資料を丁寧に調査する学生たちが集まっていました"
        result = decontam_check.check(manifest([row("t", "f1", src, "train")],
                                               [row("e", "f2", variant, "eval")]))
        self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")
        self.assertIn("char_unsegmented", result["evidence_pairs"][0]["signals"])

    def test_transitive_families_block_all_derived_eval(self):
        data = manifest(
            [row("t", "train family", ALPHA, "train")],
            [row("e1", "eval family", ALPHA, "eval"), row("e2", "eval family", GAMMA, "eval")],
        )
        result = decontam_check.check(data)
        self.assertEqual(result["direct_cross_split_pairs"], 1)
        self.assertEqual(result["contaminated_eval_count"], 2)
        self.assertEqual(result["contaminated_component_count"], 1)

    def test_clean_similar_topic_but_different_text(self):
        data = manifest([row("t", "f1", ALPHA, "train")], [row("e", "f2", GAMMA, "eval")])
        self.assertEqual(decontam_check.check(data)["contaminated_eval_count"], 0)

    def test_rights_are_declarative_and_required(self):
        for field, new_value in (("license_approved", False), ("pii_screened", False),
                                 ("allowed_use", "eval"), ("rights_reference", "")):
            with self.subTest(field=field):
                data = manifest()
                data["train"][0][field] = new_value
                with self.assertRaises(decontam_check.InputError):
                    decontam_check.check(data)

    def test_hash_only_incomplete_manifest_is_error(self):
        data = manifest()
        data["train"][0].pop("text")
        with self.assertRaisesRegex(decontam_check.InputError, "TEXT_REQUIRED_FOR_NEAR_CHECK"):
            decontam_check.check(data)

    def test_short_text_without_enough_ngrams_fails_closed(self):
        data = manifest([row("short", "f1", "Go!", "train")],
                        [row("normal", "f2", BETA, "eval")])
        with self.assertRaisesRegex(decontam_check.InputError, "INSUFFICIENT_NEAR_DUPLICATE_SIGNAL"):
            decontam_check.check(data)

    def test_incorrect_hash_is_error(self):
        data = manifest()
        data["train"][0]["normalized_sha256"] = "a" * 64
        with self.assertRaisesRegex(decontam_check.InputError, "HASH_MISMATCH"):
            decontam_check.check(data)

    def test_false_hash_format_and_duplicate_id_fail(self):
        data = manifest()
        data["eval"][0]["raw_sha256"] = "wrong"
        with self.assertRaisesRegex(decontam_check.InputError, "INVALID_SHA256"):
            decontam_check.check(data)
        data = manifest()
        data["eval"][0]["id"] = "training"
        with self.assertRaisesRegex(decontam_check.InputError, "DUPLICATE_ID"):
            decontam_check.check(data)

    def test_unknown_or_unsealed_eval_or_empty_train_fails(self):
        for variant in (None, "false", False):
            with self.subTest(variant=variant):
                data = manifest()
                data["eval_sealed"] = variant
                with self.assertRaisesRegex(decontam_check.InputError, "SEALED_EVAL_REQUIRED"):
                    decontam_check.check(data)
        with self.assertRaisesRegex(decontam_check.InputError, "TRAIN_AND_EVAL_REQUIRED"):
            decontam_check.check(manifest(train=[]))

    def test_rejects_oversized_and_invalid_unicode(self):
        data = manifest()
        data["train"][0] = row("big", "one", "text", "train")
        data["train"][0]["text"] = "x" * (decontam_check.MAX_TEXT_BYTES + 1)
        with self.assertRaisesRegex(decontam_check.InputError, "INVALID_TEXT_LENGTH"):
            decontam_check.check(data)
        data = manifest()
        data["train"][0]["text"] = "unpaired \ud800 surrogate"
        with self.assertRaisesRegex(decontam_check.InputError, "INVALID_UNICODE"):
            decontam_check.check(data)

    def test_report_never_contains_raw_text_ids_families_or_hashes(self):
        secret = "Test-only fictitious email demo@example.invalid. The diligent researcher compares sixteen independent numerical results before completing a report."
        data = manifest([row("private-fake-identifier", "private-family", secret, "train")],
                        [row("private-holdout", "another-family", secret, "eval")])
        encoded = json.dumps(decontam_check.check(data), sort_keys=True)
        for value in (secret, "demo@example.invalid", "private-fake-identifier", "private-family", data["train"][0]["raw_sha256"]):
            self.assertNotIn(value, encoded)

    def test_reproducible_json_report_and_private_mode(self):
        data = manifest()
        with tempfile.TemporaryDirectory() as root:
            src = Path(root) / "input.json"
            src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            file1, file2 = Path(root) / "one.json", Path(root) / "two.json"
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(decontam_check.main(["--manifest", str(src), "--output", str(file1)]), 0)
                self.assertEqual(decontam_check.main(["--manifest", str(src), "--output", str(file2)]), 0)
            self.assertEqual(file1.read_bytes(), file2.read_bytes())
            self.assertNotIn(str(src), out.getvalue())
            self.assertEqual(stat.S_IMODE(file1.stat().st_mode), 0o600)

    def test_invalid_input_generates_redacted_failure_json(self):
        with tempfile.TemporaryDirectory() as root:
            src, output = Path(root) / "bad.json", Path(root) / "report.json"
            src.write_text('{"secret":"test-private-value"}', encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertNotEqual(decontam_check.main(["--manifest", str(src), "--output", str(output)]), 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "FAIL_INVALID_MANIFEST")
            self.assertFalse(report["phase0_passed"])
            self.assertNotIn("test-private-value", output.read_text())
            self.assertNotIn(str(src), out.getvalue())

    def test_cli_reports_overlapping_synthetic_rows_with_failure_exit(self):
        data = manifest([row("secret-train-id", "one", ALPHA, "train")],
                        [row("secret-eval-id", "two", ALPHA, "eval")])
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "input.json", Path(root) / "output.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(decontam_check.main(["--manifest", str(source), "--output", str(output)]), 1)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "FAIL_CONTAMINATION_DETECTED")
            self.assertFalse(result["training_authorized"])
            self.assertEqual(result["contaminated_eval_count"], 1)
            self.assertNotIn("secret-", output.read_text())

    def test_bounds_reject_oversized_manifest_and_row_count(self):
        base = manifest()
        base["train"] = [row(f"record-{n}", f"family-{n}", ALPHA, "train") for n in range(501)]
        with self.assertRaisesRegex(decontam_check.InputError, "TOO_MANY_ROWS"):
            decontam_check.check(base)
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "large.json", Path(root) / "status.json"
            source.write_bytes(b"x" * (decontam_check.MAX_MANIFEST_BYTES + 1))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(decontam_check.main(["--manifest", str(source), "--output", str(output)]), 1)
            self.assertEqual(json.loads(output.read_text())["error_code"], "INVALID_INPUT_FILE")

    def test_never_overwrites_existing_report(self):
        with tempfile.TemporaryDirectory() as root:
            src = Path(root) / "manifest.json"
            src.write_text(json.dumps(manifest()), encoding="utf-8")
            output = Path(root) / "report.json"
            output.write_text("OLD FILE MUST REMAIN", encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(decontam_check.main(["--manifest", str(src), "--output", str(output)]), 1)
            self.assertEqual(output.read_text(), "OLD FILE MUST REMAIN")

    def test_input_symlink_rejected_and_not_followed(self):
        with tempfile.TemporaryDirectory() as root:
            src = Path(root) / "manifest.json"
            src.write_text(json.dumps(manifest()), encoding="utf-8")
            alias = Path(root) / "alias.json"
            alias.symlink_to(src)
            output = Path(root) / "failure.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(decontam_check.main(["--manifest", str(alias), "--output", str(output)]), 1)
            self.assertEqual(json.loads(output.read_text())["error_code"], "INPUT_SYMLINK_REJECTED")

    def test_output_symlink_parent_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            real = base / "real"
            real.mkdir()
            link = base / "alias"
            link.symlink_to(real, target_is_directory=True)
            src = base / "manifest.json"
            src.write_text(json.dumps(manifest()), encoding="utf-8")
            sink = link / "bad.json"
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                self.assertEqual(decontam_check.main(["--manifest", str(src), "--output", str(sink)]), 1)
            self.assertFalse((real / "bad.json").exists())


if __name__ == "__main__":
    unittest.main()
