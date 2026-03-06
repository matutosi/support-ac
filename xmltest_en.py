import requests
import xml.etree.ElementTree as ET


xml = requests.get("http://api.jstage.jst.go.jp/searchapi/do?service=3&issn=2189-4809")
xml.encoding = "utf-8"
root = ET.fromstring(xml.text)

end = int(root[8].text) + 9
items = range(9,end,1)

for i in items:
    title_en = root[i][0][0].text
    if(title_en!=None):
        title_en = title_en.replace('  ','').replace('\n','')
        author_en = [name.text.replace('  ','').replace('\n','') 
                for name in root[i][2][0].iter()]
        author_en = ", ".join(author_en[1:])
        journal_en ="Vegetation Science"
        link_en = root[i][1][0].text
        vol = "Volume" + root[i][7].text
        iss = "Issue " + root[i][8].text
        pg = "Pages" + root[i][9].text + "-" + root[i][10].text
        yr = root[i][11].text
        doi = root[i][12].text
        join_en = ", ".join([author_en, title_en+" "+journal_en, yr, vol, iss, pg])
        print(i)
        print("<li style=\"margin-left: 40px; padding-bottom: 15px;\">")
        print(" <a href=\"" + link_en + "\">")
        print("     " + join_en)
        print(" </a>")
        print("</li>")

