"""A minimal Google Sheets v4 client for the one-way backup (spec §13.7).
Behind a Protocol so tests use an in-memory fake."""

from typing import Protocol
from urllib.parse import quote

import httpx

from app.services.errors import SheetSyncError

SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
_TIMEOUT = 20.0
RECONNECT_HINT = "reconnect Google to grant the drive.file permission"


class SheetsClient(Protocol):
    def create_spreadsheet(self, title: str, tab_titles: list[str]) -> str: ...

    def replace_tab(self, spreadsheet_id: str, tab: str, rows: list[list[str]]) -> None: ...


class GoogleSheetsClient:
    def __init__(self, access_token: str):
        self._headers = {"Authorization": f"Bearer {access_token}"}

    def _request(self, op: str, method: str, url: str, **kwargs) -> httpx.Response:
        # Errors never include response bodies, which can echo sheet data.
        try:
            response = httpx.request(method, url, headers=self._headers, timeout=_TIMEOUT, **kwargs)
        except httpx.HTTPError as exc:
            raise SheetSyncError(f"sheets {op} failed ({type(exc).__name__})") from None
        if not response.is_success:
            message = f"sheets {op} rejected (status {response.status_code})"
            if response.status_code in (401, 403):
                # Typically a Google connection made before drive.file was requested.
                message += f"; {RECONNECT_HINT}"
            raise SheetSyncError(message)
        return response

    def create_spreadsheet(self, title: str, tab_titles: list[str]) -> str:
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": t}} for t in tab_titles],
        }
        response = self._request("create", "POST", SHEETS_API, json=body)
        try:
            return response.json()["spreadsheetId"]
        except (ValueError, KeyError):
            raise SheetSyncError("sheets create returned no spreadsheet id") from None

    def replace_tab(self, spreadsheet_id: str, tab: str, rows: list[list[str]]) -> None:
        base = f"{SHEETS_API}/{quote(spreadsheet_id, safe='')}/values"
        whole_tab = quote(f"'{tab}'", safe="")
        self._request("clear", "POST", f"{base}/{whole_tab}:clear")
        # RAW: values are stored as typed text, never parsed as formulas.
        top_left = quote(f"'{tab}'!A1", safe="")
        self._request(
            "update",
            "PUT",
            f"{base}/{top_left}",
            params={"valueInputOption": "RAW"},
            json={"values": rows},
        )
