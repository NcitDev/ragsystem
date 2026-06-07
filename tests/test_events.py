from pathlib import Path

from rag.core.events import discover_event_entries, render_event_catalog


def test_discover_event_entries_finds_constants_and_tracking_methods(tmp_path: Path):
    repo = tmp_path / "repo"
    events_dir = repo / "domain" / "analytics"
    events_dir.mkdir(parents=True)
    (events_dir / "payment.kt").write_text(
        "\n".join(
            [
                'const val START_ORDER_POLLING_AFTER_PAYMENT = "Start Order Polling After Payment"',
                "object PaymentAnalytics {",
                "    fun orderPollingAfterPaymentStart(type: String) = Unit",
                "}",
                "class AnalyticsHelper {",
                "    fun trackPaymentFinished(type: String) = Unit",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    entries = discover_event_entries(repo)
    names = {entry.name for entry in entries}

    assert "START_ORDER_POLLING_AFTER_PAYMENT" in names
    assert "orderPollingAfterPaymentStart" in names
    assert "trackPaymentFinished" in names


def test_render_event_catalog_includes_search_terms_and_locations():
    catalog = render_event_catalog(
        "dodo",
        [
            *discover_event_entries(Path(__file__).parent / "missing"),
        ],
    )

    assert "# dodo Analytics And Event Catalog" in catalog


def test_render_event_catalog_humanizes_event_names(tmp_path: Path):
    repo = tmp_path / "repo"
    events_dir = repo / "domain" / "analytics"
    events_dir.mkdir(parents=True)
    (events_dir / "payment.kt").write_text(
        'const val START_ORDER_POLLING_AFTER_PAYMENT = "Start Order Polling After Payment"',
        encoding="utf-8",
    )

    catalog = render_event_catalog("dodo", discover_event_entries(repo))

    assert "`START_ORDER_POLLING_AFTER_PAYMENT`" in catalog
    assert "start order polling after payment" in catalog.lower()
    assert "payment.kt:1" in catalog
