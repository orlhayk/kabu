from __future__ import annotations

import csv
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT / "secrets"
CLIENT_SECRET_FILE = SECRETS_DIR / "google-oauth-client.json"
TOKEN_FILE = SECRETS_DIR / "google-token.json"
SHEETS_CSV = ROOT / "data" / "sheets_candidates.csv"
RATIONALE_CSV = ROOT / "data" / "sheets_rationale.csv"
MEMO_CSV = ROOT / "data" / "sheets_morning_memo.csv"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1iWOTH1B96-J0wGQd3OrTAJZw369RfHYDbC78SLZL2nY"
CANDIDATES_SHEET = "候補一覧"
RATIONALE_SHEET = "判断根拠"
LEGACY_RATIONALE_SHEET = "候補詳細"
SUMMARY_SHEET = "朝メモ"


def read_csv_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle)]


def load_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_sheet_map(service) -> dict[str, int]:
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    mapping: dict[str, int] = {}
    for sheet in spreadsheet.get("sheets", []):
        props = sheet["properties"]
        mapping[props["title"]] = props["sheetId"]
    return mapping


def ensure_sheets(service, titles: list[str]) -> dict[str, int]:
    existing = get_sheet_map(service)
    requests = []
    if LEGACY_RATIONALE_SHEET in existing and RATIONALE_SHEET not in existing:
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": existing[LEGACY_RATIONALE_SHEET], "title": RATIONALE_SHEET},
                    "fields": "title",
                }
            }
        )
        existing[RATIONALE_SHEET] = existing[LEGACY_RATIONALE_SHEET]
        del existing[LEGACY_RATIONALE_SHEET]
    for title in titles:
        if title not in existing:
            requests.append({"addSheet": {"properties": {"title": title}}})

    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests},
        ).execute()

    return get_sheet_map(service)


def update_sheet_values(service, title: str, rows: list[list[str]]) -> None:
    body = {"values": rows}
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=title,
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{title}!A1",
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()


def format_sheet(service, title: str, sheet_id: int, column_count: int) -> None:
    column_sizes = {
        CANDIDATES_SHEET: [160, 160, 72, 72, 88, 80, 92, 88, 88, 72, 72, 72, 96, 96, 82],
        RATIONALE_SHEET: [160, 160, 76, 170, 72, 72, 88, 80, 92, 88, 88, 72, 72, 72, 170, 170, 240, 420, 82],
        SUMMARY_SHEET: [160, 160, 360, 72, 72, 88, 80, 92, 88, 88, 72, 72, 72, 82],
    }
    size_list = column_sizes.get(title, [])
    requests = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "clearBasicFilter": {
                "sheetId": sheet_id,
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": max(column_count, 1),
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.95, "green": 0.91, "blue": 0.82},
                        "textFormat": {"bold": True, "fontSize": 10},
                        "wrapStrategy": "CLIP",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": max(column_count, 1),
                },
                "cell": {
                    "userEnteredFormat": {
                        "wrapStrategy": "CLIP",
                        "verticalAlignment": "TOP",
                    }
                },
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
            }
        },
    ]
    for index in range(max(column_count, 1)):
        pixel_size = size_list[index] if index < len(size_list) else 100
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"pixelSize": pixel_size},
                    "fields": "pixelSize",
                }
            }
        )
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()


def main() -> None:
    creds = load_credentials()
    service = build("sheets", "v4", credentials=creds)

    candidates_rows = read_csv_rows(SHEETS_CSV)
    detail_rows = read_csv_rows(RATIONALE_CSV)
    summary_rows = read_csv_rows(MEMO_CSV)

    sheet_map = ensure_sheets(service, [CANDIDATES_SHEET, RATIONALE_SHEET, SUMMARY_SHEET])

    update_sheet_values(service, CANDIDATES_SHEET, candidates_rows)
    update_sheet_values(service, RATIONALE_SHEET, detail_rows)
    update_sheet_values(service, SUMMARY_SHEET, summary_rows)

    format_sheet(service, CANDIDATES_SHEET, sheet_map[CANDIDATES_SHEET], len(candidates_rows[0]) if candidates_rows else 1)
    format_sheet(service, RATIONALE_SHEET, sheet_map[RATIONALE_SHEET], len(detail_rows[0]) if detail_rows else 1)
    format_sheet(service, SUMMARY_SHEET, sheet_map[SUMMARY_SHEET], len(summary_rows[0]) if summary_rows else 1)

    print(json.dumps({"spreadsheet_id": SPREADSHEET_ID, "updated": [CANDIDATES_SHEET, RATIONALE_SHEET, SUMMARY_SHEET]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
