import asyncio
import tempfile
from xml.sax.saxutils import escape
import unittest
from pathlib import Path
from unittest import mock

import sec_client
from supply_chain import graph, integrity, scout, xbrl
from supply_chain.db import open_graph

# A cut-down 10-K instance in the shape EDGAR's _htm.xml files have
CONTEXTS = {
    # id: (start, end, {axis: member})
    "rev26a": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:CustomerAMember",
                                            "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:RevenueFromContractWithCustomerMember",
                                            "us-gaap:ConcentrationRiskByTypeAxis": "us-gaap:CustomerConcentrationRiskMember"}),
    "ar26a": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:CustomerAMember",
                                           "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:AccountsReceivableMember",
                                           "us-gaap:ConcentrationRiskByTypeAxis": "us-gaap:CustomerConcentrationRiskMember"}),
    "rev25a": ("2024-01-29", "2025-01-26", {"srt:MajorCustomersAxis": "nvda:CustomerAMember",
                                            "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember",
                                            "us-gaap:ConcentrationRiskByTypeAxis": "us-gaap:CustomerConcentrationRiskMember"}),
    "apple26": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:AppleIncMember",
                                             "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
    "apple25": ("2024-01-29", "2025-01-26", {"srt:MajorCustomersAxis": "nvda:AppleIncMember",
                                             "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
    "luxshare": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:LuxshareMember",
                                              "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:AccountsReceivableMember"}),
    "top10": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:TopTenCustomersMember",
                                           "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
    "region": ("2025-01-27", "2026-01-25", {"us-gaap:StatementGeographicalAxis": "country:TW",
                                            "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
    "endcust": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:EndCustomerMember", "us-gaap:StatementGeographicalAxis": "country:TW",
                                             "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
    "segment": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:CustomerBMember", "us-gaap:StatementBusinessSegmentsAxis": "nvda:ComputeMember",
                                             "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
    "supplier": ("2025-01-27", "2026-01-25", {"nvda:ConcentrationRiskBySupplierAxis": "nvda:SupplierOneMember",
                                              "us-gaap:ConcentrationRiskByBenchmarkAxis": "nvda:PurchasesTotalMember",
                                              "us-gaap:ConcentrationRiskByTypeAxis": "us-gaap:SupplierConcentrationRiskMember"}),
    "vendor": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:VendorMember",
                                            "us-gaap:ConcentrationRiskByBenchmarkAxis": "nvda:ManufacturerConcentrationMember"}),
    "pair": ("2025-01-27", "2026-01-25", {"srt:MajorCustomersAxis": "nvda:AblecomAndCompuwareMember",
                                          "us-gaap:ConcentrationRiskByBenchmarkAxis": "us-gaap:SalesRevenueNetMember"}),
}
FACTS = [  # (id, context, value, decimals)
    ("f1", "rev26a", "0.22", "2"), ("f2", "ar26a", "0.25", "2"), ("f3", "rev25a", "0.12", "2"),
    ("f4", "apple26", "0.91", "2"), ("f5", "apple25", "0.89", "2"), ("f6", "luxshare", "0.27", "2"), ("f7", "top10", "0.96", "2"),
    ("f8", "region", "0.31", "2"), ("f9", "endcust", "0.76", "2"), ("f10", "segment", "0.14", "2"), ("f11", "supplier", "0.631", "3"),
    ("f12", "vendor", "0.18", "2"), ("f13", "pair", "0.05", "2"),
    ("f14", "rev26a", "0.2213", "4"),  # the same figure again, more precisely
]
LABELS = {"CustomerAMember": "Customer A", "AppleIncMember": "Apple, Inc.", "LuxshareMember": "Luxshare", "TopTenCustomersMember": "Top Ten Customers",
          "EndCustomerMember": "End Customer", "CustomerBMember": "Customer B", "ComputeMember": "Compute & Networking",
          "SupplierOneMember": "Supplier A", "PurchasesTotalMember": "Purchases, Total", "VendorMember": "Vendor",
          "AblecomAndCompuwareMember": "Ablecom and Compuware"}


def instance_xml(contexts=CONTEXTS, facts=FACTS):
    parts = ['<?xml version="1.0"?><xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
             ' xmlns:us-gaap="http://fasb.org/us-gaap/2025">']
    for cid, (start, end, dims) in contexts.items():
        members = "".join(f'<xbrldi:explicitMember dimension="{a}">{m}</xbrldi:explicitMember>' for a, m in dims.items())
        period = f"<startDate>{start}</startDate><endDate>{end}</endDate>" if start else f"<instant>{end}</instant>"
        parts.append(f'<context id="{cid}"><entity><identifier scheme="http://www.sec.gov/CIK">1</identifier><segment>{members}</segment></entity>'
                     f'<period>{period}</period></context>')
    for fid, cid, value, decimals in facts:
        parts.append(f'<us-gaap:ConcentrationRiskPercentage1 id="{fid}" contextRef="{cid}" decimals="{decimals}" unitRef="number">{value}'
                     '</us-gaap:ConcentrationRiskPercentage1>')
    parts.append('<us-gaap:Revenues contextRef="rev26a" decimals="-6" unitRef="usd">1000</us-gaap:Revenues></xbrl>')
    return "".join(parts).encode()


def labels_xml(labels=LABELS):
    parts = ['<?xml version="1.0"?><linkbase xmlns="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink">'
             '<labelLink xlink:type="extended">']
    for i, (element, text) in enumerate(labels.items()):
        parts.append(f'<loc xlink:type="locator" xlink:href="nvda.xsd#nvda_{element}" xlink:label="loc{i}"/>'
                     f'<label xlink:type="resource" xlink:label="lab{i}" xlink:role="http://www.xbrl.org/2003/role/label">{escape(text)} [Member]</label>'
                     f'<label xlink:type="resource" xlink:label="lab{i}" xlink:role="http://www.xbrl.org/2003/role/terseLabel">{escape(text)}</label>'
                     f'<labelArc xlink:type="arc" xlink:from="loc{i}" xlink:to="lab{i}"/>')
    parts.append("</labelLink></linkbase>")
    return "".join(parts).encode()


def run(coro):
    return asyncio.run(coro)


class Reading(unittest.TestCase):
    def test_labels_prefer_the_terse_one(self):
        labels = xbrl.parse_labels(labels_xml())
        self.assertEqual(labels["nvda_AppleIncMember"], "Apple, Inc.")

    def test_standard_label_without_member_suffix(self):
        content = labels_xml().replace(b"/terseLabel", b"/documentation")
        self.assertEqual(xbrl.parse_labels(content)["nvda_CustomerAMember"], "Customer A")

    def test_humanize_without_a_label(self):
        self.assertEqual(xbrl.humanize("nvda:CustomerOneMember"), "Customer One")
        self.assertEqual(xbrl.humanize("intc:HPInc.Member"), "HP Inc.")
        self.assertEqual(xbrl.humanize("crus:AppleIncMember"), "Apple Inc")

    def test_classify(self):
        for label in ("Customer A", "Customer one", "Major Customer One", "Undisclosed Customer 1", "Two Customer", "Top Customer One",
                      "Supplier A", "Company A", "Reseller B", "Distributor A", "Unidentified Customer Two", "Second Largest Customer",
                      "Customer 5", "Largest Customer", "Vendor", "One Customer"):
            self.assertEqual(xbrl.classify(label), "unnamed", label)
        for label in ("Top Ten Customers", "Three Largest Customers", "United States And Europe Based End Customers", "Seventy Six Customers",
                      "Ablecom and Compuware", "Four Customers"):
            self.assertEqual(xbrl.classify(label), "group", label)
        for label in ("Apple, Inc.", "Dell Inc.", "HP Inc.", "Lenovo Group Limited", "Foxconn", "Compuware"):
            self.assertEqual(xbrl.classify(label), "named", label)

    def test_measure_from_the_benchmark(self):
        self.assertEqual(xbrl.measure_of("us-gaap:RevenueFromContractWithCustomerMember"), "revenue")
        self.assertEqual(xbrl.measure_of("us-gaap:SalesRevenueNetMember"), "revenue")
        self.assertEqual(xbrl.measure_of("mod:SalesMember"), "revenue")
        self.assertEqual(xbrl.measure_of("us-gaap:AccountsReceivableMember"), "receivables")
        self.assertEqual(xbrl.measure_of("smci:PurchasesTotalMember"), "purchases")
        self.assertEqual(xbrl.measure_of("us-gaap:CostOfGoodsAndServicesSoldMember"), "purchases")
        self.assertIsNone(xbrl.measure_of("us-gaap:RevenueFromContractWithCustomerSegmentBenchmarkMember"))
        self.assertIsNone(xbrl.measure_of("lite:ManufacturerConcentrationMember"))

    def test_percent(self):
        self.assertEqual(xbrl.percent("0.25"), 25)
        self.assertEqual(xbrl.percent("0.304"), 30.4)
        self.assertEqual(xbrl.percent("25"), 25)
        self.assertEqual(xbrl.percent("1"), 100)

    def test_rows_and_what_is_left_out(self):
        rows, skipped = xbrl.concentration_rows(instance_xml(), xbrl.parse_labels(labels_xml()))
        got = {(r["label"], r["measure"], r["end"]): r for r in rows}
        self.assertEqual(got[("Customer A", "revenue", "2026-01-25")]["percent"], 22.13)  # the more precise duplicate
        self.assertEqual(got[("Customer A", "receivables", "2026-01-25")]["percent"], 25)
        self.assertEqual(got[("Customer A", "revenue", "2025-01-26")]["percent"], 12)
        self.assertEqual(got[("Supplier A", "purchases", "2026-01-25")]["percent"], 63.1)
        self.assertEqual(got[("Customer B", "revenue", "2026-01-25")]["notes"], ["segment: Compute & Networking"])
        self.assertEqual(len(rows), 8)
        reasons = {(s.get("label"), s["reason"]) for s in skipped}
        self.assertIn(("Top Ten Customers", "group_not_a_company"), reasons)
        self.assertIn(("Ablecom and Compuware", "group_not_a_company"), reasons)
        self.assertIn(("End Customer", "narrowed_by_StatementGeographicalAxis"), reasons)
        self.assertIn(("Vendor", "unknown_benchmark"), reasons)
        self.assertNotIn(None, {s.get("label") for s in skipped})  # the region-only share isn't about a company: not listed at all

    def test_files_in_the_filing(self):
        names = [{"name": n} for n in ("nvda-20260125.htm", "nvda-20260125_cal.xml", "nvda-20260125_htm.xml", "nvda-20260125_lab.xml",
                                        "FilingSummary.xml")]
        self.assertEqual(xbrl.instance_and_labels(names), ("nvda-20260125_htm.xml", "nvda-20260125_lab.xml"))
        old = [{"name": n} for n in ("aapl-20180929.xml", "aapl-20180929_lab.xml", "aapl-20180929_pre.xml", "FilingSummary.xml")]
        self.assertEqual(xbrl.instance_and_labels(old), ("aapl-20180929.xml", "aapl-20180929_lab.xml"))
        self.assertEqual(xbrl.instance_and_labels([{"name": "a.htm"}]), (None, None))


class Importing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        self.nvda = graph.add_company(self.conn, "NVIDIA Corporation")
        self.apple = graph.add_company(self.conn, "Apple Inc.")
        self.document = graph.add_document(self.conn, "sec", "10-K", "0001-26-1/nvda.htm", "https://www.sec.gov/x", company_id=self.nvda)
        self.rows, _ = xbrl.concentration_rows(instance_xml(), xbrl.parse_labels(labels_xml()))
        self.asked = []

    async def resolve(self, conn, name):
        self.asked.append(name)
        if name == "Apple, Inc.":
            return {"status": "matched", "company_id": self.apple, "method": "identifier_store", "reason": None, "detail": None}
        return {"status": "skipped", "company_id": None, "method": None, "reason": "no_match", "detail": "not known"}

    def load(self, rows=None):
        return run(xbrl.import_rows(self.conn, self.nvda, self.document, self.rows if rows is None else rows, resolve=self.resolve))

    def placeholders(self):
        return [r["name"] for r in self.conn.execute("SELECT name FROM companies WHERE is_placeholder = 1 ORDER BY name")]

    def test_unnamed_customers_become_placeholders_per_year(self):
        self.load()
        self.assertEqual(self.placeholders(), [
            "Customer A (unnamed customer of NVIDIA Corporation, year to 2025-01-26)",
            "Customer A (unnamed customer of NVIDIA Corporation, year to 2026-01-25)",
            "Customer B (unnamed customer of NVIDIA Corporation, year to 2026-01-25)",
            "Supplier A (unnamed supplier of NVIDIA Corporation, year to 2026-01-25)"])
        self.assertNotIn("Customer A", self.asked)  # never sent to the name lookup
        owner = {r[0] for r in self.conn.execute("SELECT placeholder_for FROM companies WHERE is_placeholder = 1")}
        self.assertEqual(owner, {self.nvda})

    def test_revenue_and_receivables_of_one_customer_are_one_link(self):
        self.load()
        customer = self.conn.execute("SELECT id FROM companies WHERE name LIKE 'Customer A%2026-01-25)'").fetchone()[0]
        link = self.conn.execute("SELECT * FROM relationships WHERE supplier_id = ? AND customer_id = ?", (self.nvda, customer)).fetchone()
        self.assertEqual((link["supplier_revenue_share"], link["tier"], link["shares_as_of"]), (22.13, 1, "2026-01-25"))
        notes = [r[0] for r in self.conn.execute("SELECT share_note FROM evidence WHERE relationship_id = ? ORDER BY id", (link["id"],))]
        self.assertEqual(sorted(notes, key=str), ["25% of accounts receivable", None])

    def test_named_customer_takes_the_newest_share_and_keeps_the_old_as_evidence(self):
        self.load()
        link = self.conn.execute("SELECT * FROM relationships WHERE supplier_id = ? AND customer_id = ?", (self.nvda, self.apple)).fetchone()
        self.assertEqual((link["supplier_revenue_share"], link["shares_as_of"]), (91, "2026-01-25"))
        evidence = self.conn.execute("SELECT quote, extractor, tier, stated_on, document_id, locator FROM evidence WHERE relationship_id = ? ORDER BY stated_on",
                                     (link["id"],)).fetchall()
        self.assertEqual([e["stated_on"] for e in evidence], ["2025-01-26", "2026-01-25"])
        self.assertEqual({(e["extractor"], e["tier"], e["document_id"]) for e in evidence}, {("xbrl", 1, self.document)})
        self.assertIn("Apple, Inc.: 91% of revenue, 2025-01-27 to 2026-01-25", evidence[1]["quote"])
        self.assertIn("nvda:AppleIncMember", evidence[1]["quote"])
        self.assertEqual(evidence[1]["locator"], "XBRL fact f4, context apple26")

    def test_older_figure_loaded_later_does_not_replace_the_newer(self):
        apple = [r for r in self.rows if r["label"] == "Apple, Inc."]
        self.load([r for r in apple if r["end"] == "2026-01-25"])
        self.load([r for r in apple if r["end"] == "2025-01-26"])
        link = self.conn.execute("SELECT supplier_revenue_share, shares_as_of FROM relationships WHERE customer_id = ?", (self.apple,)).fetchone()
        self.assertEqual(tuple(link), (91, "2026-01-25"))

    def test_unresolved_name_is_rejected_not_guessed(self):
        results = self.load()
        luxshare = [r for r in results if r["row"]["label"] == "Luxshare"][0]
        self.assertEqual((luxshare["status"], luxshare["relationship_id"]), ("rejected", None))
        rejected = self.conn.execute("SELECT * FROM rejected").fetchone()
        self.assertEqual((rejected["reason"], rejected["customer_name"], rejected["supplier_name"], rejected["rejected_by"]),
                         ("unresolved_company", "Luxshare", "NVIDIA Corporation", "rule"))
        self.assertFalse(self.conn.execute("SELECT 1 FROM companies WHERE name LIKE 'Luxshare%'").fetchone())

    def test_supplier_share_points_the_other_way(self):
        self.load()
        supplier = self.conn.execute("SELECT id FROM companies WHERE name LIKE 'Supplier A%'").fetchone()[0]
        link = self.conn.execute("SELECT * FROM relationships WHERE supplier_id = ?", (supplier,)).fetchone()
        self.assertEqual((link["customer_id"], link["customer_supply_share"], link["customer_share_scope"], link["supplier_revenue_share"]),
                         (self.nvda, 63.1, "purchases, total", None))

    def test_segment_is_kept_as_a_note(self):
        self.load()
        note = self.conn.execute("SELECT e.share_note FROM evidence e JOIN relationships r ON r.id = e.relationship_id "
                                 "JOIN companies c ON c.id = r.customer_id WHERE c.name LIKE 'Customer B%'").fetchone()[0]
        self.assertEqual(note, "segment: Compute & Networking")

    def test_loading_again_adds_nothing(self):
        self.load()
        counts = [self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("companies", "relationships", "evidence", "rejected")]
        self.load()
        self.assertEqual([self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("companies", "relationships", "evidence", "rejected")],
                         counts)
        self.assertEqual(integrity.check(self.conn), [])

    def test_name_lookup_down_raises_so_the_job_is_retried(self):
        async def down(conn, name):
            return {"status": "unavailable", "company_id": None, "method": None, "reason": "openfigi_unavailable", "detail": "busy"}
        with self.assertRaises(RuntimeError):
            run(xbrl.import_rows(self.conn, self.nvda, self.document, [r for r in self.rows if r["label"] == "Luxshare"], resolve=down))

    def test_a_name_matching_the_filer_itself_is_rejected(self):
        async def itself(conn, name):
            return {"status": "matched", "company_id": self.nvda, "method": "identifier_store", "reason": None, "detail": None}
        results = run(xbrl.import_rows(self.conn, self.nvda, self.document, [r for r in self.rows if r["label"] == "Apple, Inc."], resolve=itself))
        self.assertEqual({r["status"] for r in results}, {"rejected"})


class FromEdgar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        self.nvda = graph.add_company(self.conn, "NVIDIA Corporation")
        graph.add_company(self.conn, "Apple Inc.")
        self.filing = {"accession": "0001045810-26-000021", "form": "10-K", "filed": "2026-02-25", "period": "2026-01-25",
                       "primary_document": "nvda-20260125.htm", "url": "https://www.sec.gov/nvda-20260125.htm", "xbrl": True}

    def fake_edgar(self, files):
        async def filing_files(cik, accession):
            return [{"name": n} for n in files]

        async def get_bytes(url, max_bytes=0):
            return instance_xml() if url.endswith("_htm.xml") else labels_xml()
        return mock.patch.multiple(sec_client, filing_files=filing_files, get_bytes=get_bytes)

    def test_import_filing(self):
        with self.fake_edgar(["nvda-20260125.htm", "nvda-20260125_htm.xml", "nvda-20260125_lab.xml"]), \
                mock.patch.object(xbrl.resolver.openfigi, "search", mock.AsyncMock(return_value=[])), \
                mock.patch.object(xbrl.resolver.constituents, "universe", return_value=[]):
            out = run(xbrl.import_filing(self.conn, self.nvda, 1045810, self.filing))
        self.assertEqual(len(out["rows"]), 8)
        linked = {r["row"]["label"] for r in out["results"] if r["status"] == "linked"}
        self.assertEqual(linked, {"Customer A", "Customer B", "Apple, Inc.", "Supplier A"})
        document = self.conn.execute("SELECT * FROM documents WHERE id = ?", (out["document_id"],)).fetchone()
        self.assertEqual((document["kind"], document["company_id"]), ("10-K", self.nvda))

    def test_job_note_when_nothing_is_tagged(self):
        async def none(*a, **k):
            return {"document_id": 1, "rows": [], "skipped": [], "results": []}
        with mock.patch.object(xbrl, "import_filing", none):
            note = run(xbrl.xbrl_job({"company_id": 1, "payload": {"cik": 1, "filing": {}}}, self.conn))
        self.assertEqual(note, {"notes": "no customer figures tagged"})

    def test_filing_without_xbrl(self):
        with self.fake_edgar(["old.htm"]):
            out = run(xbrl.import_filing(self.conn, self.nvda, 1045810, self.filing))
        self.assertEqual((out["rows"], out["note"]), ([], "no XBRL data in the filing"))

    def test_scout_queues_xbrl_for_a_10k_with_data(self):
        graph.add_identifier(self.conn, self.nvda, "cik", "1045810")
        filings = [self.filing, {**self.filing, "accession": "q", "form": "10-Q"}, {**self.filing, "accession": "n", "xbrl": False}]
        with mock.patch.object(sec_client, "list_filings", mock.AsyncMock(return_value=filings)):
            run(scout.scan(self.conn, self.nvda, today=__import__("datetime").date(2026, 3, 1)))
        queued = [r[0] for r in self.conn.execute("SELECT key FROM jobs WHERE kind = 'xbrl'")]
        self.assertEqual(queued, ["0001045810-26-000021"])


if __name__ == "__main__":
    unittest.main()
