from workbench.models import (
    DiffMetadata,
    DiffRisk,
    DiffHunkSection,
    DiffCardContent,
    CardLink,
    CardSection,
    ThreadHunk,
    CardMessage,
    TriageOption,
    ChangeContext,
    TriageCard,
)


def test_diff_card_content_round_trips():
    content = DiffCardContent(
        metadata=DiffMetadata(author="alice", team="infra", status="needs_review"),
        summary="Adds a retry loop to the client.",
        risk=DiffRisk(
            factors=["touches retry path"], watch_outs=["no test for backoff"]
        ),
        why_care="You own this client.",
        hunks=[
            DiffHunkSection(
                file="client.py",
                header="@@ -10,7 +10,9 @@",
                code="+    retry()\n-    pass",
                annotation="adds retry call",
                rank=1,
            )
        ],
    )
    dumped = content.model_dump()
    assert dumped["metadata"]["team"] == "infra"
    assert dumped["hunks"][0]["rank"] == 1
    assert dumped["hunks"][0]["expandable"] is True
    again = DiffCardContent(**dumped)
    assert again.hunks[0].file == "client.py"


def test_diff_metadata_team_optional():
    m = DiffMetadata(author="bob", status="accepted")
    assert m.team is None


def test_diff_card_content_defaults_empty_collections():
    content = DiffCardContent(
        metadata=DiffMetadata(author="a", status="s"),
        summary="s",
        risk=DiffRisk(),
        why_care="w",
    )
    assert content.hunks == []
    assert content.risk.factors == []
    assert content.risk.watch_outs == []


def test_card_message_defaults():
    msg = CardMessage(header="Diff D123")
    assert msg.sections == []
    assert msg.links == []
    assert msg.options == []
    assert msg.thread_hunks == []


def test_card_message_full_shape():
    msg = CardMessage(
        header="Diff D123",
        sections=[CardSection(title="Summary", body="does X", monospace=False)],
        links=[CardLink(label="View in Phabricator", url="https://phab/D123")],
        options=[TriageOption(label="Add P1", action="add_todo")],
        thread_hunks=[ThreadHunk(file="a.py", header="@@", code="+x", rank=1)],
    )
    assert msg.sections[0].title == "Summary"
    assert msg.links[0].url == "https://phab/D123"
    assert msg.thread_hunks[0].rank == 1


def test_change_context_round_trips():
    ctx = ChangeContext(
        change_type="code_updated",
        changed_fields={"status": {"old": "needs_review", "new": "accepted"}},
        change_summary="status changed; new diff version",
        previous_triage_action="defer",
        previous_priority="P2",
    )
    dumped = ctx.model_dump()
    again = ChangeContext.model_validate(dumped)
    assert again.change_type == "code_updated"
    assert again.changed_fields["status"]["new"] == "accepted"


def test_change_context_defaults():
    ctx = ChangeContext(
        change_type="status_changed", changed_fields={}, change_summary="s"
    )
    assert ctx.previous_triage_action is None
    assert ctx.previous_priority is None


def test_triage_card_has_optional_thread_name():
    card = TriageCard(card_content={"summary": "x"})
    assert card.thread_name is None
    card2 = TriageCard(card_content={"summary": "x"}, thread_name="spaces/A/threads/T1")
    assert card2.thread_name == "spaces/A/threads/T1"
