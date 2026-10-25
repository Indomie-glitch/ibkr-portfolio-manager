import shutil
import tempfile
import unittest
from pathlib import Path

import usage_store
from supply_chain import chunker
from supply_chain.chunker import Section

FIXTURES = Path(__file__).parent / "fixtures" / "filings"


def chunks_of(name, form, **limits):
    return chunker.chunk_file(FIXTURES / name, "sec", form, **limits)


def by_section(chunks, start):
    return [c for c in chunks if c.section.startswith(start)]


class EstimateTests(unittest.TestCase):
    def test_limit_leaves_room_below_the_long_prompt_price(self):
        self.assertLessEqual(chunker.MAX_CHUNK_TOKENS, usage_store.PRICES["claude-haiku-5-5"]["long_from"] * 0.85)

    def test_errs_high_for_prose(self):
        text = "The company sells integrated circuits to manufacturers of consumer electronics. " * 50
        self.assertGreater(chunker.estimate_tokens(text), len(text.split()) * 1.3)

    def test_numbers_and_symbols_cost_more_than_letters(self):
        table = "1,234,567 | (89.5)% | $ 4,321\n" * 20
        self.assertGreater(chunker.estimate_tokens(table), len(table) / 3 * 1.5)  # a plain "3 letters a token" rule would undercount
        self.assertEqual(chunker.estimate_tokens("1,234,567"), 5)  # three digit groups and two commas


class TextTests(unittest.TestCase):
    def test_tables_become_rows_and_edgar_cells_are_joined(self):
        html = ("<html><body><p>Intro</p><table><tr><td>Total assets</td><td>$</td><td>1,234</td><td>$</td><td>(5</td><td>)</td></tr>"
                "<tr><td>Growth</td><td>12</td><td>%</td></tr></table><p>After</p></body></html>")
        self.assertEqual(chunker.paragraphs_from(html), ["Intro", "Total assets | $1,234 | $(5)\nGrowth | 12%", "After"])

    def test_one_row_table_is_layout(self):
        html = "<html><body><table><tr><td>Item 1A.</td><td>Risk Factors</td></tr></table></body></html>"
        self.assertEqual(chunker.paragraphs_from(html), ["Item 1A. Risk Factors"])

    def test_drops_hidden_xbrl_scripts_page_numbers_and_blank_space(self):
        html = ("<html><head><title>t</title></head><body><ix:header><ix:hidden>SECRET</ix:hidden></ix:header><script>x=1</script>"
                "<div>Table of Contents</div><div>Real text   here</div><div>- 12 -</div><div>F-3</div><div> </div></body></html>")
        self.assertEqual(chunker.paragraphs_from(html), ["Real text here"])

    def test_inline_markup_stays_in_one_paragraph(self):
        self.assertEqual(chunker.paragraphs_from("<html><body><p>Sales to <b>Beta</b> <span>Corp</span> grew.</p></body></html>"),
                         ["Sales to Beta Corp grew."])

    def test_plain_text(self):
        paragraphs = chunker.load_paragraphs(FIXTURES / "plain.txt")
        self.assertEqual(paragraphs, ["Plain exhibit", "The parties agree that Seller will supply goods to Buyer.",
                                      "Name Share\nBeta 48%\nDelta 12%"])

    def test_decodes_windows_1252(self):
        self.assertEqual(chunker.decode("café".encode("cp1252")), "café")


class TenKTests(unittest.TestCase):
    def setUp(self):
        self.chunks = chunks_of("tenk.htm", "10-K")

    def test_keeps_only_the_sections_that_name_relationships(self):
        self.assertEqual([c.section for c in self.chunks][:3],
                         ["Item 1. Business", "Item 1A. Risk Factors", "Item 7. MD&A (customer and supplier passages)"])
        text = "\n".join(c.text for c in self.chunks)
        for dropped in ("HIDDEN XBRL JUNK", "Unresolved Staff", "Pursuant to the requirements", "Exhibit 10.1 is filed", "Dividends were not paid",
                        "Income Taxes", "Total assets"):
            self.assertNotIn(dropped, text)

    def test_table_of_contents_is_not_the_item(self):
        business = by_section(self.chunks, "Item 1. ")[0]
        self.assertIn("Acme designs chips", business.text)
        self.assertNotIn("| 3", business.text)

    def test_running_page_header_does_not_split_a_section(self):
        risks = by_section(self.chunks, "Item 1A")
        self.assertEqual(len(risks), 1)
        self.assertIn("single supplier", risks[0].text)
        self.assertIn("loss of Beta Corp", risks[0].text)

    def test_mdna_keeps_customer_paragraphs_with_neighbours_only(self):
        text = by_section(self.chunks, "Item 7")[0].text
        self.assertIn("largest customer, Beta Corp, were 48%", text)
        self.assertIn("Revenue grew", text)
        self.assertIn("Operating expenses", text)
        self.assertNotIn("Interest income", text)

    def test_notes_found_under_item_15_and_only_relevant_ones_kept(self):
        notes = by_section(self.chunks, "Item 8")[0]
        self.assertEqual(notes.section, "Item 8. Financial Statements, notes: Revenue; Concentration of Customers")
        self.assertIn("Beta Corp | 48%\nDelta Ltd | 12%", notes.text)
        self.assertNotIn("Organization", notes.text)
        self.assertNotIn("SIGNATURES", notes.text)

    def test_locators_point_at_paragraph_numbers(self):
        paragraphs = chunker.load_paragraphs(FIXTURES / "tenk.htm")
        for chunk in self.chunks:
            self.assertEqual(chunk.locator, chunker.locator_for(chunk.section, chunk.first_paragraph, chunk.last_paragraph))
            self.assertEqual(chunk.document, "tenk.htm")
            self.assertTrue(paragraphs[chunk.first_paragraph - 1] in chunk.text and paragraphs[chunk.last_paragraph - 1] in chunk.text)
        self.assertEqual(self.chunks[0].locator, "Item 1. Business, paragraphs 3-6")
        self.assertEqual([c.tokens > 0 for c in self.chunks], [True] * len(self.chunks))


class OtherFormTests(unittest.TestCase):
    def test_10q_uses_the_part_to_tell_the_two_item_1s_apart(self):
        sections = [c.section for c in chunks_of("tenq.htm", "10-Q")]
        self.assertEqual(sections, ["Item 1. Financial Statements, notes: Revenue and Concentration",
                                    "Item 2. MD&A (customer and supplier passages)", "Part II Item 1A. Risk Factors"])
        self.assertNotIn("Legal Proceedings", "\n".join(c.text for c in chunks_of("tenq.htm", "10-Q")))

    def test_8k_keeps_material_agreement_item_only(self):
        chunks = chunks_of("8k.htm", "8-K")
        self.assertEqual([c.section for c in chunks], ["Item 1.01 Entry into a Material Definitive Agreement"])
        self.assertNotIn("press release", chunks[0].text)

    def test_8k_about_something_else_gives_nothing(self):
        self.assertEqual(chunks_of("8k-results.htm", "8-K"), [])

    def test_filing_folder_adds_exhibit_10_agreements_of_an_8k(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("8k.htm", "ex10-1.htm", "8k-results.htm"):
                shutil.copy(FIXTURES / name, Path(folder) / name)
            shutil.copy(FIXTURES / "6k.htm", Path(folder) / "ex21-1.htm")
            chunks = chunker.chunk_filing(folder, "8-K", "8k.htm")
        self.assertEqual([(c.document, c.section) for c in chunks],
                         [("8k.htm", "Item 1.01 Entry into a Material Definitive Agreement"), ("ex10-1.htm", "Exhibit 10.1")])
        self.assertEqual([c.number for c in chunks], [1, 2])
        self.assertIn("Gamma Foundry Ltd.", chunks[1].text)

    def test_exhibits_are_only_added_for_8k(self):
        with tempfile.TemporaryDirectory() as folder:
            shutil.copy(FIXTURES / "tenk.htm", Path(folder) / "tenk.htm")
            shutil.copy(FIXTURES / "ex10-1.htm", Path(folder) / "ex10-1.htm")
            self.assertNotIn("ex10-1.htm", {c.document for c in chunker.chunk_filing(folder, "10-K", "tenk.htm")})

    def test_exhibit_labels(self):
        self.assertEqual([chunker.exhibit_label(n) for n in ("ex10-1.htm", "a2026ex101.htm", "tsla-ex10_12.htm", "ex10.htm", "ex10-1.txt")],
                         ["Exhibit 10.1", "Exhibit 10.1", "Exhibit 10.12", "Exhibit 10", "Exhibit 10.1"])
        for name in ("index10.htm", "ex21.htm", "ex101.pdf", "ex99-1.htm", "ex100.htm"[:3]):
            self.assertIsNone(chunker.exhibit_label(name))


class FallbackTests(unittest.TestCase):
    def test_filing_without_recognisable_sections_is_read_whole(self):
        chunks = chunks_of("6k.htm", "6-K")
        self.assertEqual([c.section for c in chunks], ["Full text"])
        self.assertIn("multi-year supply deal", chunks[0].text)
        self.assertIn("deliver components", chunks[0].text)

    def test_10k_with_no_items_is_read_whole(self):
        paragraphs = ["Annual report", "Our customer Beta buys a lot. " * 5, "More text."]
        chunks = chunker.chunk_paragraphs(paragraphs, "sec", "10-K")
        self.assertEqual([c.section for c in chunks], ["Full text"])
        self.assertEqual((chunks[0].first_paragraph, chunks[0].last_paragraph), (1, 3))

    def test_10k_whose_items_are_all_too_short_is_read_whole(self):
        chunks = chunker.chunk_paragraphs(["Item 1. Business", "Item 1A. Risk Factors", "Item 7. MD&A"], "sec", "10-K")
        self.assertEqual([c.section for c in chunks], ["Full text"])

    def test_unknown_source_and_empty_document(self):
        self.assertEqual([c.section for c in chunker.chunk_paragraphs(["Some text."], "nowhere", "")], ["Full text"])
        self.assertEqual(chunker.chunk_paragraphs([], "sec", "10-K"), [])

    def test_prose_mentioning_an_item_is_not_a_heading(self):
        paragraphs = ["Item 7 of this report discusses our results in detail for readers who want more about the year."] * 3
        self.assertEqual(chunker._headings(paragraphs, "10-K"), [])


class SplitTests(unittest.TestCase):
    def sentences(self, n):
        return [f"Sentence number {i} says that Beta Corp bought parts from Gamma." for i in range(n)]

    def test_chunks_stay_under_the_limit_and_cut_between_paragraphs(self):
        paragraphs = [" ".join(self.sentences(4)) for _ in range(40)]
        chunks = chunker.chunk_paragraphs(paragraphs, "none", max_tokens=300, overlap_tokens=0)
        self.assertGreater(len(chunks), 3)
        for chunk in chunks:
            self.assertLessEqual(chunk.tokens, 300)
            self.assertEqual(chunk.overlap, 0)
            for paragraph in chunk.text.split("\n\n"):
                self.assertIn(paragraph, paragraphs)
        self.assertEqual("\n\n".join(c.text for c in chunks), "\n\n".join(paragraphs))
        self.assertEqual(chunks[1].first_paragraph, chunks[0].last_paragraph + 1)

    def test_overlap_repeats_the_end_of_the_previous_chunk(self):
        paragraphs = [f"Paragraph {i} says Beta Corp buys from Gamma Foundry every quarter." for i in range(60)]
        chunks = chunker.chunk_paragraphs(paragraphs, "none", max_tokens=300, overlap_tokens=60)
        self.assertGreater(len(chunks), 2)
        for before, after in zip(chunks, chunks[1:]):
            self.assertGreater(after.overlap, 0)
            self.assertLessEqual(after.tokens, 300)
            self.assertEqual(after.first_paragraph, before.last_paragraph - after.overlap + 1)
            self.assertTrue(after.text.startswith("\n\n".join(before.text.split("\n\n")[-after.overlap:])))
        self.assertEqual(chunks[-1].last_paragraph, 60)

    def test_a_too_big_paragraph_is_cut_at_sentence_ends(self):
        sentences = self.sentences(80)
        chunks = chunker.chunk_paragraphs([" ".join(sentences)], "none", max_tokens=200, overlap_tokens=0)
        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(chunk.tokens, 200)
            for part in chunk.text.split("\n\n"):
                self.assertTrue(part.endswith("Gamma."), part[-30:])
        self.assertEqual(" ".join(c.text.replace("\n\n", " ") for c in chunks), " ".join(sentences))
        self.assertEqual({(c.first_paragraph, c.last_paragraph) for c in chunks}, {(1, 1)})

    def test_a_long_table_is_cut_between_rows(self):
        rows = [f"Customer {i} | {i}%" for i in range(100)]
        chunks = chunker.chunk_paragraphs(["\n".join(rows)], "none", max_tokens=100, overlap_tokens=0)
        self.assertGreater(len(chunks), 3)
        rejoined = [row for c in chunks for part in c.text.split("\n\n") for row in part.split("\n")]
        self.assertEqual(rejoined, rows)

    def test_a_single_endless_word_is_cut_as_a_last_resort(self):
        chunks = chunker.chunk_paragraphs(["x" * 1000], "none", max_tokens=100, overlap_tokens=0)
        self.assertTrue(all(c.tokens <= 100 for c in chunks))
        self.assertEqual("".join(c.text.replace("\n\n", "") for c in chunks), "x" * 1000)

    def test_default_limit_holds_for_a_big_section(self):
        paragraphs = ["1,234 | 5,678 | (9)% | $ 12.5 | 31,415\n" * 40 for _ in range(1500)]
        chunks = chunker.chunk_paragraphs(paragraphs, "none")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.tokens <= chunker.MAX_CHUNK_TOKENS for c in chunks))


class FinderTests(unittest.TestCase):
    def test_another_source_can_plug_in_its_own_finder(self):
        @chunker.finder("test-source")
        def sections(paragraphs, form):
            return [Section("Business overview", [i for i, p in enumerate(paragraphs) if p.startswith("B:")])]
        try:
            chunks = chunker.chunk_paragraphs(["A: cover", "B: we sell to Beta", "A: legal", "B: and to Delta"], "test-source", "annual", "report.pdf")
        finally:
            del chunker.FINDERS["test-source"]
        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0].document, chunks[0].section, chunks[0].text), ("report.pdf", "Business overview", "B: we sell to Beta\n\nB: and to Delta"))
        self.assertEqual(chunks[0].locator, "Business overview, paragraphs 2-4")

    def test_a_finder_returning_none_means_whole_text_and_empty_means_nothing(self):
        chunker.finder("none-source")(lambda paragraphs, form: None)
        chunker.finder("empty-source")(lambda paragraphs, form: [])
        try:
            self.assertEqual([c.section for c in chunker.chunk_paragraphs(["Text"], "none-source")], ["Full text"])
            self.assertEqual(chunker.chunk_paragraphs(["Text"], "empty-source"), [])
        finally:
            del chunker.FINDERS["none-source"], chunker.FINDERS["empty-source"]


if __name__ == "__main__":
    unittest.main()
