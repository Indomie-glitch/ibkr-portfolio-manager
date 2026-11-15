"""8-K exhibits (#322): which exhibit 10.x files are read, a very large one read for its commercial terms only, locators
that name the exhibit, "filed later" sentences, the backfill, and the switch the frozen evaluation set uses. No network:
the SEC client is replaced."""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sec_client
import usage_store
from supply_chain import chunker, exhibits, graph, jobs, reader, scout
from supply_chain.db import open_graph
from tests.pipeline_isolation import isolate
from tests.test_supply_chain_reader import ACME, FakeClient, party, relationship

FIXTURES = Path(__file__).parent / "fixtures" / "filings"


def run(coro):
    return asyncio.run(coro)


class DecideTests(unittest.TestCase):
    def test_allow_list_first_then_skip_list(self):
        cases = {
            "Wafer Supply Agreement, dated as of May 1, 2026, between the Company and Gamma Foundry Ltd.": ("read", None),
            "Amended and Restated Master Agreement": ("read", None),
            "Capacity Reservation Agreement": ("read", None),
            "Long-Term Purchase Agreement for HBM3E memory": ("read", None),
            "Collaboration and License Agreement": ("read", None),
            "Credit Agreement, dated as of June 9, 2026, among the Company, the lenders and JPMorgan Chase Bank, N.A.": ("skip", "financing"),
            "Indenture, dated as of August 17, 2026": ("skip", "financing"),
            "Form of Capped Call Confirmation": ("skip", "financing"),
            "Securities Purchase Agreement": ("skip", "financing"),
            "Purchase Agreement among the Company and the initial purchasers of the Notes": ("skip", "financing"),
            "Equity Distribution Agreement": ("skip", "financing"),
            "Employment Agreement with Jane Doe": ("skip", "employment"),
            "Separation Agreement and General Release": ("skip", "employment"),
            # seen on real filings of the theme companies (#322 review): legal phrases and financing that look like supply words
            "Loan Guarantee Agreement by and between Constellation Energy Generation, LLC and the U.S. Department of Energy, in its capacity as guarantor": ("skip", "financing"),
            "Receivables Purchase Agreement, dated as of July 16, 2025, by and among Super Micro Computer, Inc., MUFG Bank": ("skip", "financing"),
            "Amendment No. 4, dated as of April 29, 2026, among Entegris, as borrower, the other credit parties": ("skip", "financing"),
            "Form of Bond Hedge Confirmation.": ("skip", "financing"),
            "Unit Purchase Agreement, dated September 18, 2024": ("unclear", None),
            "Second Amendment to the Amended and Restated Preferred Distributor Agreement": ("read", None),
            "Master Services Agreement between CoreWeave, Inc. and Meta Platforms, Inc., dated December 10, 2023.": ("read", None),
            "Letter Agreement": ("unclear", None),
            None: ("unclear", None),
        }
        for description, expected in cases.items():
            with self.subTest(description=description):
                self.assertEqual(exhibits.decide(description), expected)

    def test_item_901_table_and_lines(self):
        table = ["Item 9.01 Financial Statements and Exhibits.", "(d) Exhibits",
                 "Exhibit Number | Description\n10.1* | Supply Agreement, dated May 1, 2026\n10.2 | Credit Agreement\n104 | Cover Page", "SIGNATURES"]
        self.assertEqual(exhibits.item_901_descriptions(table),
                         {"Exhibit 10.1": "Supply Agreement, dated May 1, 2026", "Exhibit 10.2": "Credit Agreement"})
        lines = chunker.load_paragraphs(FIXTURES / "8k.htm")
        self.assertEqual(exhibits.item_901_descriptions(lines), {"Exhibit 10.1": "Supply Agreement."})

    def test_filed_later(self):
        text = ["The foregoing description is qualified by the full text of the agreement, which the Company intends to file as an "
                "exhibit to its Quarterly Report on Form 10-Q for the quarter ending September 27, 2026."]
        self.assertTrue(exhibits.filed_later(text).startswith("The foregoing description"))
        self.assertIsNone(exhibits.filed_later(["A copy of the agreement is filed as Exhibit 10.1 to this report."]))

    def test_labels_from_the_index_type(self):
        self.assertEqual([exhibits.label_of(t) for t in ("EX-10.1", "EX-10", "EX-10.12", "EX-1.1", "EX-99.1", "8-K")],
                         ["Exhibit 10.1", "Exhibit 10", "Exhibit 10.12", None, None, None])


def agreement(sections=40, words=900):
    """A synthetic agreement of about sections x words: an opening, definitions and numbered sections."""
    filler = " ".join(["the parties shall perform their obligations under this agreement in good faith"] * (words // 12))
    paragraphs = ['MASTER SUPPLY AGREEMENT',
                  'This Master Supply Agreement is made between Gamma Foundry Ltd. ("Supplier") and Acme Semiconductor Inc. ("Buyer").',
                  'NOW, THEREFORE, the parties agree as follows:']
    titles = {3: "Term", 7: "Pricing", 11: "Capacity", 15: "Most Favored Customer", 19: "Termination"}
    for n in range(1, sections + 1):
        paragraphs.append(f"{n}. {titles.get(n, f'General Provision {n}')}. {filler}")
    paragraphs.insert(4, '"Products" means the wafers listed in Schedule A.')
    return paragraphs


class PlanTests(unittest.TestCase):
    def test_a_normal_exhibit_is_read_whole(self):
        section, note = chunker.exhibit_plan(agreement(sections=5), "Exhibit 10.1")
        self.assertIsNone(note)
        self.assertEqual(len(section.paragraphs), 9)

    def test_a_very_large_exhibit_is_read_for_its_parties_and_commercial_terms(self):
        paragraphs = agreement(sections=60, words=12_000)
        self.assertGreater(chunker.estimate_tokens("\n\n".join(paragraphs)), chunker.EXHIBIT_FULL_TOKENS)
        section, note = chunker.exhibit_plan(paragraphs, "Exhibit 10.1")
        kept = [paragraphs[i][:30] for i in section.paragraphs]
        self.assertIn('This Master Supply Agreement', " ".join(kept))  # the parties
        self.assertTrue(any(k.startswith('"Products" means') for k in kept))  # a definition
        for title in ("3. Term", "7. Pricing", "11. Capacity", "15. Most Favored", "19. Termination"):
            self.assertTrue(any(k.startswith(title) for k in kept), title)
        self.assertFalse(any(k.startswith("4. General") for k in kept))
        self.assertIn("5 of 60 sections", note)
        self.assertIn("left out 55 paragraphs", note)

    def test_headings_name_the_section(self):
        under, titles = chunker.agreement_headings(["Opening", "Section 4.2 Term. This agreement runs to 2030.", "It renews yearly.",
                                                    "ARTICLE V PRICING", "4.3 Prices. Fixed."])
        self.assertEqual(under, [None, "Section 4.2", "Section 4.2", "Article V", "Section 4.3"])
        self.assertEqual(titles[1], "Term")


class ExhibitCase(unittest.TestCase):
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
        self.gamma = graph.add_company(self.conn, "Gamma Foundry Ltd.")
        self.folder = root / "filings" / "1" / "000000000126000001"
        self.folder.mkdir(parents=True)
        shutil.copy(FIXTURES / "8k.htm", self.folder / "8k.htm")
        self.document = graph.add_document(self.conn, "sec", "8-K", "0000000001-26-000001/8k.htm", "https://www.sec.gov/x", company_id=self.acme,
                                           title="8-K 2026-05-02", filed_at="2026-05-02", period_end="2026-05-01", status="downloaded")
        self.conn.execute("UPDATE documents SET local_path = ? WHERE id = ?", (str(self.folder / "8k.htm"), self.document))
        self.files = {"ex10-1.htm": (FIXTURES / "ex10-1.htm").read_bytes(), "ex10-2.htm": b"<p>CREDIT AGREEMENT among the lenders.</p>",
                      "ex10-3.htm": b"<p>" + b"LETTER AGREEMENT terms and conditions. " * 9000 + b"</p>"}
        self.index = [{"name": "8k.htm", "type": "8-K", "description": "8-K"},
                      {"name": "ex10-1.htm", "type": "EX-10.1", "description": "EX-10.1"},
                      {"name": "ex10-2.htm", "type": "EX-10.2", "description": "Credit Agreement"},
                      {"name": "ex10-3.htm", "type": "EX-10.3", "description": "EX-10.3"},
                      {"name": "ex99-1.htm", "type": "EX-99.1", "description": "Press release"}]
        self.downloaded = []

        async def download(cik, accession, filename, folder=None):
            self.downloaded.append(filename)
            path = Path(folder) / filename
            path.write_bytes(self.files[filename])
            return {"path": str(path), "sha256": "ab" * 32, "size": len(self.files[filename]), "url": "u"}

        async def filing_index(cik, accession):
            return self.index

        for name, fake in (("download", download), ("filing_index", filing_index)):
            p = mock.patch.object(sec_client, name, fake)
            p.start()
            self.addCleanup(p.stop)

    def fetch(self):
        return run(exhibits.fetch_exhibits(self.conn, self.document, 1, "0000000001-26-000001", "8k.htm"))

    def files_rows(self):
        return {r["label"]: dict(r) for r in self.conn.execute("SELECT * FROM document_files")}


class FetchTests(ExhibitCase):
    def test_each_exhibit_is_decided_and_recorded(self):
        outcome = self.fetch()
        rows = self.files_rows()
        self.assertEqual(rows["Exhibit 10.1"]["decision"], "read")  # "Supply Agreement." from Item 9.01
        self.assertEqual(rows["Exhibit 10.1"]["description"], "Supply Agreement.")
        self.assertEqual((rows["Exhibit 10.2"]["decision"], rows["Exhibit 10.2"]["reason"]), ("skipped", "financing"))
        self.assertEqual((rows["Exhibit 10.3"]["decision"], rows["Exhibit 10.3"]["reason"]), ("skipped", "unclear description"))
        self.assertNotIn("Exhibit 99.1", rows)
        self.assertEqual(self.downloaded, ["ex10-1.htm", "ex10-3.htm"])  # the credit agreement isn't downloaded
        self.assertFalse((self.folder / "ex10-3.htm").exists())  # unclear and over 30,000 tokens: removed again
        self.assertIn("skipped Exhibit 10.2 (financing)", exhibits.describe(outcome))
        self.fetch()  # looked at once only
        self.assertEqual(self.downloaded, ["ex10-1.htm", "ex10-3.htm"])

    def test_the_job_queues_the_read_again_and_the_exhibit_is_read_with_its_locator(self):
        jobs.enqueue(self.conn, "read", str(self.document), {"form": "8-K"})
        self.conn.execute("UPDATE jobs SET status = 'done' WHERE kind = 'read'")  # read before its exhibits arrived
        job = {"key": str(self.document), "company_id": self.acme,
               "payload": {"cik": 1, "accession": "0000000001-26-000001", "filename": "8k.htm", "items": ["1.01"]}}
        result = run(exhibits.exhibits_job(job, self.conn))
        self.assertIn("read Exhibit 10.1", result["notes"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'read' AND status = 'queued'").fetchone()[0], 1)

        quote = "1. Supplier shall manufacture the wafers."
        answer = relationship(party("Gamma Foundry Ltd."), ACME, "supplier", quote, what="wafers")
        names = {"Gamma Foundry Ltd.": self.gamma}

        async def resolve(conn, name):
            return {"status": "matched", "company_id": names[name], "method": "identifier_store"} if name in names else {"status": "skipped", "reason": "no_match"}
        run(reader.read_document(self.conn, self.document, client=FakeClient({"Exhibit 10.1": [answer]}), resolve=resolve))
        candidate = self.conn.execute("SELECT locator FROM candidates").fetchone()
        self.assertEqual(candidate["locator"], f"Exhibit 10.1, Section 1, paragraph 3 [chunker v{chunker.CHUNKER_VERSION}]")

    def test_the_main_document_only_when_exhibits_are_off(self):
        self.fetch()
        client = FakeClient({})
        run(reader.read_document(self.conn, self.document, client=client, resolve=None, exhibits=False))
        sections = [next(l for l in c["messages"][0]["content"].split("\n") if l.startswith("Section: ")) for c in client.calls]
        self.assertFalse(any("Exhibit" in s for s in sections))

    def test_filed_later_is_recorded(self):
        (self.folder / "8k.htm").write_text("<p>Item 1.01 Entry into a Material Definitive Agreement.</p><p>The Company intends to file the "
                                            "agreement as an exhibit to its Annual Report on Form 10-K for the year ending December 31, 2026.</p>")
        self.index = self.index[:1]
        outcome = self.fetch()
        self.assertTrue(outcome["filed_later"])
        self.assertIn("Form 10-K", self.conn.execute("SELECT filed_later FROM documents").fetchone()[0])
        self.assertEqual(exhibits.describe(outcome), "agreement to be filed with a later report")


class QueueTests(ExhibitCase):
    def payload(self, items):
        return {"document_id": self.document, "cik": 1, "accession": "0000000001-26-000001", "filename": "8k.htm", "form": "8-K", "items": items}

    def test_the_download_job_queues_exhibits_before_the_read(self):
        self.conn.execute("UPDATE documents SET status = 'discovered' WHERE id = ?", (self.document,))
        with mock.patch.object(scout.sec, "fetch_document", mock.AsyncMock(return_value="ab" * 32)):
            run(scout.download_job({"payload": self.payload(["1.01", "9.01"]), "company_id": self.acme}, self.conn))
        kinds = [r[0] for r in self.conn.execute("SELECT kind FROM jobs")]
        self.assertEqual(kinds, ["exhibits"])

    def test_an_8k_about_something_else_is_queued_as_before(self):
        with mock.patch.object(scout.sec, "fetch_document", mock.AsyncMock(return_value="ab" * 32)):
            run(scout.download_job({"payload": self.payload(["2.02"]), "company_id": self.acme}, self.conn))
        self.assertEqual([r[0] for r in self.conn.execute("SELECT kind FROM jobs")], [])  # not read: no agreement

    def test_backfill_queues_old_8ks_with_an_agreement_once(self):
        jobs.enqueue(self.conn, "download", "0000000001-26-000001/8k.htm", self.payload(["1.01"]), document_id=self.document)
        self.conn.execute("UPDATE jobs SET status = 'done'")
        self.assertEqual(exhibits.queue_backfill(self.conn), 1)
        self.assertEqual(exhibits.queue_backfill(self.conn), 0)
        payload = json.loads(self.conn.execute("SELECT payload FROM jobs WHERE kind = 'exhibits'").fetchone()[0])
        self.assertEqual(payload["accession"], "0000000001-26-000001")
        self.assertEqual(reader.queue_unread(self.conn), 0)  # its read waits for the exhibits job


class RedactionTests(unittest.TestCase):
    def test_the_prompt_says_a_redacted_value_is_hidden(self):
        text = " ".join(reader.SYSTEM_PROMPT.split())
        self.assertIn('"[***]", "[REDACTED]"', text)
        self.assertIn('never treat it as zero: if the share or price is redacted, leave it null and put "redacted" in share_as_written', text)
