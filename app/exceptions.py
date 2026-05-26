class EGovAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"e-Gov API error {status_code}: {message}")


class LawNotFoundError(Exception):
    def __init__(self, query: str):
        self.query = query
        super().__init__(f"法令が見つかりません: {query}")


class XMLParseError(Exception):
    def __init__(self, message: str):
        super().__init__(f"XML解析エラー: {message}")


class LawTooLargeError(Exception):
    def __init__(self, char_count: int, max_chars: int):
        self.char_count = char_count
        self.max_chars = max_chars
        super().__init__(f"法令が大きすぎます: {char_count} > {max_chars}")
