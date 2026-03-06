import requests
from bs4 import BeautifulSoup

url = "https://www.jstage.jst.go.jp/browse/vegsci/41/2/_contents/-char/ja"
response = requests.get(url)
html = response.text
soup = BeautifulSoup(html, "html.parser")

type_info = ".section-level1"
article_info = "#search-resultslist-wrap li"
articles = soup.select(f'{type_info},{article_info}')

# articles
for art in articles:
    type = art.get_text()
    if len(type) > 20:
        type = ""
    title = art.select_one(".searchlist-title")
    if title:
        title = title.get_text(strip=True).replace("\n", "").replace("\r", "").replace("\t", "").replace(" +", " ")
    author = art.select_one(".searchlist-authortags")
    if author:
        author = author.get_text(strip=True).replace("\n", "").replace("\r", "").replace("\t", "").replace(" +", " ")
    add_info = art.select_one(".searchlist-additional-info")
    if add_info:
        add_info = add_info.get_text(strip=True).replace("\n", "").replace("\r", "").replace("\t", "").replace(" +", " ")
    print(type)
    print(title)
    print(author)
    print(add_info)

