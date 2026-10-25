import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import usage_store
from supply_chain import graph, integrity, jobs, reader, scout
from supply_chain.db import open_graph
from supply_chain.worker import Permanent

FIXTURES = Path(__file__).parent / "fixtures" / "filings"


def run(coro):
    return asyncio.run(coro)


def party(name, is_filer=False, unnamed=False):
    return {"name": name, "is_filer": is_filer, "unnamed": unnamed}


def relationship(supplier, customer, role, quote, **fields):
    answer = {"supplier": supplier, "customer": customer, "counterparty_role": role, "what": None, "quote": quote,
              "supplier_revenue_share": None, "customer_supply_share": None, "customer_share_scope": None, "share_as_written": None,
              "period_as_written": None, "stated_on": None, "ended": False}
    answer.update(fields)
    return answer


ACME = party("Acme Semiconductor Inc.", is_filer=True)
BETA_BUYS = relationship(ACME, party("Beta Corp"), "customer",
                         "Our largest customer, Beta Corp, buys most of our output.", what="chips")
GAMMA_SUPPLIES = relationship(party("Gamma Foundry"), ACME, "supplier",
                              "We rely on Gamma Foundry to manufacture our wafers.", what="wafers")


def response(answer=None, stop="end_turn", input_tokens=1000, output_tokens=200):
    content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps({"relationships": answer or []}))]
    return SimpleNamespace(stop_reason=stop, usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
                           content=content if stop in ("end_turn", "max_tokens") else [])


class FakeClient:
    """Answers by the section named in the message: {section prefix: [relationships] or a callable(message) -> response}."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []
        self.messages = self

    async def create(self, **request):
        message = request["messages"][0]["content"]
        self.calls.append(request)
        section = next(line for line in message.split("\n") if line.startswith("Section: "))[len("Section: "):]
        for prefix, answer in self.answers.items():
            if section.startswith(prefix):
                return answer(message) if callable(answer) else response(answer)
        return response([])


class ReaderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.conn = open_graph(root / "g.sqlite")
        self.addCleanup(self.conn.close)
        usage_patch = mock.patch.object(usage_store, "DB_PATH", root / "usage.sqlite")
        usage_patch.start()
        self.addCleanup(usage_patch.stop)
        self.acme = graph.add_company(self.conn, "Acme Semiconductor Inc.")
        graph.add_identifier(self.conn, self.acme, "ticker", "ACME", "US")
        self.beta = graph.add_company(self.conn, "Beta Corp")
        self.gamma = graph.add_company(self.conn, "Gamma Foundry Ltd.")
        folder = root / "filings" / "1" / "0001"
        folder.mkdir(parents=True)
        shutil.copy(FIXTURES / "tenk.htm", folder / "tenk.htm")
        self.document = self.add_document("10-K", folder / "tenk.htm")
        self.names = {"Beta Corp": self.beta, "Gamma Foundry": self.gamma, "Gamma Foundry Ltd.": self.gamma, "Acme": self.acme}
        self.lookups = []

    def add_document(self, form, path, status="downloaded"):
        document = graph.add_document(self.conn, "sec", form, f"0001/{path.name}/{form}", "https://www.sec.gov/x", company_id=self.acme,
                                      title=f"{form} 2026-02-25", filed_at="2026-02-25", period_end="2026-01-25", status=status)
        self.conn.execute("UPDATE documents SET local_path = ? WHERE id = ?", (str(path), document))
        return document

    async def resolve(self, conn, name):
        self.lookups.append(name)
        if name == "Lookup Down":
            return {"status": "unavailable", "detail": "OpenFIGI didn't answer"}
        if name in self.names:
            return {"status": "matched", "company_id": self.names[name], "method": "identifier_store"}
        return {"status": "skipped", "reason": "no_match", "detail": "no company with this name"}

    def read(self, answers, document=None):
        client = FakeClient(answers)
        totals = run(reader.read_document(self.conn, document or self.document, client=client, resolve=self.resolve))
        return totals, client

    def candidates(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM candidates ORDER BY id")]

    def rejected(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM rejected ORDER BY id")]


class DirectionTests(ReaderTestCase):
    def test_customer_and_supplier_of_the_filer(self):
        totals, client = self.read({"Item 1. Business": [BETA_BUYS, GAMMA_SUPPLIES]})
        self.assertEqual(totals["chunks"], 4)
        self.assertEqual(len(client.calls), 4)
        beta, gamma = self.candidates()
        self.assertEqual((beta["supplier_id"], beta["customer_id"], beta["kind"], beta["counterparty_role"]), (self.acme, self.beta, "supplies", "customer"))
        self.assertEqual((beta["supplier_name"], beta["customer_name"]), ("Acme Semiconductor Inc.", "Beta Corp"))
        self.assertEqual((gamma["supplier_id"], gamma["customer_id"], gamma["what"]), (self.gamma, self.acme, "wafers"))
        self.assertEqual(beta["status"], "pending")
        self.assertEqual(beta["resolved_by"], "identifier_store")

    def test_locator_is_the_quote_paragraph_and_context_its_neighbours(self):
        self.read({"Item 1. Business": [BETA_BUYS]})
        row = self.candidates()[0]
        self.assertEqual(row["locator"], "Item 1. Business, paragraph 5 [chunker v1]")
        self.assertIn("Acme designs chips.", row["context"])
        self.assertIn("Business", row["context"].split("\n\n")[0])  # the paragraph before
        self.assertIn("founded in 1999", row["context"])  # and after

    def test_a_partnership_is_stored_with_the_filer_as_supplier(self):
        partner = relationship(party("Beta Corp"), ACME, "partner", "Our largest customer, Beta Corp, buys most of our output.")
        self.read({"Item 1. Business": [partner]})
        row = self.candidates()[0]
        self.assertEqual((row["kind"], row["supplier_id"], row["customer_id"]), ("partnership", self.acme, self.beta))

    def test_role_that_disagrees_with_the_direction_is_rejected(self):
        wrong = dict(BETA_BUYS, counterparty_role="supplier")
        self.read({"Item 1. Business": [wrong]})
        self.assertEqual(self.candidates(), [])
        self.assertEqual(self.rejected()[0]["reason"], "direction_mismatch")
        self.assertEqual(self.rejected()[0]["rejected_by"], "rule")

    def test_a_relationship_not_involving_the_filer_is_rejected(self):
        third = relationship(party("Gamma Foundry"), party("Beta Corp"), "supplier", "We rely on Gamma Foundry to manufacture our wafers.")
        both = relationship(ACME, ACME, "customer", "We rely on Gamma Foundry to manufacture our wafers.")
        self.read({"Item 1. Business": [third, both]})
        self.assertEqual([r["reason"] for r in self.rejected()], ["not_about_filer", "not_about_filer"])


class QuoteTests(ReaderTestCase):
    def test_a_made_up_quote_is_rejected(self):
        made_up = dict(BETA_BUYS, quote="Beta Corp is our exclusive customer for all products.")
        self.read({"Item 1. Business": [made_up]})
        self.assertEqual(self.candidates(), [])
        row = self.rejected()[0]
        self.assertEqual((row["reason"], row["customer_name"], row["document_id"]), ("quote_not_found", "Beta Corp", self.document))
        self.assertEqual(json.loads(row["payload"])["quote"], made_up["quote"])

    def test_curly_quotes_and_spacing_still_match(self):
        spaced = dict(BETA_BUYS, quote="Our  largest customer,\nBeta Corp, buys most of our output.")
        self.read({"Item 1. Business": [spaced]})
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(self.candidates()[0]["quote"], "Our largest customer, Beta Corp, buys most of our output.")

    def test_a_different_word_is_not_normalised_away(self):
        self.read({"Item 1. Business": [dict(BETA_BUYS, quote="Our biggest customer, Beta Corp, buys most of our output.")]})
        self.assertEqual(self.rejected()[0]["reason"], "quote_not_found")

    def test_no_quote_at_all(self):
        self.read({"Item 1. Business": [dict(BETA_BUYS, quote="")]})
        self.assertEqual((self.rejected()[0]["reason"], self.rejected()[0]["quote"]), ("quote_not_found", "(no quote given)"))

    def test_a_table_row_counts_as_a_quote(self):
        row_quote = relationship(ACME, party("Beta Corp"), "customer", "Beta Corp | 48%", supplier_revenue_share=48)
        self.read({"Item 8": [row_quote]})
        row = self.candidates()[0]
        self.assertEqual((row["supplier_revenue_share"], row["share_dropped"]), (48.0, None))
        self.assertTrue(row["locator"].startswith("Item 8. Financial Statements, notes: Revenue; Concentration of Customers, paragraph"))

    def test_the_counterparty_must_be_named_in_the_passage(self):
        elsewhere = dict(BETA_BUYS, customer=party("Delta Systems"))
        self.read({"Item 1. Business": [elsewhere]})
        self.assertEqual(self.rejected()[0]["reason"], "name_not_in_text")
        self.assertEqual(self.lookups, [])


class ShareTests(ReaderTestCase):
    def test_a_share_not_in_the_quote_is_dropped_but_the_link_kept(self):
        guessed = dict(BETA_BUYS, supplier_revenue_share=48)
        self.read({"Item 1. Business": [guessed]})
        row = self.candidates()[0]
        self.assertIsNone(row["supplier_revenue_share"])
        self.assertEqual(row["share_dropped"], "supplier_revenue_share: digits_not_in_quote")
        self.assertEqual(self.rejected(), [])

    def test_out_of_range_share_and_its_scope_are_dropped(self):
        silly = dict(GAMMA_SUPPLIES, customer_supply_share=140, customer_share_scope="wafers")
        self.read({"Item 1. Business": [silly]})
        row = self.candidates()[0]
        self.assertEqual((row["customer_supply_share"], row["customer_share_scope"]), (None, None))
        self.assertEqual(row["share_dropped"], "customer_supply_share: out_of_range")

    def test_words_instead_of_a_number_are_kept_as_written(self):
        self.read({"Item 1. Business": [dict(BETA_BUYS, share_as_written="most of our output")]})
        self.assertEqual(self.candidates()[0]["share_as_written"], "most of our output")

    def test_digits_check(self):
        self.assertTrue(reader.share_in_quote(48.0, "48% of revenue"))
        self.assertTrue(reader.share_in_quote(12.5, "12.5 percent"))
        self.assertTrue(reader.share_in_quote(48, "48.0%"))
        self.assertFalse(reader.share_in_quote(48, "148% growth"))
        self.assertFalse(reader.share_in_quote(48, "1.48 billion"))
        self.assertFalse(reader.share_in_quote(30, "a third of revenue"))


class CounterpartyTests(ReaderTestCase):
    def test_unnamed_customer_kept_without_a_company_and_not_looked_up(self):
        quote = "Sales to our largest customer, Beta Corp, were 48% of revenue, up from 41% a year ago."
        unnamed = relationship(ACME, party("Customer A", unnamed=True), "customer", quote, supplier_revenue_share=48,
                               period_as_written="fiscal 2026", stated_on="2026-01-25")
        self.read({"Item 7": [unnamed]})
        row = self.candidates()[0]
        self.assertEqual((row["customer_name"], row["customer_unnamed"], row["customer_id"], row["supplier_id"]), ("Customer A", 1, None, self.acme))
        self.assertEqual((row["supplier_revenue_share"], row["stated_on"]), (48.0, "2026-01-25"))
        self.assertEqual(self.lookups, [])

    def test_a_label_the_model_didnt_flag_is_still_unnamed(self):
        quote = "Sales to our largest customer, Beta Corp, were 48% of revenue, up from 41% a year ago."
        self.read({"Item 7": [relationship(ACME, party("Customer A"), "customer", quote)]})
        self.assertEqual(self.candidates()[0]["customer_unnamed"], 1)

    def test_a_group_is_rejected(self):
        self.read({"Item 1. Business": [dict(BETA_BUYS, customer=party("our customers")),
                                        dict(BETA_BUYS, customer=party("top ten customers", unnamed=True))]})
        self.assertEqual([r["reason"] for r in self.rejected()], ["generic_counterparty", "generic_counterparty"])
        self.assertEqual(self.candidates(), [])

    def test_a_name_the_resolver_cant_match_is_rejected(self):
        self.names.pop("Gamma Foundry")
        self.read({"Item 1. Business": [GAMMA_SUPPLIES]})
        row = self.rejected()[0]
        self.assertEqual((row["reason"], row["supplier_name"], row["customer_name"]), ("unresolved_company", "Gamma Foundry", "Acme Semiconductor Inc."))
        self.assertIn("no_match", row["detail"])

    def test_a_name_that_resolves_to_the_filer_is_rejected(self):
        self.names["Beta Corp"] = self.acme
        self.read({"Item 1. Business": [BETA_BUYS]})
        self.assertEqual(self.rejected()[0]["reason"], "same_company")

    def test_bad_date_is_dropped(self):
        self.read({"Item 1. Business": [dict(BETA_BUYS, stated_on="fiscal 2026")]})
        self.assertIsNone(self.candidates()[0]["stated_on"])

    def test_ended_is_kept(self):
        self.read({"Item 1. Business": [dict(GAMMA_SUPPLIES, ended=True)]})
        self.assertEqual(self.candidates()[0]["ended"], 1)


class StoreTests(ReaderTestCase):
    def test_the_same_relationship_twice_is_saved_once(self):
        totals, _ = self.read({"Item 1. Business": [BETA_BUYS, dict(BETA_BUYS)]})
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(totals["candidates"], 1)

    def test_readers_never_write_relationships(self):
        self.read({"Item 1. Business": [BETA_BUYS, GAMMA_SUPPLIES]})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 0)
        self.assertEqual(integrity.check(self.conn), [])

    def test_document_marked_processed_and_chunks_recorded(self):
        self.read({"Item 1. Business": [BETA_BUYS]})
        self.assertEqual(self.conn.execute("SELECT status FROM documents WHERE id = ?", (self.document,)).fetchone()[0], "processed")
        reads = self.conn.execute("SELECT chunk_number, found, input_tokens, model FROM chunk_reads ORDER BY chunk_number").fetchall()
        self.assertEqual([tuple(r) for r in reads], [(1, 1, 1000, "claude-haiku-5-5"), (2, 0, 1000, "claude-haiku-5-5"),
                                                     (3, 0, 1000, "claude-haiku-5-5"), (4, 0, 1000, "claude-haiku-5-5")])

    def test_a_retried_job_skips_the_chunks_it_read(self):
        original = self.resolve

        async def flaky(conn, name):
            if name == "Beta Corp":
                return {"status": "unavailable", "detail": "OpenFIGI didn't answer"}
            return await original(conn, name)

        client = FakeClient({"Item 1A": [relationship(party("Gamma Foundry Ltd."), ACME, "supplier",
                                                       "We depend on a single supplier, Gamma Foundry Ltd., for substantially all of our wafers.")],
                             "Item 7": [relationship(ACME, party("Beta Corp"), "customer",
                                                     "Sales to our largest customer, Beta Corp, were 48% of revenue, up from 41% a year ago.")]})
        with self.assertRaises(RuntimeError):
            run(reader.read_document(self.conn, self.document, client=client, resolve=flaky))
        self.assertEqual(len(client.calls), 3)  # Item 1 and 1A saved, Item 7 failed on the lookup
        self.names["Beta Corp"] = self.beta
        run(reader.read_document(self.conn, self.document, client=client, resolve=self.resolve))
        self.assertEqual(len(client.calls), 5)  # only Item 7 again, and Item 8
        self.assertEqual({r["supplier_id"] for r in self.candidates()}, {self.gamma, self.acme})

    def test_document_not_downloaded(self):
        other = self.add_document("10-K", Path(self.tmp.name) / "missing.htm", status="discovered")
        with self.assertRaises(Permanent):
            run(reader.read_document(self.conn, other, client=FakeClient({}), resolve=self.resolve))


class CallTests(ReaderTestCase):
    def test_request_shape(self):
        _, client = self.read({})
        request = client.calls[0]
        self.assertEqual(request["model"], "claude-haiku-5-5")
        self.assertEqual(request["output_config"]["effort"], "medium")
        self.assertEqual(request["output_config"]["format"]["type"], "json_schema")
        message = request["messages"][0]["content"]
        self.assertIn("Filer: Acme Semiconductor Inc. (ACME)", message)
        self.assertIn("Form: 10-K, filed 2026-02-25, period 2026-01-25", message)
        self.assertIn("Section: Item 1. Business, paragraphs 3-6 [chunker v1]", message)
        self.assertIn("Acme designs chips.", message)
        self.assertIn("never add anything from your own knowledge", request["system"].lower())
        self.assertIn('"Beta Corp | 48%"', request["system"])

    def test_cut_off_answer_is_read_again_in_halves(self):
        calls = []

        def answer(message):
            calls.append(message)
            if len(calls) == 1:
                return response([], stop="max_tokens")
            return response([BETA_BUYS] if "Beta Corp, buys" in message else [])

        totals, client = self.read({"Item 1. Business": answer})
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(self.candidates()[0]["locator"], "Item 1. Business, paragraph 5 [chunker v1]")
        self.assertEqual(self.conn.execute("SELECT input_tokens FROM chunk_reads WHERE chunk_number = 1").fetchone()[0], 3000)

    def test_a_refusal_reads_as_nothing_found(self):
        totals, _ = self.read({"Item 1. Business": lambda m: response(stop="refusal")})
        self.assertEqual(totals["declined"], 1)
        self.assertEqual(self.candidates(), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM chunk_reads").fetchone()[0], 4)

    def test_usage_logged_and_cost_returned_for_the_run(self):
        job_id, _ = jobs.enqueue(self.conn, "read", str(self.document))
        job = jobs.claim(self.conn, "test")
        client = FakeClient({"Item 1. Business": [BETA_BUYS]})
        with mock.patch.object(reader.resolver, "resolve", self.resolve), mock.patch.object(reader.anthropic, "AsyncAnthropic", return_value=client), \
                mock.patch.object(reader.config, "anthropic_api_key", return_value="sk-test"):
            result = run(reader.read_job(job, self.conn))
        self.assertEqual((result["model"], result["input_tokens"], result["output_tokens"]), ("claude-haiku-5-5", 4000, 800))
        self.assertAlmostEqual(result["cost_usd"], (4000 * 0.10 + 800 * 0.50) / 1_000_000)
        self.assertIn("4 chunks (0 read before), 1 candidates, 0 rejected", result["notes"])
        month = usage_store.monthly()
        self.assertEqual(month["by_feature"]["supply_chain_reader"]["calls"], 4)
        self.assertEqual(self.conn.execute("SELECT run_id FROM candidates").fetchone()[0], job["run_id"])

    def test_no_api_key(self):
        with mock.patch.object(reader.config, "anthropic_api_key", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "no Anthropic API key"):
                run(reader.read_document(self.conn, self.document, resolve=self.resolve))


class QueueTests(ReaderTestCase):
    def test_forms_worth_reading(self):
        self.assertTrue(reader.should_read("10-K"))
        self.assertTrue(reader.should_read("20-F"))
        self.assertTrue(reader.should_read("8-K", ["1.01", "9.01"]))
        self.assertTrue(reader.should_read("8-K", ["1.02"]))
        self.assertTrue(reader.should_read("8-K", None))  # items unknown: the chunker decides
        self.assertFalse(reader.should_read("8-K", ["2.02", "9.01"]))
        self.assertFalse(reader.should_read("10-Q"))
        self.assertFalse(reader.should_read("6-K"))

    def test_a_finished_download_queues_the_read(self):
        job_id, _ = jobs.enqueue(self.conn, "download", "0001/tenk.htm", {"document_id": self.document, "cik": "1", "accession": "0001",
                                                                          "filename": "tenk.htm", "form": "10-K", "items": []}, company_id=self.acme)
        job = jobs.claim(self.conn, "test")

        async def fetched(*args):
            return "ab" * 32

        with mock.patch.object(scout.sec, "fetch_document", fetched):
            run(scout.download_job(job, self.conn))
        row = self.conn.execute("SELECT priority, company_id, document_id FROM jobs WHERE kind = 'read' AND key = ?", (str(self.document),)).fetchone()
        self.assertEqual(tuple(row), (45, self.acme, self.document))

    def test_an_8k_about_results_is_not_queued(self):
        eight = self.add_document("8-K", Path(self.tmp.name) / "8k.htm")
        self.assertFalse(reader.queue_read(self.conn, eight, "8-K", ["2.02", "9.01"]))
        self.assertTrue(reader.queue_read(self.conn, eight, "8-K", ["1.01"]))
        self.assertEqual(self.conn.execute("SELECT priority FROM jobs WHERE kind = 'read'").fetchone()[0], 40)

    def test_queued_once_and_backfill(self):
        self.assertEqual(reader.queue_unread(self.conn), 1)
        self.assertEqual(reader.queue_unread(self.conn), 0)
        self.assertFalse(reader.queue_read(self.conn, self.document, "10-K"))


if __name__ == "__main__":
    unittest.main()
