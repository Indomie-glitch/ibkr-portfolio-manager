import asyncio
import json
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import usage_store
from tests.pipeline_isolation import isolate
from supply_chain import graph, integrity, jobs, reader, status, verifier
from supply_chain.db import now, open_graph

CONTEXT = ("Item 1A. Risk Factors\n\nWe rely on Gamma Foundry Ltd. to manufacture all of our wafers, and it supplied 100% of our wafers in "
           "fiscal 2026.\n\nSales to our largest customer, Beta Corp, were 48% of revenue.")


def run(coro):
    return asyncio.run(coro)


def verdict(item, kind="supported", fields=(), reason="The context says so."):
    return {"item": item, "verdict": kind, "unsupported_fields": list(fields), "reason": reason}


def response(verdicts=None, stop="end_turn", model="claude-sonnet-5-5", iterations=None, input_tokens=2000, output_tokens=300):
    text = json.dumps({"verdicts": verdicts or []})
    content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)] if stop != "refusal" else []
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, iterations=iterations)
    return SimpleNamespace(stop_reason=stop, model=model, usage=usage, content=content)


class FakeClient:
    """client.beta.messages.create; answer(message, request) -> response."""
    def __init__(self, answer):
        self.answer, self.calls = answer, []
        self.beta = SimpleNamespace(messages=self)

    async def create(self, **request):
        self.calls.append(request)
        return self.answer(request["messages"][0]["content"], request)


def all_supported(message, request):
    count = message.count("\nClaim:")
    return response([verdict(n) for n in range(1, count + 1)])


class VerifierTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.conn = open_graph(root / "g.sqlite")
        self.addCleanup(self.conn.close)
        patch = mock.patch.object(usage_store, "DB_PATH", root / "usage.sqlite")
        patch.start()
        self.addCleanup(patch.stop)
        isolate(self, root)
        self.acme = graph.add_company(self.conn, "Acme Semiconductor Inc.")
        graph.add_identifier(self.conn, self.acme, "ticker", "ACME", "US")
        self.beta = graph.add_company(self.conn, "Beta Corp")
        self.gamma = graph.add_company(self.conn, "Gamma Foundry Ltd.")
        self.document = graph.add_document(self.conn, "sec", "10-K", "0001/acme.htm", "https://www.sec.gov/x", company_id=self.acme,
                                           filed_at="2026-02-25", period_end="2026-01-25", status="processed")
        self.read_id = self.conn.execute(
            """INSERT INTO chunk_reads (document_id, chunker_version, chunk_number, locator, text_hash, found, read_at)
               VALUES (?, 1, 1, 'Item 1A. Risk Factors, paragraphs 3-9 [chunker v1]', 'x', 1, ?)""", (self.document, now())).lastrowid

    def add_candidate(self, **fields):
        row = {"kind": "supplies", "counterparty_role": "supplier", "supplier_name": "Gamma Foundry Ltd.", "customer_name": "Acme Semiconductor Inc.",
               "supplier_is_filer": 0, "customer_is_filer": 1, "supplier_unnamed": 0, "customer_unnamed": 0,
               "supplier_id": self.gamma, "customer_id": self.acme, "resolved_by": "identifier_store", "what": "wafers",
               "supplier_revenue_share": None, "customer_supply_share": None, "customer_share_scope": None, "share_as_written": None,
               "share_dropped": None, "period_as_written": None, "stated_on": None, "ended": 0,
               "quote": "We rely on Gamma Foundry Ltd. to manufacture all of our wafers, and it supplied 100% of our wafers in fiscal 2026.",
               "locator": "Item 1A. Risk Factors, paragraph 4 [chunker v1]", "context": CONTEXT}
        row.update(fields)
        columns = list(row)
        return self.conn.execute(
            f"""INSERT INTO candidates (document_id, chunk_read_id, {", ".join(columns)}, candidate_hash, created_at, updated_at)
                VALUES (?, ?, {", ".join("?" * len(columns))}, ?, ?, ?)""",
            (self.document, self.read_id, *row.values(), graph.text_hash(json.dumps(row)), now(), now())).lastrowid

    def beta_customer(self, **fields):
        base = {"counterparty_role": "customer", "supplier_name": "Acme Semiconductor Inc.", "customer_name": "Beta Corp",
                "supplier_is_filer": 1, "customer_is_filer": 0, "supplier_id": self.acme, "customer_id": self.beta, "what": None,
                "quote": "Sales to our largest customer, Beta Corp, were 48% of revenue.", "locator": "Item 1A. Risk Factors, paragraph 5 [chunker v1]"}
        base.update(fields)
        return self.add_candidate(**base)

    def verify(self, answer=all_supported):
        client = FakeClient(answer)
        totals = run(verifier.verify_document(self.conn, self.document, client=client))
        return totals, client

    def candidate(self, candidate_id):
        return dict(self.conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone())

    def relationships(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM relationships ORDER BY id")]

    def evidence(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM evidence ORDER BY id")]

    def rejected(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM rejected ORDER BY id")]


class VerdictTests(VerifierTestCase):
    def test_supported_is_written_as_verified_tier_2(self):
        candidate = self.add_candidate(customer_supply_share=100, customer_share_scope="wafers", period_as_written="fiscal 2026",
                                       stated_on="2026-01-25")
        totals, _ = self.verify()
        self.assertEqual((totals["linked"], totals["rejected"]), (1, 0))
        relationship, = self.relationships()
        self.assertEqual((relationship["supplier_id"], relationship["customer_id"], relationship["kind"], relationship["tier"]),
                         (self.gamma, self.acme, "supplies", 2))
        self.assertEqual((relationship["customer_supply_share"], relationship["customer_share_scope"], relationship["what"]), (100.0, "wafers", "wafers"))
        self.assertEqual(relationship["confidence"], 0.6)  # one verified quote: medium (merge.py, #333)
        evidence, = self.evidence()
        self.assertEqual((evidence["extractor"], evidence["tier"], evidence["verification"], evidence["verified_by"]),
                         ("reader", 2, "verified", "claude-sonnet-5-5"))
        self.assertEqual((evidence["locator"], evidence["stated_on"], evidence["states_ended"]),
                         ("Item 1A. Risk Factors, paragraph 4 [chunker v1]", "2026-01-25", 0))
        row = self.candidate(candidate)
        self.assertEqual((row["status"], row["relationship_id"]), ("linked", relationship["id"]))
        self.assertEqual(json.loads(row["verdict"])["model"], "claude-sonnet-5-5")
        self.assertEqual(integrity.check(self.conn), [])

    def test_wrong_direction_is_rejected_even_when_partly_supported(self):
        candidate = self.add_candidate(supplier_name="Acme Semiconductor Inc.", customer_name="Gamma Foundry Ltd.", supplier_id=self.acme,
                                       customer_id=self.gamma, supplier_is_filer=1, customer_is_filer=0, counterparty_role="customer")
        self.verify(lambda m, r: response([verdict(1, "partly_supported", ["direction"], "Gamma makes Acme's wafers, not the reverse.")]))
        self.assertEqual(self.relationships(), [])
        row, = self.rejected()
        self.assertEqual((row["reason"], row["rejected_by"]), ("partly_supported_link", "verifier"))
        self.assertIn("unsupported: direction", row["detail"])
        self.assertEqual(self.candidate(candidate)["status"], "partly_supported")

    def test_made_up_percentage_is_dropped_and_the_link_kept(self):
        self.beta_customer(supplier_revenue_share=58)
        self.verify(lambda m, r: response([verdict(1, "partly_supported", ["supplier_revenue_share"], "The context says 48%, not 58%.")]))
        relationship, = self.relationships()
        self.assertIsNone(relationship["supplier_revenue_share"])
        evidence, = self.evidence()
        self.assertIsNone(evidence["supplier_revenue_share"])
        self.assertIn("not supported by the passage: supplier_revenue_share", evidence["share_note"])

    def test_not_supported_goes_to_rejected_with_the_reason(self):
        candidate = self.add_candidate(supplier_name="Delta Systems", supplier_id=self.beta)
        self.verify(lambda m, r: response([verdict(1, "not_supported", ["supplier"], "The context doesn't mention Delta Systems.")]))
        row, = self.rejected()
        self.assertEqual((row["reason"], row["rejected_by"], row["supplier_name"]), ("not_supported", "verifier", "Delta Systems"))
        self.assertIn("doesn't mention Delta Systems", row["detail"])
        self.assertNotIn("context", json.loads(row["payload"]))
        self.assertEqual(self.candidate(candidate)["status"], "not_supported")
        self.assertEqual(self.relationships(), [])

    def test_ended_relationship_is_kept_on_the_evidence(self):
        self.add_candidate(ended=1)
        self.verify()
        self.assertEqual(self.evidence()[0]["states_ended"], 1)
        self.assertEqual(self.relationships()[0]["status"], "ended")  # the merge (#127): its newest statement says it ended

    def test_ended_claim_the_context_doesnt_support(self):
        self.add_candidate(ended=1)
        self.verify(lambda m, r: response([verdict(1, "partly_supported", ["ended"], "Nothing says it ended.")]))
        self.assertEqual(self.evidence()[0]["states_ended"], 0)

    def test_unsupported_period_drops_the_date(self):
        self.add_candidate(period_as_written="fiscal 2026", stated_on="2026-01-25")
        self.verify(lambda m, r: response([verdict(1, "partly_supported", ["period"])]))
        self.assertIsNone(self.evidence()[0]["stated_on"])


class CounterpartyTests(VerifierTestCase):
    def test_unnamed_customer_becomes_a_placeholder_like_xbrl(self):
        first = self.beta_customer(customer_name="Customer A", customer_id=None, customer_unnamed=1, stated_on="2026-01-25")
        second = self.beta_customer(customer_name="Customer A", customer_id=None, customer_unnamed=1, stated_on="2026-01-25",
                                    quote="Customer A accounted for 48% of revenue.")
        self.verify()
        placeholder = self.conn.execute("SELECT * FROM companies WHERE is_placeholder = 1").fetchall()
        self.assertEqual(len(placeholder), 1)  # one per filer, label and period
        self.assertEqual(placeholder[0]["name"], "Customer A (unnamed customer of Acme Semiconductor Inc., year to 2026-01-25)")
        self.assertEqual(placeholder[0]["placeholder_for"], self.acme)
        self.assertEqual(self.candidate(first)["relationship_id"], self.candidate(second)["relationship_id"])
        self.assertEqual(self.relationships()[0]["customer_id"], placeholder[0]["id"])
        self.assertEqual(len(self.evidence()), 2)
        self.assertEqual(integrity.check(self.conn), [])

    def test_an_unnamed_counterparty_without_a_date_uses_the_report_period(self):
        self.beta_customer(customer_name="Customer B", customer_id=None, customer_unnamed=1)
        self.verify()
        name = self.conn.execute("SELECT name FROM companies WHERE is_placeholder = 1").fetchone()[0]
        self.assertTrue(name.endswith("year to 2026-01-25)"))

    def private_supplier(self, name="Groq", **fields):
        return self.add_candidate(supplier_name=name, supplier_private=1, supplier_id=None, resolved_by="private_pending",
                                  quote=f"We rely on {name} to manufacture all of our wafers, and it supplied 100% of our wafers in fiscal 2026.", **fields)

    def test_a_confirmed_private_counterparty_becomes_a_private_company(self):
        candidate = self.private_supplier("OpenAI, L.P.")
        self.verify()
        link = self.relationships()[0]
        company = self.conn.execute("SELECT * FROM companies WHERE id = ?", (link["supplier_id"],)).fetchone()
        self.assertEqual((company["name"], company["is_private"], company["is_placeholder"]), ("OpenAI, Inc.", 1, 0))
        self.assertEqual(self.candidate(candidate)["status"], "linked")
        self.assertEqual(integrity.check(self.conn), [])

    def test_two_spellings_land_on_one_company_and_one_link(self):
        self.private_supplier("OpenAI")
        self.private_supplier("OpenAI, L.P.")
        self.verify()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies WHERE is_private = 1").fetchone()[0], 1)
        self.assertEqual(len(self.relationships()), 1)

    def test_a_private_counterparty_the_verifier_rejects_creates_no_company(self):
        candidate = self.private_supplier("Groq")
        self.verify(lambda message, request: response([verdict(1, "not_supported")]))
        self.assertEqual(self.candidate(candidate)["status"], "not_supported")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies WHERE is_private = 1").fetchone()[0], 0)
        self.assertEqual(self.relationships(), [])

    def test_a_private_counterparty_with_the_link_unsupported_creates_no_company(self):
        self.private_supplier("Groq")
        self.verify(lambda message, request: response([verdict(1, "partly_supported", ["supplier"])]))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies WHERE is_private = 1").fetchone()[0], 0)
        self.assertEqual(self.rejected()[0]["reason"], "partly_supported_link")

    def test_the_claim_marks_an_unnamed_counterparty(self):
        self.beta_customer(customer_name="Customer A", customer_id=None, customer_unnamed=1)
        _, client = self.verify()
        self.assertIn("sells to Customer A (unnamed in the passage) (customer).", client.calls[0]["messages"][0]["content"])

    def test_share_dropped_by_the_reader_is_still_verified(self):
        candidate = self.beta_customer(share_dropped="supplier_revenue_share: digits_not_in_quote", share_as_written="about half")
        totals, client = self.verify()
        message = client.calls[0]["messages"][0]["content"]
        self.assertNotIn("revenue from", message)  # no share in the claim: the Reader dropped it
        self.assertEqual(self.candidate(candidate)["status"], "linked")
        note = self.evidence()[0]["share_note"]
        self.assertIn("dropped by the Reader: supplier_revenue_share: digits_not_in_quote", note)
        self.assertIn("as written: about half", note)

    def test_existing_link_gets_the_evidence_added(self):
        xbrl_link = graph.add_relationship(self.conn, self.acme, self.beta, {"document_id": self.document, "tier": 1, "extractor": "xbrl",
                                                                             "quote": "Beta Corp: 48% of revenue [us-gaap:ConcentrationRiskPercentage1]"},
                                           supplier_revenue_share=48, confidence=0.9)
        self.beta_customer()
        self.verify()
        self.assertEqual(len(self.relationships()), 1)
        self.assertEqual(len(self.evidence()), 2)
        self.assertEqual(self.relationships()[0]["tier"], 1)
        self.assertEqual(self.relationships()[0]["id"], xbrl_link)


class FallbackTests(VerifierTestCase):
    def test_the_model_that_answered_is_recorded_and_priced(self):
        self.add_candidate()
        iterations = [SimpleNamespace(type="message", model="claude-sonnet-5-5", input_tokens=2000, output_tokens=0),
                      SimpleNamespace(type="fallback_message", model="claude-sonnet-5", input_tokens=2100, output_tokens=400)]
        totals, _ = self.verify(lambda m, r: response([verdict(1)], model="claude-sonnet-5", iterations=iterations))
        self.assertEqual(self.evidence()[0]["verified_by"], "claude-sonnet-5")
        self.assertEqual(totals["models"], ["claude-sonnet-5-5", "claude-sonnet-5"])
        self.assertAlmostEqual(totals["cost_usd"], (2000 * 2 + 2100 * 2 + 400 * 10) / 1_000_000)
        month = usage_store.monthly()["by_feature"]["supply_chain_verifier"]
        self.assertEqual((month["calls"], month["input_tokens"]), (2, 4100))
        self.assertIn("claude-sonnet-5", usage_store.PRICES)

    def test_request_asks_for_the_default_fallback(self):
        self.add_candidate()
        _, client = self.verify()
        request = client.calls[0]
        self.assertEqual((request["model"], request["fallbacks"], request["betas"]), ("claude-sonnet-5-5", "default", ["server-side-fallback-2026-07-01"]))
        self.assertEqual(request["output_config"]["effort"], "medium")
        self.assertIn("only against its own context", request["system"])

    def test_a_refusal_of_the_whole_chain_leaves_candidates_pending(self):
        candidate = self.add_candidate()
        totals, _ = self.verify(lambda m, r: response(stop="refusal"))
        self.assertEqual(totals["declined"], 1)
        self.assertEqual(self.candidate(candidate)["status"], "pending")
        self.assertEqual(self.rejected(), [])


class BatchTests(VerifierTestCase):
    def test_claims_are_written_from_the_stored_fields_with_their_own_context(self):
        self.add_candidate(customer_supply_share=100, customer_share_scope="wafers", period_as_written="fiscal 2026", stated_on="2026-01-25")
        _, client = self.verify()
        message = client.calls[0]["messages"][0]["content"]
        self.assertTrue(message.startswith("Item 1\nClaim:\nGamma Foundry Ltd. (supplier) sells to Acme Semiconductor Inc. (customer).\n"))
        self.assertIn("Share of Acme Semiconductor Inc.'s wafers that comes from Gamma Foundry Ltd.: 100%", message)
        self.assertIn("Period: fiscal 2026 (2026-01-25)", message)
        self.assertIn("Ended: no", message)
        self.assertIn("Context:\n<<<\n" + CONTEXT + "\n>>>", message)

    def test_a_partnership_claim_has_no_direction(self):
        self.beta_customer(kind="partnership", counterparty_role="partner")
        _, client = self.verify()
        self.assertIn("Acme Semiconductor Inc. and Beta Corp are partners", client.calls[0]["messages"][0]["content"])
        self.assertEqual(self.relationships()[0]["kind"], "partnership")

    def test_batches_of_ten(self):
        for n in range(23):
            self.beta_customer(quote=f"Sales to our largest customer, Beta Corp, were 48% of revenue. ({n})")
        totals, client = self.verify()
        self.assertEqual(len(client.calls), 3)
        self.assertEqual([c["messages"][0]["content"].count("\nClaim:") for c in client.calls], [10, 10, 3])
        self.assertEqual(totals["linked"], 23)

    def test_batches_stay_near_the_token_cap(self):
        big = "Gamma Foundry Ltd. makes our wafers. " * 600  # about 7,800 estimated tokens each
        for n in range(4):
            self.add_candidate(context=f"{big} ({n})")
        groups = verifier.batches(self.conn.execute("SELECT * FROM candidates").fetchall())
        self.assertEqual([len(g) for g in groups], [2, 2])

    def test_an_item_the_answer_skips_is_asked_alone_then_left_pending(self):
        first = self.add_candidate()
        second = self.beta_customer()
        calls = []

        def answer(message, request):
            calls.append(message)
            return response([verdict(1)]) if len(calls) == 1 else response([])

        totals, _ = self.verify(answer)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.candidate(first)["status"], "linked")
        self.assertEqual(self.candidate(second)["status"], "pending")
        self.assertEqual(totals["unanswered"], 1)

    def test_a_cut_off_answer_is_asked_again_in_halves(self):
        self.add_candidate()
        self.beta_customer()
        calls = []

        def answer(message, request):
            calls.append(message)
            return response(stop="max_tokens") if len(calls) == 1 else all_supported(message, request)

        totals, _ = self.verify(answer)
        self.assertEqual((len(calls), totals["linked"]), (3, 2))

    def test_only_pending_candidates_are_checked(self):
        self.add_candidate()
        self.verify()
        totals, client = self.verify()
        self.assertEqual((totals["candidates"], len(client.calls)), (0, 0))


class JobTests(VerifierTestCase):
    def test_verify_is_queued_above_read_after_a_read_finds_candidates(self):
        self.add_candidate()
        self.assertTrue(verifier.queue_verify(self.conn, self.document, self.acme))
        priority = self.conn.execute("SELECT priority FROM jobs WHERE kind = 'verify'").fetchone()[0]
        self.assertGreater(priority, max(reader.READ_PRIORITY.values()))
        self.assertFalse(verifier.queue_verify(self.conn, self.document, self.acme))  # one open job

    def test_read_job_queues_the_verify(self):
        async def found(conn, document_id, run_id=None, **kwargs):
            self.add_candidate()
            return {"chunks": 1, "skipped": 0, "candidates": 1, "rejected": 0, "declined": 0, "deferred": None, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

        job_id, _ = jobs.enqueue(self.conn, "read", str(self.document), company_id=self.acme)
        job = jobs.claim(self.conn, "test")
        with mock.patch.object(reader, "read_document", found):
            run(reader.read_job(job, self.conn))
        self.assertEqual(self.conn.execute("SELECT key, priority FROM jobs WHERE kind = 'verify'").fetchone()[:], (str(self.document), 46))

    def test_nothing_pending_queues_nothing(self):
        self.assertFalse(verifier.queue_verify(self.conn, self.document))
        self.assertEqual(verifier.queue_unverified(self.conn), 0)
        self.add_candidate()
        self.assertEqual(verifier.queue_unverified(self.conn), 1)
        self.assertEqual(verifier.queue_unverified(self.conn), 0)

    def test_handler_returns_model_tokens_and_cost(self):
        self.add_candidate()
        jobs.enqueue(self.conn, "verify", str(self.document))
        job = jobs.claim(self.conn, "test")
        client = FakeClient(all_supported)
        with mock.patch.object(verifier.anthropic, "AsyncAnthropic", return_value=client), \
                mock.patch.object(verifier.config, "anthropic_api_key", return_value="sk-test"):
            result = run(verifier.verify_job(job, self.conn))
        self.assertEqual((result["model"], result["input_tokens"], result["output_tokens"]), ("claude-sonnet-5-5", 2000, 300))
        self.assertAlmostEqual(result["cost_usd"], (2000 * 2 + 300 * 10) / 1_000_000)
        self.assertEqual(result["notes"], "1 checked: 1 linked, 0 rejected")
        self.assertEqual(self.evidence()[0]["run_id"], job["run_id"])

    def test_link_lines_say_verified(self):
        self.add_candidate()
        self.beta_customer(kind="partnership", counterparty_role="partner")
        self.verify()
        lines = [e["text"] for e in status.log_events(self.conn, kind="links")]
        self.assertIn("Gamma Foundry Ltd. → ACME · verified", lines)
        self.assertIn("ACME ↔ Beta Corp · verified", lines)


class AttemptTests(VerifierTestCase):
    """A candidate left unchecked is tried once more after RETRY_AFTER, then left for Needs attention: never a paid loop."""
    def setUp(self):
        super().setUp()
        self.candidate_id = self.add_candidate()
        self.start = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)

    def refuse(self, at):
        client = FakeClient(lambda m, r: response(stop="refusal"))
        run(verifier.verify_document(self.conn, self.document, client=client, now_at=at))
        return client

    def test_a_declined_candidate_waits_then_is_tried_once_more_then_given_up(self):
        self.refuse(self.start)
        row = self.candidate(self.candidate_id)
        self.assertEqual((row["status"], row["verify_attempts"]), ("pending", 1))
        self.assertEqual(row["verify_after"], "2026-10-30T09:00:00Z")
        # every hourly pass before the wait is over queues nothing
        for hours in (1, 2, 24, 71):
            self.assertEqual(verifier.queue_unverified(self.conn, self.start + timedelta(hours=hours)), 0)
        self.assertEqual(verifier.queue_unverified(self.conn, self.start + timedelta(days=3, minutes=1)), 1)
        self.conn.execute("UPDATE jobs SET status = 'done' WHERE kind = 'verify'")
        self.refuse(self.start + timedelta(days=3, minutes=2))
        self.assertEqual(self.candidate(self.candidate_id)["verify_attempts"], 2)
        for days in (4, 7, 30, 365):
            self.assertEqual(verifier.queue_unverified(self.conn, self.start + timedelta(days=days)), 0)
        self.assertEqual(verifier.unchecked_count(self.conn), 1)

    def test_a_document_run_early_skips_candidates_still_waiting(self):
        self.refuse(self.start)
        client = FakeClient(all_supported)
        totals = run(verifier.verify_document(self.conn, self.document, client=client, now_at=self.start + timedelta(hours=1)))
        self.assertEqual((totals["candidates"], len(client.calls)), (0, 0))

    def test_a_skipped_item_counts_an_attempt_too(self):
        client = FakeClient(lambda m, r: response([]))
        totals = run(verifier.verify_document(self.conn, self.document, client=client, now_at=self.start))
        self.assertEqual((totals["unanswered"], len(client.calls)), (1, 2))
        self.assertEqual(self.candidate(self.candidate_id)["verify_attempts"], 1)

    def test_linked_candidates_are_not_counted(self):
        run(verifier.verify_document(self.conn, self.document, client=FakeClient(all_supported), now_at=self.start))
        self.assertEqual(self.candidate(self.candidate_id)["verify_attempts"], 0)

    def test_given_up_candidates_need_attention_and_retry_gives_fresh_attempts(self):
        self.conn.execute("UPDATE candidates SET verify_attempts = 2, verify_after = '2026-01-01T00:00:00Z'")
        attention = status.overview(self.conn)["attention"]
        self.assertEqual((attention["unchecked"], attention["total"]), (1, 1))
        self.assertEqual(status.retry(self.conn, company_id=self.acme), 1)
        row = self.candidate(self.candidate_id)
        self.assertEqual((row["verify_attempts"], row["verify_after"]), (0, None))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'verify' AND status = 'queued'").fetchone()[0], 1)

    def test_a_verify_job_that_failed_for_good_isnt_requeued_every_hour(self):
        job_id, _ = jobs.enqueue(self.conn, "verify", str(self.document), now=self.start)
        self.conn.execute("UPDATE jobs SET status = 'dead', updated_at = ? WHERE id = ?", ("2026-10-27T09:00:00Z", job_id))
        self.assertEqual(verifier.queue_unverified(self.conn, self.start + timedelta(hours=1)), 0)
        self.assertEqual(verifier.queue_unverified(self.conn, self.start + timedelta(days=3, hours=1)), 1)


if __name__ == "__main__":
    unittest.main()
