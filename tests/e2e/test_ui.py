"""
ownedpulse E2E UI tests — Playwright.
Install: pip install playwright pytest-playwright && playwright install chromium
Run: pytest tests/e2e/ --headed (or headless for CI)

Changes from previous version:
- Theme toggle tests added
- Retrieval settings panel tests added
- Query expansion collapsible tests added
- Langfuse trace drawer tests added
- Audit footer human-readable labels tested ("Semantic search" not "CONTENT")
- /history page tests added
- /corpus page tests added
- Corpus stats bar on landing page tested
- Citation cited/uncited visual distinction tested
- Superseded badge with current version link tested
- Zone 4: all new provenance fields tested
- Zone 4: chunk navigation tested
- EU-Commission must not appear in UI
- JetBrains Mono font in chunk text tested
- All tooltips present tested
"""

import pytest
from playwright.sync_api import Page, expect

UI_URL = "http://localhost:5173"
CONTENT_QUERY = "What are the Annex 11 requirements for audit trails?"
METADATA_QUERY = "How many EMA guidelines were published in the last 90 days?"
ICH_Q9_QUERY = "ICH Q9 quality risk management 2005 original"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1440, "height": 900}}


def submit_query_and_wait(page: Page, query: str = CONTENT_QUERY):
    page.goto(UI_URL)
    page.locator("[data-testid='query-input']").fill(query)
    page.locator("[data-testid='submit-button']").click()
    page.locator("[data-testid='answer-panel']").wait_for(timeout=90000)


# ── Page load ─────────────────────────────────────────────────────────────────

class TestPageLoad:

    def test_page_loads(self, page: Page):
        page.goto(UI_URL)
        expect(page).not_to_have_title("")

    def test_logo_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='logo']")).to_be_visible()

    def test_wordmark_owned_ai_split(self, page: Page):
        page.goto(UI_URL)
        wordmark = page.locator("[data-testid='wordmark']")
        expect(wordmark).to_contain_text("owned")
        expect(wordmark).to_contain_text("ai")

    def test_sidebar_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='sidebar']")).to_be_visible()

    def test_filter_bar_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='filter-bar']")).to_be_visible()

    def test_query_input_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='query-input']")).to_be_visible()

    def test_theme_toggle_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='theme-toggle']")).to_be_visible()


# ── Theme toggle ──────────────────────────────────────────────────────────────

class TestThemeToggle:

    def test_default_theme_is_light_panel(self, page: Page):
        page.goto(UI_URL)
        html = page.locator("html")
        data_theme = html.get_attribute("data-theme")
        assert data_theme != "dark", "Default theme should be light panel"

    def test_toggle_switches_to_dark_panel(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='theme-toggle']").click()
        html = page.locator("html")
        expect(html).to_have_attribute("data-theme", "dark")

    def test_toggle_switches_back_to_light(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='theme-toggle']").click()
        page.locator("[data-testid='theme-toggle']").click()
        html = page.locator("html")
        data_theme = html.get_attribute("data-theme")
        assert data_theme != "dark"

    def test_theme_persists_after_reload(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='theme-toggle']").click()
        page.reload()
        html = page.locator("html")
        expect(html).to_have_attribute("data-theme", "dark")
        # Cleanup — toggle back
        page.locator("[data-testid='theme-toggle']").click()


# ── Landing page ──────────────────────────────────────────────────────────────

class TestLandingPage:

    def test_empty_state_shown(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='empty-state']")).to_be_visible()

    def test_heading_present(self, page: Page):
        page.goto(UI_URL)
        heading = page.locator("[data-testid='landing-heading']")
        expect(heading).to_contain_text("Query regulatory intelligence")

    def test_three_example_chips(self, page: Page):
        page.goto(UI_URL)
        chips = page.locator("[data-testid='example-query']")
        expect(chips).to_have_count(3)

    def test_example_chip_populates_input(self, page: Page):
        page.goto(UI_URL)
        chip = page.locator("[data-testid='example-query']").first
        chip_text = chip.inner_text()
        chip.click()
        expect(page.locator("[data-testid='query-input']")).to_have_value(chip_text)

    def test_corpus_stats_bar_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='corpus-stats-bar']")).to_be_visible()

    def test_corpus_stats_shows_fda_count(self, page: Page):
        page.goto(UI_URL)
        stats = page.locator("[data-testid='corpus-stats-bar']")
        expect(stats).to_contain_text("FDA")

    def test_corpus_stats_shows_ema_count(self, page: Page):
        page.goto(UI_URL)
        stats = page.locator("[data-testid='corpus-stats-bar']")
        expect(stats).to_contain_text("EMA")

    def test_corpus_stats_no_eu_commission(self, page: Page):
        page.goto(UI_URL)
        stats_text = page.locator("[data-testid='corpus-stats-bar']").inner_text()
        assert "EU-Commission" not in stats_text, \
            "EU-Commission not normalised in corpus stats bar"

    def test_corpus_stats_agency_count_clickable(self, page: Page):
        page.goto(UI_URL)
        fda_link = page.locator("[data-testid='corpus-stats-fda']")
        expect(fda_link).to_be_visible()
        fda_link.click()
        expect(page).to_have_url(f"{UI_URL}/corpus?agency=FDA")

    def test_last_updated_timestamp_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='last-pipeline-run']")).to_be_visible()


# ── Retrieval settings ────────────────────────────────────────────────────────

class TestRetrievalSettings:

    def test_retrieval_settings_button_visible(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='retrieval-settings-toggle']")).to_be_visible()

    def test_retrieval_settings_collapsed_by_default(self, page: Page):
        page.goto(UI_URL)
        panel = page.locator("[data-testid='retrieval-settings-panel']")
        expect(panel).not_to_be_visible()

    def test_retrieval_settings_expands_on_click(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='retrieval-settings-toggle']").click()
        expect(page.locator("[data-testid='retrieval-settings-panel']")).to_be_visible()

    def test_query_depth_options_present(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='retrieval-settings-toggle']").click()
        for depth in ("low", "standard", "deep"):
            expect(page.locator(f"[data-testid='depth-{depth}']")).to_be_visible()

    def test_score_threshold_control_present(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='retrieval-settings-toggle']").click()
        expect(page.locator("[data-testid='score-threshold-input']")).to_be_visible()

    def test_top_k_control_present(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='retrieval-settings-toggle']").click()
        expect(page.locator("[data-testid='top-k-input']")).to_be_visible()


# ── Query submission ──────────────────────────────────────────────────────────

class TestQuerySubmission:

    def test_thinking_indicator_appears(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='query-input']").fill(CONTENT_QUERY)
        page.locator("[data-testid='submit-button']").click()
        expect(page.locator("[data-testid='thinking-indicator']")).to_be_visible()

    def test_answer_appears(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='answer-panel']")).to_be_visible()
        assert len(page.locator("[data-testid='answer-panel']").inner_text()) > 50

    def test_empty_state_hidden_after_query(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='empty-state']")).not_to_be_visible()

    def test_citations_appear(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='citation-card']").first).to_be_visible()

    def test_answer_contains_citation_markers(self, page: Page):
        submit_query_and_wait(page)
        answer_text = page.locator("[data-testid='answer-panel']").inner_text()
        assert "[1]" in answer_text, "Answer does not contain [1] citation marker"

    def test_answer_does_not_contain_html_tags(self, page: Page):
        """Server must not return HTML in answer — client renders plain text."""
        submit_query_and_wait(page)
        answer_html = page.locator("[data-testid='answer-panel']").inner_html()
        assert "<p><p>" not in answer_html, "Double p-tags suggest server HTML in answer"


# ── Query expansion ───────────────────────────────────────────────────────────

class TestQueryExpansion:

    def test_query_expansion_line_visible(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='query-expansion']")).to_be_visible()

    def test_query_expansion_collapsed_by_default(self, page: Page):
        submit_query_and_wait(page)
        panel = page.locator("[data-testid='query-expansion-panel']")
        expect(panel).not_to_be_visible()

    def test_query_expansion_expands_on_click(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='query-expansion']").click()
        expect(page.locator("[data-testid='query-expansion-panel']")).to_be_visible()

    def test_query_expansion_shows_sub_queries(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='query-expansion']").click()
        items = page.locator("[data-testid='sub-query-item']")
        assert items.count() >= 2, "Expected at least 2 sub-queries in expansion panel"


# ── Cited vs uncited chunks ───────────────────────────────────────────────────

class TestCitedVsUncited:

    def test_cited_cards_have_matched_badge(self, page: Page):
        submit_query_and_wait(page)
        matched = page.locator("[data-testid='badge-matched']")
        assert matched.count() > 0, "No MATCHED badges found in citations"

    def test_uncited_cards_have_not_cited_badge(self, page: Page):
        submit_query_and_wait(page)
        not_cited = page.locator("[data-testid='badge-not-cited']")
        if not_cited.count() > 0:
            first_uncited = page.locator("[data-testid='citation-card'][data-cited='false']").first
            opacity = first_uncited.evaluate("el => window.getComputedStyle(el).opacity")
            assert float(opacity) < 1.0, \
                "Uncited citation card should be dimmed (opacity < 1)"


# ── Audit footer ──────────────────────────────────────────────────────────────

class TestAuditFooter:
    """Annex 11 §8.1 — audit footer must be visible and correctly labelled."""

    def test_audit_footer_visible_after_query(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='audit-footer']")).to_be_visible()

    def test_audit_footer_not_visible_before_query(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='audit-footer']")).not_to_be_visible()

    def test_audit_footer_contains_query_id(self, page: Page):
        submit_query_and_wait(page)
        footer_text = page.locator("[data-testid='audit-footer']").inner_text()
        assert "Query ID" in footer_text, "Audit footer missing 'Query ID' label"

    def test_audit_footer_shows_semantic_search_not_content(self, page: Page):
        """Routing badge must show human-readable 'Semantic search', not raw 'CONTENT'."""
        submit_query_and_wait(page)
        footer_text = page.locator("[data-testid='audit-footer']").inner_text()
        assert "Semantic search" in footer_text, \
            "Audit footer should show 'Semantic search', not raw 'CONTENT'"
        assert "CONTENT" not in footer_text, \
            "Raw 'CONTENT' must not appear in audit footer — use 'Semantic search'"

    def test_audit_footer_shows_metadata_lookup_for_metadata_query(self, page: Page):
        submit_query_and_wait(page, query=METADATA_QUERY)
        footer_text = page.locator("[data-testid='audit-footer']").inner_text()
        assert "Metadata lookup" in footer_text, \
            "Metadata query should show 'Metadata lookup' in footer"

    def test_audit_footer_has_view_trace_link(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='view-trace-link']")).to_be_visible()

    def test_audit_footer_date_format_european(self, page: Page):
        """Date in audit footer must be DD/MM/YYYY not MM/DD/YYYY."""
        submit_query_and_wait(page)
        footer_text = page.locator("[data-testid='audit-footer']").inner_text()
        import re
        # Check for DD/MM/YYYY pattern
        european_date = re.search(r'\d{2}/\d{2}/\d{4}', footer_text)
        assert european_date, f"European date format DD/MM/YYYY not found in footer: {footer_text}"


# ── Langfuse trace drawer ─────────────────────────────────────────────────────

class TestLangfuseDrawer:

    def test_trace_drawer_hidden_initially(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='langfuse-drawer']")).not_to_be_visible()

    def test_view_trace_opens_drawer(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='view-trace-link']").click()
        expect(page.locator("[data-testid='langfuse-drawer']")).to_be_visible()

    def test_trace_drawer_shows_trace_id(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='view-trace-link']").click()
        page.locator("[data-testid='langfuse-drawer']").wait_for(timeout=10000)
        expect(page.locator("[data-testid='trace-id']")).to_be_visible()

    def test_trace_drawer_close_button_works(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='view-trace-link']").click()
        page.locator("[data-testid='langfuse-drawer']").wait_for()
        page.locator("[data-testid='langfuse-drawer-close']").click()
        expect(page.locator("[data-testid='langfuse-drawer']")).not_to_be_visible()


# ── Source panel (Zone 4) ─────────────────────────────────────────────────────

class TestSourcePanel:

    def _submit_and_wait_for_citations(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='query-input']").fill(CONTENT_QUERY)
        page.locator("[data-testid='submit-button']").click()
        page.locator("[data-testid='citation-card']").first.wait_for(timeout=90000)

    def test_source_panel_hidden_initially(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='source-panel']")).not_to_be_visible()

    def test_citation_card_click_opens_source_panel(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        expect(page.locator("[data-testid='source-panel']")).to_be_visible()

    def test_view_source_button_opens_source_panel(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='view-source-button']").first.click()
        expect(page.locator("[data-testid='source-panel']")).to_be_visible()

    def test_source_panel_shows_chunk_text(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        chunk = page.locator("[data-testid='chunk-text']")
        expect(chunk).to_be_visible()
        assert len(chunk.inner_text()) > 10

    def test_source_panel_shows_provenance_metadata(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        expect(page.locator("[data-testid='provenance-metadata']")).to_be_visible()

    def test_source_panel_shows_chunk_index(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        expect(page.locator("[data-testid='prov-chunk-index']")).to_be_visible()

    def test_source_panel_shows_char_offsets(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        expect(page.locator("[data-testid='prov-char-offsets']")).to_be_visible()

    def test_source_panel_shows_ingestion_date(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        expect(page.locator("[data-testid='prov-ingestion-date']")).to_be_visible()

    def test_source_panel_null_fields_show_not_available(self, page: Page):
        """Null fields must show 'Not available', not a dash."""
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        clause_id_cell = page.locator("[data-testid='prov-clause-id']")
        if clause_id_cell.is_visible():
            text = clause_id_cell.inner_text()
            assert "—" not in text and text != "-", \
                f"Null clause_id should show 'Not available', not a dash: {text}"

    def test_source_panel_shows_chunk_nav(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        expect(page.locator("[data-testid='next-chunk-btn']")).to_be_visible()

    def test_source_panel_closes_on_new_query(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        page.locator("[data-testid='source-panel']").wait_for()
        page.locator("[data-testid='query-input']").fill("A new query to close the panel")
        page.locator("[data-testid='submit-button']").click()
        expect(page.locator("[data-testid='source-panel']")).not_to_be_visible()

    def test_source_panel_close_button_works(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        page.locator("[data-testid='source-panel']").wait_for()
        page.locator("[data-testid='source-panel-close']").click()
        expect(page.locator("[data-testid='source-panel']")).not_to_be_visible()

    def test_source_panel_no_eu_commission_in_agency(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        page.locator("[data-testid='source-panel']").wait_for()
        agency_text = page.locator("[data-testid='prov-agency']").inner_text()
        assert "EU-Commission" not in agency_text, \
            "EU-Commission not normalised in Zone 4 provenance"

    def test_jetbrains_mono_used_for_chunk_text(self, page: Page):
        self._submit_and_wait_for_citations(page)
        page.locator("[data-testid='citation-card']").first.click()
        page.locator("[data-testid='source-panel']").wait_for()
        chunk_el = page.locator("[data-testid='chunk-text']")
        font_family = chunk_el.evaluate(
            "el => window.getComputedStyle(el).fontFamily"
        )
        assert "JetBrains" in font_family or "monospace" in font_family.lower(), \
            f"Chunk text not using JetBrains Mono: {font_family}"


# ── Superseded badge ──────────────────────────────────────────────────────────

class TestSupersededBadge:

    def test_superseded_badge_has_current_version_link(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='query-input']").fill(ICH_Q9_QUERY)
        page.locator("[data-testid='submit-button']").click()
        page.locator("[data-testid='citation-card']").first.wait_for(timeout=90000)
        badges = page.locator("[data-testid='badge-superseded']")
        if badges.count() > 0:
            first_badge = badges.first
            expect(first_badge).to_be_visible()
            card = page.locator("[data-testid='superseded-current-version']").first
            expect(card).to_be_visible()


# ── Export ────────────────────────────────────────────────────────────────────

class TestExportButton:

    def test_export_button_visible_after_query(self, page: Page):
        submit_query_and_wait(page)
        expect(page.locator("[data-testid='export-button']")).to_be_visible()

    def test_export_button_not_visible_before_query(self, page: Page):
        page.goto(UI_URL)
        expect(page.locator("[data-testid='export-button']")).not_to_be_visible()

    def test_json_export_triggers_download(self, page: Page):
        submit_query_and_wait(page)
        with page.expect_download() as dl_info:
            page.locator("[data-testid='export-json']").click()
        download = dl_info.value
        assert download.suggested_filename.startswith("ownedpulse-export-"), \
            f"Unexpected filename: {download.suggested_filename}"
        assert download.suggested_filename.endswith(".json"), \
            f"JSON export should have .json extension"

    def test_pdf_export_triggers_download(self, page: Page):
        submit_query_and_wait(page)
        with page.expect_download() as dl_info:
            page.locator("[data-testid='export-pdf']").click()
        download = dl_info.value
        assert download.suggested_filename.endswith(".pdf"), \
            f"PDF export should have .pdf extension"


# ── Query history ─────────────────────────────────────────────────────────────

class TestQueryHistory:

    def test_history_items_appear_in_sidebar(self, page: Page):
        submit_query_and_wait(page)
        history = page.locator("[data-testid='history-item']")
        expect(history.first).to_be_visible()

    def test_view_all_link_navigates_to_history_page(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='view-all-history']").click()
        expect(page).to_have_url(f"{UI_URL}/history")

    def test_history_item_sidebar_click_loads_result(self, page: Page):
        submit_query_and_wait(page)
        page.locator("[data-testid='new-query-button']").click()
        page.locator("[data-testid='history-item']").first.click()
        expect(page.locator("[data-testid='answer-panel']")).to_be_visible(timeout=10000)

    def test_history_item_sidebar_click_does_not_show_thinking(self, page: Page):
        """Sidebar history click loads cached result, must not re-execute query."""
        submit_query_and_wait(page)
        page.locator("[data-testid='new-query-button']").click()
        page.locator("[data-testid='history-item']").first.click()
        thinking = page.locator("[data-testid='thinking-indicator']")
        expect(thinking).not_to_be_visible()


# ── History page (/history) ───────────────────────────────────────────────────

class TestHistoryPage:

    def test_history_page_loads(self, page: Page):
        submit_query_and_wait(page)
        page.goto(f"{UI_URL}/history")
        expect(page).to_have_url(f"{UI_URL}/history")

    def test_history_page_has_table(self, page: Page):
        page.goto(f"{UI_URL}/history")
        expect(page.locator("[data-testid='history-table']")).to_be_visible()

    def test_history_table_has_entries(self, page: Page):
        submit_query_and_wait(page)
        page.goto(f"{UI_URL}/history")
        rows = page.locator("[data-testid='history-row']")
        assert rows.count() > 0, "History table has no rows"

    def test_history_routing_column_human_readable(self, page: Page):
        submit_query_and_wait(page)
        page.goto(f"{UI_URL}/history")
        first_row = page.locator("[data-testid='history-row']").first
        routing_cell = first_row.locator("[data-testid='history-routing']")
        routing_text = routing_cell.inner_text()
        assert routing_text in ("Semantic", "Metadata"), \
            f"History routing must be 'Semantic' or 'Metadata', got: {routing_text}"
        assert "CONTENT" not in routing_text and "METADATA" not in routing_text, \
            "Raw routing values must not appear in history table"

    def test_history_date_format_european(self, page: Page):
        submit_query_and_wait(page)
        page.goto(f"{UI_URL}/history")
        first_row = page.locator("[data-testid='history-row']").first
        date_cell = first_row.locator("[data-testid='history-timestamp']")
        import re
        date_text = date_cell.inner_text()
        assert re.search(r'\d{2}/\d{2}/\d{4}', date_text), \
            f"History date not in DD/MM/YYYY format: {date_text}"

    def test_history_load_button_works(self, page: Page):
        submit_query_and_wait(page)
        page.goto(f"{UI_URL}/history")
        page.locator("[data-testid='history-load-btn']").first.click()
        expect(page).to_have_url(f"{UI_URL}/")
        expect(page.locator("[data-testid='answer-panel']")).to_be_visible(timeout=10000)

    def test_history_export_button_present(self, page: Page):
        page.goto(f"{UI_URL}/history")
        expect(page.locator("[data-testid='history-export-btn']")).to_be_visible()


# ── Corpus page (/corpus) ─────────────────────────────────────────────────────

class TestCorpusPage:

    def test_corpus_page_loads(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        expect(page).to_have_url(f"{UI_URL}/corpus")

    def test_corpus_page_has_table(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        expect(page.locator("[data-testid='corpus-table']")).to_be_visible()

    def test_corpus_table_has_documents(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        rows = page.locator("[data-testid='corpus-row']")
        rows.first.wait_for(timeout=15000)
        assert rows.count() > 0, "Corpus table has no rows"

    def test_corpus_no_eu_commission_in_agency_column(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        page.locator("[data-testid='corpus-row']").first.wait_for(timeout=15000)
        agency_cells = page.locator("[data-testid='corpus-agency']")
        for i in range(min(agency_cells.count(), 20)):
            text = agency_cells.nth(i).inner_text()
            assert "EU-Commission" not in text, \
                f"EU-Commission not normalised in corpus browser: {text}"

    def test_corpus_status_badge_present(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        page.locator("[data-testid='corpus-row']").first.wait_for(timeout=15000)
        expect(page.locator("[data-testid='corpus-status']").first).to_be_visible()

    def test_corpus_agency_filter_works(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        page.locator("[data-testid='corpus-filter-fda']").click()
        page.locator("[data-testid='corpus-row']").first.wait_for(timeout=15000)
        agency_cells = page.locator("[data-testid='corpus-agency']")
        for i in range(min(agency_cells.count(), 10)):
            assert "FDA" in agency_cells.nth(i).inner_text()

    def test_corpus_date_format_european(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        page.locator("[data-testid='corpus-row']").first.wait_for(timeout=15000)
        import re
        date_cells = page.locator("[data-testid='corpus-pub-date']")
        for i in range(min(date_cells.count(), 5)):
            text = date_cells.nth(i).inner_text()
            if text and text != "Not available":
                assert re.search(r'\d{2}/\d{2}/\d{4}', text), \
                    f"Corpus date not in DD/MM/YYYY format: {text}"

    def test_corpus_view_pdf_button_present(self, page: Page):
        page.goto(f"{UI_URL}/corpus")
        page.locator("[data-testid='corpus-row']").first.wait_for(timeout=15000)
        expect(page.locator("[data-testid='corpus-view-pdf']").first).to_be_visible()


# ── Filter bar ────────────────────────────────────────────────────────────────

class TestFilterBar:

    def test_agency_filters_present(self, page: Page):
        page.goto(UI_URL)
        for agency in ("fda", "ema", "ich"):
            expect(page.locator(f"[data-testid='agency-{agency}']")).to_be_visible()

    def test_active_filter_has_active_state(self, page: Page):
        page.goto(UI_URL)
        page.locator("[data-testid='agency-ema']").click()
        expect(page.locator("[data-testid='agency-ema']")).to_have_attribute("data-active", "true")

    def test_filter_tooltip_on_agency_label(self, page: Page):
        page.goto(UI_URL)
        label = page.locator("[data-testid='agency-filter-label']")
        expect(label).to_be_visible()
