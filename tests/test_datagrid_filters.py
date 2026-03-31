"""Tests for DataGrid filter behavior using Playwright."""

import time

import pytest
from playwright.sync_api import Page, expect


def _setup_system(page: Page, app: dict):
    """Add ROM and DAT paths, sync, then click the SNES system."""
    # Open settings
    page.click("#btn-settings")
    page.wait_for_selector("#settings-modal.is-open")

    # Navigate to ROMs tab and add ROM path
    page.click(".settings-nav-item[data-panel='roms']")
    page.wait_for_selector("#settings-roms.active")
    page.click("#btn-add-rom-path")
    page.wait_for_selector("#addpath-modal.is-open")
    page.fill("#addpath-path", str(app["rom_root"]))
    page.click("#addpath-form button[type=submit]")
    page.wait_for_timeout(500)

    # Navigate to DATs tab and add DAT path
    page.click(".settings-nav-item[data-panel='dats']")
    page.wait_for_selector("#settings-dats.active")
    page.click("#btn-add-dat-path")
    page.wait_for_selector("#addpath-modal.is-open")
    page.fill("#addpath-path", str(app["dat_dir"]))
    page.click("#addpath-form button[type=submit]")
    page.wait_for_timeout(500)

    # Close confirm sync modal if it appears
    if page.locator("#confirm-sync-yes").is_visible():
        page.click("#confirm-sync-yes")
        # Wait for sync to complete
        page.wait_for_selector("#scan-log-title:has-text('Complete')", timeout=15000)

    # Close settings if open
    if page.locator("#settings-modal.is-open").count() > 0:
        page.click("#settings-modal .modal-close")

    # Click the SNES system in sidebar
    page.click("#system-tree li:has-text('Nintendo - SNES')")
    page.wait_for_selector("#game-list:not([hidden])")
    page.wait_for_timeout(300)


def _open_game_filter(page: Page):
    """Open the Game column filter dialog."""
    page.click(".dg-th-label:has-text('Game')")
    page.wait_for_selector(".dg-filter-dialog")


def _open_status_filter(page: Page):
    """Open the Status column filter dialog."""
    page.click(".dg-th-label:has-text('Status')")
    page.wait_for_selector(".dg-filter-dialog")


def _get_visible_row_count(page: Page) -> int:
    """Count visible rows in the DataGrid."""
    return page.locator(".dg-row").count()


def _get_filter_items(page: Page) -> list[dict]:
    """Get all items in the open filter dialog with their checked state."""
    items = []
    for label in page.locator(".dg-filter-item").all():
        cb = label.locator("input[type=checkbox]")
        text = label.inner_text().strip()
        checked = cb.is_checked()
        items.append({"text": text, "checked": checked})
    return items


class TestFilterBasics:
    """Test basic filter open/close and state."""

    def test_default_status_filter_hides_missing(self, page, app):
        """Missing games should be hidden by default via status filter."""
        _setup_system(page, app)
        # Should see 5 owned games, not 8 total
        assert _get_visible_row_count(page) == 5

    def test_status_filter_shows_dot_when_active(self, page, app):
        """Status column header should show a dot indicating active filter."""
        _setup_system(page, app)
        dot = page.locator(".dg-th:has-text('Status') .dg-th-filter-dot")
        expect(dot).to_have_text(" ●")

    def test_open_status_filter_shows_all_values(self, page, app):
        """Opening status filter shows all unique statuses with correct checked state."""
        _setup_system(page, app)
        _open_status_filter(page)
        items = _get_filter_items(page)
        statuses = {i["text"] for i in items}
        assert "missing" in statuses
        assert "unverified" in statuses
        # missing should be unchecked
        missing_item = next(i for i in items if i["text"] == "missing")
        assert not missing_item["checked"]


class TestFilterSearch:
    """Test filter search box behavior."""

    def test_search_filters_checkbox_list(self, page, app):
        """Typing in search box should filter the checkbox list."""
        _setup_system(page, app)
        _open_game_filter(page)
        page.fill(".dg-filter-search", "Test")
        items = _get_filter_items(page)
        # Should only show items containing "test"
        for item in items:
            assert "test" in item["text"].lower()

    def test_search_text_persists_on_reopen(self, page, app):
        """Search text should be preserved when reopening the filter."""
        _setup_system(page, app)
        _open_game_filter(page)
        page.fill(".dg-filter-search", "Alpha")
        # Close by clicking outside
        page.click("#game-list-title")
        page.wait_for_timeout(200)
        # Reopen
        _open_game_filter(page)
        search_val = page.input_value(".dg-filter-search")
        assert search_val == "Alpha"


class TestFilterAllNone:
    """Test All/None button behavior."""

    def test_none_unchecks_all_and_shows_full_list(self, page, app):
        """Clicking None should uncheck all visible items and show full list."""
        _setup_system(page, app)
        _open_game_filter(page)
        page.click(".dg-filter-controls a:has-text('None')")
        page.wait_for_timeout(200)
        items = _get_filter_items(page)
        # All items should be unchecked
        for item in items:
            assert not item["checked"], f"{item['text']} should be unchecked"
        # Table should show 0 rows
        assert _get_visible_row_count(page) == 0

    def test_all_checks_all_visible(self, page, app):
        """Clicking All should check all visible items."""
        _setup_system(page, app)
        _open_game_filter(page)
        # First click None
        page.click(".dg-filter-controls a:has-text('None')")
        page.wait_for_timeout(200)
        # Then click All
        page.click(".dg-filter-controls a:has-text('All')")
        page.wait_for_timeout(200)
        items = _get_filter_items(page)
        for item in items:
            assert item["checked"], f"{item['text']} should be checked"

    def test_all_with_search_only_checks_visible(self, page, app):
        """With search text, All should only check matching items."""
        _setup_system(page, app)
        _open_game_filter(page)
        # Click None first
        page.click(".dg-filter-controls a:has-text('None')")
        page.wait_for_timeout(200)
        # Type search
        page.fill(".dg-filter-search", "Test")
        page.wait_for_timeout(200)
        # Click All — should only check "test" items
        page.click(".dg-filter-controls a:has-text('All')")
        page.wait_for_timeout(200)
        items = _get_filter_items(page)
        for item in items:
            assert item["checked"], f"{item['text']} should be checked"
        # Clear search to see all items
        page.fill(".dg-filter-search", "")
        page.wait_for_timeout(200)
        all_items = _get_filter_items(page)
        # Non-test items should still be unchecked
        non_test = [i for i in all_items if "test" not in i["text"].lower()]
        for item in non_test:
            assert not item["checked"], f"{item['text']} should be unchecked"


class TestFilterReopen:
    """Test filter state when reopening."""

    def test_reopen_shows_all_items_with_correct_state(self, page, app):
        """Reopening a filter should show ALL items with correct checked/unchecked state."""
        _setup_system(page, app)
        _open_game_filter(page)
        total_items = len(_get_filter_items(page))
        # Click None then check just one item
        page.click(".dg-filter-controls a:has-text('None')")
        page.wait_for_timeout(200)
        first_cb = page.locator(".dg-filter-item input[type=checkbox]").first
        first_cb.check()
        page.wait_for_timeout(200)
        # Close filter
        page.click("#game-list-title")
        page.wait_for_timeout(200)
        # Reopen — should show ALL items, one checked, rest unchecked
        _open_game_filter(page)
        items = _get_filter_items(page)
        assert len(items) == total_items, f"Expected {total_items} items, got {len(items)}"
        checked = [i for i in items if i["checked"]]
        unchecked = [i for i in items if not i["checked"]]
        assert len(checked) == 1, f"Expected 1 checked, got {len(checked)}"
        assert len(unchecked) == total_items - 1

    def test_reopen_after_none_shows_all_unchecked(self, page, app):
        """After clicking None and closing, reopening shows all items unchecked."""
        _setup_system(page, app)
        _open_game_filter(page)
        total_items = len(_get_filter_items(page))
        page.click(".dg-filter-controls a:has-text('None')")
        page.wait_for_timeout(200)
        # Close and reopen
        page.click("#game-list-title")
        page.wait_for_timeout(200)
        _open_game_filter(page)
        items = _get_filter_items(page)
        assert len(items) == total_items, f"Expected {total_items} items, got {len(items)}"
        for item in items:
            assert not item["checked"], f"{item['text']} should be unchecked"


class TestCrossColumnFilters:
    """Test interaction between filters on different columns."""

    def test_game_filter_respects_status_filter(self, page, app):
        """Game filter should only show values that pass the status filter."""
        _setup_system(page, app)
        # Default: status filter excludes "missing"
        _open_game_filter(page)
        items = _get_filter_items(page)
        # Should only show owned games (5), not all 8
        assert len(items) == 5

    def test_warning_shows_when_other_filters_active(self, page, app):
        """Filter dialog should warn when other columns have active filters."""
        _setup_system(page, app)
        _open_game_filter(page)
        warn = page.locator(".dg-filter-warn")
        expect(warn).to_be_visible()
        expect(warn).to_contain_text("Additional filters applied: Status")


class TestAnalysisFilterFocus:
    """Test that analysis applies a focused filter on completion."""

    def test_analysis_filters_to_analyzed_game(self, page, app):
        """After analyzing a ROM, grid should filter to show only the analyzed game with all statuses."""
        _setup_system(page, app)

        # Remember total visible rows before analysis
        total_before = _get_visible_row_count(page)
        assert total_before == 5  # 5 owned games

        # Click the first row to select it
        first_row = page.locator(".dg-row").first
        game_name = first_row.locator(".dg-td").nth(1).inner_text().strip()
        first_row.click()
        page.wait_for_timeout(200)

        # Click Analyze
        page.click("#btn-analyze")
        # Wait for analysis to complete
        page.wait_for_selector("#verify-log:has-text('Analysis complete')", timeout=15000)
        page.wait_for_timeout(500)

        # Grid should now be filtered to only the analyzed game
        visible_after = _get_visible_row_count(page)
        assert visible_after < total_before, "Grid should be filtered to fewer rows after analysis"
        assert visible_after >= 1, "At least the analyzed game should be visible"

        # All visible rows should have the analyzed game's name
        for row in page.locator(".dg-row").all():
            row_game = row.locator(".dg-td").nth(1).inner_text().strip()
            assert row_game == game_name, f"Expected '{game_name}', got '{row_game}'"

        # Status filter should show all owned statuses but not "missing"
        _open_status_filter(page)
        items = _get_filter_items(page)
        for item in items:
            if item["text"] == "missing":
                assert not item["checked"], "Status 'missing' should not be checked after analysis"
            else:
                assert item["checked"], f"Status '{item['text']}' should be checked after analysis"


class TestStaleDataNotification:
    """Test that stale DB data triggers a status bar notification."""

    def test_stale_systems_shown_after_config_cleared(self, page, app):
        """After setting up a system and clearing config, status bar should warn about stale data."""
        _setup_system(page, app)

        # We now have scan results in the DB. Clear the config paths.
        import json
        import urllib.request

        base = app["url"]

        # Get current ROM paths and remove them all
        req = urllib.request.Request(base + "/api/roms/paths")
        with urllib.request.urlopen(req) as resp:
            rom_paths = json.loads(resp.read())
        for rp in rom_paths:
            data = json.dumps({"path": rp["path"], "system": rp["system"]}).encode()
            req = urllib.request.Request(
                base + "/api/roms/paths",
                data=data,
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            urllib.request.urlopen(req)

        # Reload page — should show stale data warning
        page.reload()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        status_text = page.locator("#status-text").inner_text()
        assert "removed paths" in status_text.lower() or "stale" in status_text.lower(), \
            f"Expected stale data warning, got: {status_text}"


class TestSettingsPanel:
    """Test settings panel behavior."""

    def test_theme_radio_defaults_to_auto_toolbar(self, page, app):
        """Opening settings via toolbar should show 'auto' theme selected."""
        page.click("#btn-settings")
        page.wait_for_selector("#settings-modal.is-open")
        page.wait_for_timeout(500)

        auto_radio = page.locator('input[name="theme"][value="auto"]')
        assert auto_radio.is_checked(), "Auto theme radio should be checked by default"

    def test_theme_radio_defaults_to_auto_welcome(self, page, app):
        """Opening settings via welcome page should show 'auto' theme selected."""
        # Welcome page is shown on fresh start with no paths configured
        welcome_btn = page.locator("#welcome-settings")
        if welcome_btn.is_visible():
            welcome_btn.click()
        else:
            page.click("#btn-settings")
        page.wait_for_selector("#settings-modal.is-open")
        page.wait_for_timeout(500)

        auto_radio = page.locator('input[name="theme"][value="auto"]')
        assert auto_radio.is_checked(), "Auto theme radio should be checked via welcome button"

    def test_config_path_shown_in_general_panel(self, page, app):
        """General settings panel should display the config file path."""
        page.click("#btn-settings")
        page.wait_for_selector("#settings-modal.is-open")
        page.wait_for_timeout(500)

        link = page.locator("#config-path-link")
        path_text = link.inner_text()
        assert "config.toml" in path_text, f"Expected config.toml path, got: {path_text}"

    def test_stale_warning_after_paths_removed(self, page, app):
        """Status bar should warn about stale data when config paths are removed but DB has results."""
        _setup_system(page, app)

        # Remove all ROM paths via API
        import json
        import urllib.request

        base = app["url"]
        req = urllib.request.Request(base + "/api/roms/paths")
        with urllib.request.urlopen(req) as resp:
            rom_paths = json.loads(resp.read())
        for rp in rom_paths:
            data = json.dumps({"path": rp["path"], "system": rp["system"]}).encode()
            req = urllib.request.Request(
                base + "/api/roms/paths",
                data=data,
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            urllib.request.urlopen(req)

        # Remove all DAT paths via API
        req = urllib.request.Request(base + "/api/dats/paths")
        with urllib.request.urlopen(req) as resp:
            dat_paths = json.loads(resp.read())
        for dp in dat_paths:
            data = json.dumps({"path": dp["path"], "system": dp["system"]}).encode()
            req = urllib.request.Request(
                base + "/api/dats/paths",
                data=data,
                headers={"Content-Type": "application/json"},
                method="DELETE",
            )
            urllib.request.urlopen(req)

        # Reload and check status bar
        page.reload()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        status_text = page.locator("#status-text").inner_text()
        assert "removed paths" in status_text.lower(), \
            f"Expected stale data warning, got: {status_text}"
