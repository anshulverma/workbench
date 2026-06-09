import os

CONTEXT = os.path.join(os.path.dirname(__file__), "..", "CONTEXT.md")


def _text():
    with open(CONTEXT) as f:
        return f.read()


def test_memory_caps_drift_corrected():
    text = _text()
    assert "without caps" not in text
    # The real contract: entity 5 / preference 20 / relationship 10.
    assert "entity 5" in text or "entity facts (cap 5" in text


def test_new_terms_present():
    text = _text()
    for term in [
        "Card Presenter",
        "Card Content Schema",
        "Card Content Generator",
        "CardMessage",
        "Diff Enricher",
    ]:
        assert term in text, f"missing CONTEXT term: {term}"


def test_change_monitoring_terms_present():
    text = _text()
    for term in [
        "ChangeDetector",
        "ChangeResult",
        "material change",
        "terminal state",
        "stable source_id",
        "re-triage",
        "ChangeContext",
        "DebounceManager",
        "diff_version",
        "code_updated",
    ]:
        assert term in text, f"missing CONTEXT term: {term}"
