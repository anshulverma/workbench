from memory.extraction import format_triage_narrative, FACT_INGESTION_PROMPT


def test_format_triage_narrative_add_todo():
    card = {
        "id": "c1",
        "card_content": {"summary": "alice opened PR #100 to add rate limiting", "source_type": "github"},
        "options": [
            {"label": "Add todo (P1)", "action": "add_todo", "details": {"priority": "P1"}},
            {"label": "Skip", "action": "skip"},
        ],
        "relevance_score": 45,
    }
    response = {"card_id": "c1", "choice": 1}

    narrative = format_triage_narrative(card, response)

    assert "github" in narrative
    assert "alice opened PR #100" in narrative
    assert "Add todo (P1)" in narrative
    assert "User chose: 1" in narrative


def test_format_triage_narrative_skip():
    card = {
        "id": "c2",
        "card_content": {"summary": "CI bot notification", "source_type": "github"},
        "options": [
            {"label": "Add todo (P1)", "action": "add_todo"},
            {"label": "Skip", "action": "skip"},
        ],
        "relevance_score": 20,
    }
    response = {"card_id": "c2", "choice": 2}

    narrative = format_triage_narrative(card, response)

    assert "Skip" in narrative
    assert "User chose: 2" in narrative


def test_fact_ingestion_prompt_exists():
    assert "preference patterns" in FACT_INGESTION_PROMPT
    assert "always" in FACT_INGESTION_PROMPT
    assert "never" in FACT_INGESTION_PROMPT


def test_format_triage_narrative_mute():
    card = {
        "id": "c3",
        "card_content": {"summary": "Weekly digest email", "source_type": "email"},
        "options": [
            {"label": "Add todo (P2)", "action": "add_todo"},
            {"label": "Skip", "action": "skip"},
            {"label": "Never surface emails like this", "action": "mute_pattern"},
        ],
        "relevance_score": 15,
    }
    response = {"card_id": "c3", "choice": 3}

    narrative = format_triage_narrative(card, response)

    assert "Never surface emails like this" in narrative
    assert "email" in narrative
