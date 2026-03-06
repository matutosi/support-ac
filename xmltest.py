import requests
import xml.etree.ElementTree as ET


xml = requests.get("http://api.jstage.jst.go.jp/searchapi/do?service=3&issn=2189-4809")
xml.encoding = "utf-8"
root = ET.fromstring(xml.text)

end = int(root[8].text) + 9
items = range(9, end, 1)

#root[9].find('{http://www.w3.org/2005/Atom}article_title')[0].text

for i in items:
    title_ja = root[i][0][1].text
    if(title_ja!=None):
        title_ja = title_ja.replace('  ','').replace('\n','')
        if(root[i][2][1].text!=None):
            author_ja = [name.text.replace('  ','').replace('\n','') 
                    for name in root[i][2][1].iter()]
            author_ja = ", ".join(author_ja[1:])
        else:
            author_ja = None
        journal_ja ="植生学会誌"
        link_ja = root[i][1][1].text
        vol = root[i][7].text + "巻"
        iss = root[i][8].text + "号"
        pg = "p." + root[i][9].text + "-" + root[i][10].text
        yr = root[i][11].text
        doi = root[i][12].text
        if(author_ja!=None):
            join_ja = ", ".join([author_ja, title_ja+". "+journal_ja, yr, vol, iss, pg])
        else:
            join_ja = ", ".join([title_ja+". "+journal_ja, yr, vol, iss, pg])
        print(i-9)
        print("<li style=\"margin-left: 40px; padding-bottom: 15px;\">")
        print(" <a href=\"" + link_ja + "\">")
        print("     " + join_ja)
        print(" </a>")
        print("</li>")

