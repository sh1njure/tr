"""Notion: find the latest record with empty screenshot columns and fill them."""
import logging
from dataclasses import dataclass, field
from typing import Optional

from notion_client import Client

log = logging.getLogger("tvsnap.notion")


class NotionError(Exception):
    pass


@dataclass
class Record:
    id: str
    url: str
    pair: str
    date: str
    setup: str
    empty_columns: list = field(default_factory=list)

    def summary(self) -> str:
        return f"{self.pair or '—'} | {self.date or '—'} | {self.setup or '—'}"


def _plain(prop: Optional[dict]) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop.get(t) or [])
    if t == "date":
        d = prop.get("date") or {}
        return d.get("start") or ""
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "url":
        return prop.get("url") or ""
    return ""


class NotionDB:
    def __init__(self, token: str, cfg: dict):
        self.cfg = cfg
        self.ncfg = cfg["notion"]
        self.db_id = self.ncfg["database_id"]
        self.client = Client(auth=token)
        self._schema: Optional[dict] = None

    @property
    def columns(self) -> list:
        return [t["column"] for t in self.cfg["timeframes"]]

    def schema(self) -> dict:
        """{property name: type}"""
        if self._schema is None:
            db = self.client.databases.retrieve(database_id=self.db_id)
            self._schema = {name: p["type"] for name, p in db["properties"].items()}
        return self._schema

    def schema_text(self) -> str:
        return "\n".join(f"  {n}: {t}" for n, t in sorted(self.schema().items()))

    def check_columns(self) -> list:
        """Problems with screenshot columns; empty list = OK."""
        s = self.schema()
        problems = []
        for col in self.columns:
            if col not in s:
                problems.append(f"нет колонки «{col}» (создать тип URL)")
            elif s[col] != "url":
                problems.append(f"колонка «{col}» имеет тип {s[col]}, нужен URL")
        return problems

    def _pair_filter(self, pair: str) -> Optional[dict]:
        name = self.ncfg.get("pair_property")
        ptype = self.schema().get(name)
        if ptype in ("title", "rich_text"):
            return {"property": name, ptype: {"contains": pair}}
        if ptype == "select":
            return {"property": name, "select": {"equals": pair}}
        log.warning("Колонка пары «%s» не найдена/не поддерживается (%s) — без фильтра по паре", name, ptype)
        return None

    def _sorts(self) -> list:
        date_prop = self.ncfg.get("date_property")
        sorts = []
        if date_prop and self.schema().get(date_prop) == "date":
            sorts.append({"property": date_prop, "direction": "descending"})
        sorts.append({"timestamp": "created_time", "direction": "descending"})
        return sorts

    def _to_record(self, page: dict) -> Record:
        props = page["properties"]
        return Record(
            id=page["id"],
            url=page["url"],
            pair=_plain(props.get(self.ncfg.get("pair_property"))),
            date=_plain(props.get(self.ncfg.get("date_property"))) or page.get("created_time", "")[:10],
            setup=_plain(props.get(self.ncfg.get("setup_property"))),
            empty_columns=[c for c in self.columns if not _plain(props.get(c))],
        )

    def find_latest(self, pair: Optional[str] = None) -> Optional[Record]:
        problems = self.check_columns()
        if problems:
            raise NotionError("Колонки скринов не готовы:\n" + "\n".join(problems))
        conds = [{"property": c, "url": {"is_empty": True}} for c in self.columns]
        if pair:
            pf = self._pair_filter(pair)
            if pf:
                conds.append(pf)
        resp = self.client.databases.query(
            database_id=self.db_id,
            filter={"and": conds},
            sorts=self._sorts(),
            page_size=1,
        )
        results = resp.get("results") or []
        if not results:
            return None
        rec = self._to_record(results[0])
        log.info("Найдена запись: %s %s", rec.summary(), rec.url)
        return rec

    def write_links(self, page_id: str, links_by_column: dict) -> tuple:
        """Writes only into currently empty columns. Returns (written, skipped_non_empty)."""
        page = self.client.pages.retrieve(page_id=page_id)
        props = page["properties"]
        update, skipped = {}, []
        for col, link in links_by_column.items():
            if _plain(props.get(col)):
                skipped.append(col)
            else:
                update[col] = {"url": link}
        if update:
            self.client.pages.update(page_id=page_id, properties=update)
        log.info("Записано: %s; пропущено (не пусто): %s", list(update), skipped)
        return list(update), skipped
