import os
import re
from typing import List, Dict, Optional
from duckduckgo_search import DDGS

from config.province_rules import LATEST_HISTORICAL_YEAR


class SearchAgent:
    """基于 DuckDuckGo 的 Web Search Agent，用于补录缺失的高校录取数据。"""

    def __init__(self, proxy: Optional[str] = None, max_results: int = 5):
        self.proxy = proxy or self._default_proxy()
        self.max_results = max_results
        self.ddgs = None

    @staticmethod
    def _default_proxy() -> Optional[str]:
        return os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

    def _client(self):
        if self.ddgs is None:
            kwargs = {}
            if self.proxy:
                kwargs["proxy"] = self.proxy
            self.ddgs = DDGS(**kwargs)
        return self.ddgs

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict]:
        try:
            results = self._client().text(query, max_results=max_results or self.max_results)
            return list(results)
        except Exception as e:
            return [{"title": "搜索失败", "href": "", "body": str(e)}]

    def fill_major_score(
        self,
        school_name: str,
        major_name: str,
        province: str,
        subject_type: str,
        year: int = LATEST_HISTORICAL_YEAR,
    ) -> Dict:
        """检索某校某专业在指定省份/年份的录取最低分与位次。"""
        queries = [
            f"{school_name} {major_name} {province} {year} 录取最低分 位次",
            f"{school_name} {major_name} {province} {year} 录取分数线",
            f"{school_name} {major_name} {province} {year} 投档线",
        ]
        aggregated = []
        for q in queries:
            for r in self.search(q, max_results=5):
                body = f"{r.get('title', '')} {r.get('body', '')}"
                extracted = self._extract_numbers(body, year)
                if extracted.get("score") or extracted.get("rank"):
                    aggregated.append({
                        "query": q,
                        "url": r.get("href", ""),
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "extracted": extracted,
                    })

        best = self._merge_results(aggregated, year)
        return {
            "school_name": school_name,
            "major_name": major_name,
            "province": province,
            "subject_type": subject_type,
            "year": year,
            "results_count": len(aggregated),
            "best_guess": best,
            "sources": aggregated[:5],
        }

    @staticmethod
    def _extract_numbers(text: str, year: int) -> Dict:
        text = text.replace("，", ",").replace("；", ";")
        result = {"score": None, "rank": None, "year": year}

        # 最低分/录取分数线：XXX分
        score_patterns = [
            rf"{year}[^\\d]{{0,20}}最低分[是为：:]?\\s*(\\d{{3}})",
            rf"{year}[^\\d]{{0,20}}录取[^\\d]{{0,10}}最低分[是为：:]?\\s*(\\d{{3}})",
            rf"{year}[^\\d]{{0,20}}投档线[是为：:]?\\s*(\\d{{3}})",
            rf"{year}[^\\d]{{0,20}}分数线[是为：:]?\\s*(\\d{{3}})",
            r"最低分[是为：:]?\\s*(\\d{3})",
            r"投档线[是为：:]?\\s*(\\d{3})",
        ]
        for p in score_patterns:
            m = re.search(p, text)
            if m:
                result["score"] = int(m.group(1))
                break

        # 位次
        rank_patterns = [
            rf"{year}[^\\d]{{0,20}}最低位次[是为：:]?\\s*(\\d{{1,6}})",
            rf"{year}[^\\d]{{0,20}}位次[是为：:]?\\s*(\\d{{1,6}})",
            r"最低位次[是为：:]?\\s*(\\d{1,6})",
            r"位次[是为：:]?\\s*(\\d{1,6})",
        ]
        for p in rank_patterns:
            m = re.search(p, text)
            if m:
                result["rank"] = int(m.group(1))
                break
        return result

    @staticmethod
    def _merge_results(sources: List[Dict], year: int) -> Dict:
        if not sources:
            return {"score": None, "rank": None, "year": year, "confidence": "D", "note": "未检索到有效数据"}
        scores = [s["extracted"]["score"] for s in sources if s["extracted"].get("score")]
        ranks = [s["extracted"]["rank"] for s in sources if s["extracted"].get("rank")]
        return {
            "score": int(sum(scores) / len(scores)) if scores else None,
            "rank": int(sum(ranks) / len(ranks)) if ranks else None,
            "year": year,
            "confidence": "C",
            "note": f"基于 {len(scores)} 个分数样本 / {len(ranks)} 个位次样本估算，请人工复核",
        }
