import requests
from bs4 import BeautifulSoup

url = "https://www.seirsanduk.online/"
r = requests.get(url, headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})
soup = BeautifulSoup(r.text, 'html.parser')

print("Kanal olabilecek tüm linkler aranıyor...")
links = soup.find_all('a', href=True)
channels = []
for a in links:
    href = a['href']
    # seirsanduk'ta kanal linkleri "id=" parametresi taşıyor (main.py'deki mantıkla aynı)
    if 'id=' in href or '?id=' in href:
        title = a.get('title') or a.text.strip()
        img = a.find('img')
        if img and not title:
            title = img.get('alt', '')

        if href.startswith('?'):
            href = f"https://www.seirsanduk.online{href}"
        elif href.startswith('/'):
            href = f"https://www.seirsanduk.online{href}"

        if title and title.lower() not in ['forum', 'връзка с нас', 'privacy policy']:
            channels.append((title.strip(), href))

# İlk 5 tanesini yazdır
for c in channels[:5]:
    print(c)

print(f"\nToplam {len(channels)} kanal bulundu.")