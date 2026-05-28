import json
from datetime import datetime
from workbench.storage.base import TriageStore
from workbench.models import TriageCard, TriageOption, TriageResponse


class SqliteTriageStore(TriageStore):
    def __init__(self, db):
        self.db = db

    async def get_pending(self) -> list[TriageCard]:
        cursor = await self.db.execute(
            "SELECT * FROM triage_cards WHERE responded_at IS NULL ORDER BY sent_at ASC"
        )
        rows = await cursor.fetchall()
        return [self._row_to_card(r) for r in rows]

    async def save_card(self, card: TriageCard) -> TriageCard:
        await self.db.execute(
            "INSERT OR REPLACE INTO triage_cards (id, item_id, card_content, options, sent_at, responded_at, response) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                card.id,
                card.item_id,
                json.dumps(card.card_content),
                json.dumps([o.model_dump() for o in card.options]),
                card.sent_at.isoformat() if card.sent_at else None,
                card.responded_at.isoformat() if card.responded_at else None,
                card.response,
            ),
        )
        await self.db.commit()
        return card

    async def record_response(self, card_id: str, response: TriageResponse) -> None:
        await self.db.execute(
            "UPDATE triage_cards SET responded_at = ?, response = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), json.dumps(response.model_dump()), card_id),
        )
        await self.db.commit()

    async def get_card(self, card_id: str) -> TriageCard | None:
        cursor = await self.db.execute("SELECT * FROM triage_cards WHERE id = ?", (card_id,))
        row = await cursor.fetchone()
        return self._row_to_card(row) if row else None

    def _row_to_card(self, row) -> TriageCard:
        options_data = json.loads(row["options"])
        return TriageCard(
            id=row["id"],
            item_id=row["item_id"],
            card_content=json.loads(row["card_content"]),
            options=[TriageOption(**o) for o in options_data],
            sent_at=row["sent_at"],
            responded_at=row["responded_at"],
            response=row["response"],
        )
