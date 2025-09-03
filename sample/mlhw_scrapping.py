import requests
from bs4 import BeautifulSoup
import openai  # OpenAI APIを使用

# ----------------------------
# OpenAI APIキー設定
# ----------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ----------------------------
# カテゴリ判定用キーワード
# ----------------------------
CATEGORY_KEYWORDS = {
    "議題（結果）": ["まとめ", "要旨", "とりまとめ", "決定", "答申", "概要"],
    "議事録（過程）": ["議事録", "会議録", "発言要旨", "討議の経過", "逐語"],
    "参考資料": ["統計", "報告書", "告示", "通知", "公表", "資料", "ガイドライン", "緊急命令"]
}

# ----------------------------
# ルールベース判定関数
# ----------------------------
def categorize_rule(title):
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in title:
                return category
    return "参考資料"  # キーワードに当てはまらない場合は参考資料

# ----------------------------
# LLM判定関数
# ----------------------------
def categorize_llm(title, summary=""):
    prompt = f"""
次の情報を見て、カテゴリを「議題（結果）」「議事録（過程）」「参考資料」のいずれかに分類してください。
タイトル: {title}
本文（省略可）: {summary}
出力形式: カテゴリ名のみ
"""
    response = openai.ChatCompletion.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    category = response['choices'][0]['message']['content'].strip()
    return category

# ----------------------------
# RSS解析
# ----------------------------
rss_url = "https://www.mhlw.go.jp/stf/news.rdf"
response = requests.get(rss_url)
soup = BeautifulSoup(response.content, "xml")  # XML解析

items = soup.find_all("item")
for item in items:
    title_tag = item.find("title")
    link_tag = item.find("link")
    date_tag = item.find("dc:date")
    
    title = title_tag.text.strip() if title_tag else "No title"
    link = link_tag.text.strip() if link_tag else "No link"
    date = date_tag.text.strip() if date_tag else "No date"
    
    # まずルールベースで判定
    category = categorize_rule(title)
    
    # 曖昧な場合はLLMで補正
    if category == "参考資料" and len(title) > 20:  # 簡易条件：長いタイトルなど
        category = categorize_llm(title)
    
    print(f"タイトル: {title}")
    print(f"リンク: {link}")
    print(f"公開日: {date}")
    print(f"カテゴリ: {category}")
    print("-" * 50)
