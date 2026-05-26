import httpx
from .exceptions import EGovAPIError, LawNotFoundError, XMLParseError
from .models import LawSearchResult

BASE_URL = "https://laws.e-gov.go.jp/api/2"
TIMEOUT = 90.0

LAW_TYPE_MAP = {
    "Act": "法律",
    "CabinetOrder": "政令",
    "MinisterialOrdinance": "省令",
    "Rule": "規則",
    "Proclamation": "告示",
    "Notice": "通達",
    "Treaty": "条約",
}

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=TIMEOUT,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def search_laws(query: str) -> list[LawSearchResult]:
    client = get_client()
    try:
        resp = await client.get(
            "/laws",
            params={"law_title": query, "response_format": "json"},
        )
    except httpx.TimeoutException:
        raise EGovAPIError(504, "e-Govへの接続がタイムアウトしました")
    except httpx.RequestError as e:
        raise EGovAPIError(503, f"e-Govへの接続に失敗しました: {e}")

    if resp.status_code != 200:
        raise EGovAPIError(resp.status_code, f"e-Gov APIがエラーを返しました (HTTP {resp.status_code})")

    data = resp.json()
    laws = data.get("laws") or []
    if not laws:
        raise LawNotFoundError(query)

    results = []
    for entry in laws:
        info = entry.get("law_info", {})
        rev = entry.get("revision_info") or entry.get("current_revision_info") or {}
        raw_type = info.get("law_type", "")
        results.append(LawSearchResult(
            law_id=info.get("law_id", ""),
            law_num=info.get("law_num", ""),
            law_title=rev.get("law_title", ""),
            law_type=LAW_TYPE_MAP.get(raw_type, raw_type),
            promulgation_date=info.get("promulgation_date"),
        ))
    return results


async def get_law_data(law_id: str) -> dict:
    """
    Fetch law content from e-Gov API.
    Returns dict with:
      - tree: the law_full_text JSON tree
      - promulgation_date: ISO date string
      - law_title: from revision_info
      - law_type: Japanese string
    """
    client = get_client()
    try:
        resp = await client.get(
            f"/law_data/{law_id}",
            params={"response_format": "json"},
        )
    except httpx.TimeoutException:
        raise EGovAPIError(504, "法令本文の取得がタイムアウトしました（大きな法令の場合は時間がかかります）")
    except httpx.RequestError as e:
        raise EGovAPIError(503, f"e-Govへの接続に失敗しました: {e}")

    if resp.status_code == 404:
        raise EGovAPIError(404, f"法令ID '{law_id}' が見つかりません")
    if resp.status_code != 200:
        raise EGovAPIError(resp.status_code, f"e-Gov APIがエラーを返しました (HTTP {resp.status_code})")

    data = resp.json()
    tree = data.get("law_full_text")
    if not tree or not isinstance(tree, dict):
        raise XMLParseError("APIレスポンスに法令データが含まれていません")

    info = data.get("law_info", {})
    rev = data.get("revision_info") or data.get("current_revision_info") or {}
    raw_type = info.get("law_type", "")

    return {
        "tree": tree,
        "promulgation_date": info.get("promulgation_date"),
        "law_title_from_api": rev.get("law_title", ""),
        "law_type": LAW_TYPE_MAP.get(raw_type, raw_type),
        "law_num": info.get("law_num", ""),
    }


# Keep old name as alias for compatibility during migration
async def get_law_tree(law_id: str) -> dict:
    result = await get_law_data(law_id)
    return result["tree"]
