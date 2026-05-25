import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.yicare.or.kr"
TOY_SEARCH_URL = f"{BASE_URL}/main/main.php?categoryid=23&menuid=03&groupid=02"
AJAX_PRODUCT_URL = f"{BASE_URL}/logic/ajax_getProduct.php"
AJAX_NAME_PRODUCT_URL = f"{BASE_URL}/logic/ajax_getNameProduct.php"

DEFAULT_CONFIG = {
    "branch_no": "3",
    "branch_name": "구갈점",
    "target_product_name": "걸음마학습기-한글판",
    "target_product_no": "7563",
    "search_keyword": "걸음마학습기",
    "check_interval_seconds": 60,
    "checks_per_run": 5,
    "notify_when_available": True,
    "notify_when_no_available": False,
    "include_status_list": True,
    "timezone": "Asia/Seoul",
}

AVAILABLE_WORDS = ("대여가능", "예약가능")
UNAVAILABLE_WORDS = ("대여중", "대여불가", "예약중", "수리", "분실", "폐기")


def load_config(path: str) -> dict:
    config_path = Path(path)
    config = DEFAULT_CONFIG.copy()

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as config_file:
            config.update(json.load(config_file))

    config["branch_no"] = str(config["branch_no"])
    config["branch_name"] = str(config["branch_name"])
    config["target_product_name"] = str(config["target_product_name"])
    config["target_product_no"] = str(config.get("target_product_no") or "")
    config["search_keyword"] = str(
        config.get("search_keyword") or config["target_product_name"]
    )
    config["check_interval_seconds"] = max(10, int(config["check_interval_seconds"]))
    config["checks_per_run"] = max(1, int(config["checks_per_run"]))
    return config


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; YicareToyReservationChecker/1.0; "
                "+https://github.com/actions)"
            ),
            "Referer": TOY_SEARCH_URL,
        }
    )
    return session


def post_json(session: requests.Session, url: str, data: dict) -> object:
    response = session.post(url, data=data, timeout=20)
    response.raise_for_status()
    return response.json()


def post_text(session: requests.Session, url: str, data: dict) -> str:
    response = session.post(url, data=data, timeout=20)
    response.raise_for_status()
    return response.text


def strip_html(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_product_name(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def is_available(status: str) -> bool:
    normalized = re.sub(r"\s+", "", status)

    if any(word in normalized for word in UNAVAILABLE_WORDS):
        return False

    return any(word in normalized for word in AVAILABLE_WORDS)


def search_products(session: requests.Session, config: dict) -> list[dict]:
    body = {
        "no": "",
        "sch_st": "1",
        "page": "1",
        "categoryid": "23",
        "menuid": "03",
        "groupid": "02",
        "part": "0",
        "age": "0",
        "st": "0",
        "delivery_yn": "0",
        "product_name": config["search_keyword"],
    }
    search_html = post_text(session, f"{BASE_URL}/main/main.php", body)
    soup = BeautifulSoup(search_html, "html.parser")
    products = []

    for item in soup.select("li.pd_item"):
        link = item.find("a", onclick=True)
        if not link:
            continue

        onclick = link.get("onclick", "")
        product_match = re.search(r"getProduct\('(\d+)'\s*,\s*'(\d+)'\)", onclick)
        if not product_match:
            continue

        lines = [
            line.strip()
            for line in item.get_text("\n").splitlines()
            if line.strip()
        ]
        name = lines[0] if lines else ""
        cells = [cell.get_text(" ", strip=True) for cell in item.select("td")]
        products.append(
            {
                "product_no": product_match.group(1),
                "branch_no": product_match.group(2),
                "product_name": name,
                "area": cells[0] if len(cells) > 0 else "",
                "age": cells[1] if len(cells) > 1 else "",
                "available_count": int(cells[2]) if len(cells) > 2 and cells[2].isdigit() else 0,
            }
        )

    return products


def find_target_product_no(session: requests.Session, config: dict) -> str:
    if config["target_product_no"]:
        return config["target_product_no"]

    target = normalize_product_name(config["target_product_name"])
    products = search_products(session, config)
    for product in products:
        if normalize_product_name(product["product_name"]) == target:
            return product["product_no"]

    raise ValueError(
        f"{config['branch_name']}에서 '{config['target_product_name']}' 상품을 찾지 못했습니다."
    )


def fetch_target_status(config: dict) -> dict:
    session = make_session()
    product_no = find_target_product_no(session, config)
    product = post_json(
        session,
        AJAX_PRODUCT_URL,
        {"product_no": product_no, "data_branch_no": config["branch_no"]},
    )

    if not isinstance(product, dict) or product.get("json_flag") == "N":
        raise ValueError(f"잘못된 상품정보입니다: product_no={product_no}")

    product_name = str(product.get("product_name") or config["target_product_name"])
    rows = post_json(
        session,
        AJAX_NAME_PRODUCT_URL,
        {"product_name": product_name, "data_branch_no": config["branch_no"]},
    )
    if not isinstance(rows, list):
        raise ValueError("장난감 상세 대여상태 응답 형식이 예상과 다릅니다.")

    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        status = strip_html(row.get("rentstatus_name"))
        normalized_rows.append(
            {
                "product_no": str(row.get("product_no") or ""),
                "barcode": str(row.get("product_barcode") or ""),
                "status": status,
                "returndate": str(row.get("returndate") or "").strip(),
                "memo": strip_html(row.get("product_memo2")),
            }
        )

    available_rows = [row for row in normalized_rows if is_available(row["status"])]
    return {
        "product_no": product_no,
        "product_name": product_name,
        "area": strip_html(product.get("str_catename2")),
        "age": strip_html(product.get("product_age1")),
        "branch_name": config["branch_name"],
        "branch_no": config["branch_no"],
        "rows": normalized_rows,
        "available_rows": available_rows,
    }


def normalize_bot_token(value: str) -> str:
    token = value.strip()
    url_match = re.search(r"api\.telegram\.org/bot([^/\s]+)/?", token)
    if url_match:
        return url_match.group(1)
    if token.lower().startswith("bot") and ":" in token:
        return token[3:].strip()
    return token


def normalize_chat_id(value: str) -> str:
    chat_id = value.strip()
    chat_match = re.search(r'"chat"\s*:\s*\{[^{}]*"id"\s*:\s*(-?\d+)', chat_id)
    if chat_match:
        return chat_match.group(1)
    if re.fullmatch(r"-?\d+", chat_id):
        return chat_id
    id_match = re.search(r'"id"\s*:\s*(-?\d+)', chat_id)
    if id_match:
        return id_match.group(1)
    return chat_id


def send_telegram(message: str) -> None:
    token = normalize_bot_token(os.environ.get("TELEGRAM_BOT_TOKEN") or "")
    chat_id = normalize_chat_id(os.environ.get("TELEGRAM_CHAT_ID") or "")

    if not token or not chat_id:
        raise RuntimeError(
            "텔레그램 알림 발송에 필요한 TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        },
        timeout=20,
    )
    if not response.ok:
        raise RuntimeError(
            f"텔레그램 알림 발송 실패: HTTP {response.status_code} {response.text}"
        )


def format_row(row: dict) -> str:
    parts = [f"{row['barcode']}: {row['status']}"]
    if row["returndate"]:
        parts.append(f"반납예정일 {row['returndate']}")
    if row["memo"]:
        parts.append(f"특이사항 {row['memo']}")
    return " / ".join(parts)


def build_message(config: dict, checked_at: str, status: dict) -> str:
    available_rows = status["available_rows"]
    title = (
        "구갈점 장난감 예약 가능 알림"
        if available_rows
        else "구갈점 장난감 예약 확인 완료"
    )
    available_lines = (
        "\n".join(f"- {format_row(row)}" for row in available_rows)
        if available_rows
        else "- 가능한 장난감 없음"
    )

    message_parts = [
        title,
        f"- 대상: {status['branch_name']} / {status['product_name']}",
        f"- 상품번호: {status['product_no']}",
        f"- 확인 시간: {checked_at}",
        "",
        "가능한 장난감:",
        available_lines,
    ]

    if config.get("include_status_list", True):
        status_lines = "\n".join(f"- {format_row(row)}" for row in status["rows"])
        message_parts.extend(["", "전체 대여상태:", status_lines or "- 상태 없음"])

    message_parts.extend(["", f"링크: {TOY_SEARCH_URL}", "", "자동 예약은 하지 않았습니다."])
    return "\n".join(message_parts)


def run_once(config: dict) -> None:
    timezone = ZoneInfo(config["timezone"])
    checked_at = datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S %Z")

    print(f"[{checked_at}] 장난감 예약 상태 확인 시작")
    print(f"대상: {config['branch_name']} / {config['target_product_name']}")
    print(f"검색 페이지: {TOY_SEARCH_URL}")

    status = fetch_target_status(config)
    for row in status["rows"]:
        print(format_row(row))

    available_rows = status["available_rows"]
    print(f"대여 가능 수량: {len(available_rows)}")

    should_notify = (
        bool(available_rows) and config.get("notify_when_available", True)
    ) or (
        not available_rows and config.get("notify_when_no_available", False)
    )
    if not should_notify:
        print("설정에 따라 텔레그램 알림은 보내지 않습니다.")
        return

    message = build_message(config, checked_at, status)
    send_telegram(message)
    print("텔레그램 알림을 발송했습니다.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    checks_per_run = config["checks_per_run"] if args.loop else 1

    for check_index in range(1, checks_per_run + 1):
        if checks_per_run > 1:
            print(f"Check {check_index}/{checks_per_run}")
        run_once(config)

        if check_index < checks_per_run:
            time.sleep(config["check_interval_seconds"])

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        raise
