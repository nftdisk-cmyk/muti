import cloudscraper
from bs4 import BeautifulSoup
import re
import ast
from concurrent.futures import ThreadPoolExecutor

def generate_playlist():
    categories = [
        "https://seirsanduk.online"
    ]
    
    channel_links = {}
    results = []
    
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
    
    scraper.headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'bg,en-US;q=0.7,en;q=0.3',
        'Referer': 'https://seirsanduk.online',
        'Origin': 'https://seirsanduk.online'
    })
    
    print("1. Seir Sanduk listesinden tüm kanallar toplanıyor...")
    for cat in categories:
        try:
            r = scraper.get(cat, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'id=' in href:
                    title = a.get('title') or a.text.strip()
                    if href.startswith('?'): href = f"https://seirsanduk.online{href}"
                    if not title or title.lower() in ['forum', 'връзка с нас', 'privacy policy']: continue
                    if href not in channel_links:
                        channel_links[href] = title.strip()
        except: pass
        
    print(f"\n Toplam {len(channel_links)} kanal için agresif spor çözücü başlatılıyor...")
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(extract_m3u8_from_seir, scraper, href, title) for href, title in channel_links.items()]
        for future in futures:
            res = future.result()
            if res and isinstance(res, tuple) and len(res) == 2:
                results.append(res)
                print(f"   🔥 [BAŞARILI] {res[0]} kanalı çözüldü.")
                
    playlist = "#EXTM3U\n"
    for title, url in results:
        playlist += f'#EXTINF:-1 tvg-id="" tvg-name="{title}" tvg-logo="" group-title="SeirSanduk",{title}\n'
        playlist += f'#EXTVLCOPT:http-referrer=https://seirsanduk.online\n'
        playlist += f'{url}|Referer=https://seirsanduk.online\n'
    return playlist

def extract_m3u8_from_seir(scraper, url, title):
    try:
        r = scraper.get(url, timeout=12)
        html = r.text
        
        # Spor sayfalarındaki TÜM iframe bağlantılarını (Player 1, 2, 3) listeye alıyoruz
        iframes = re.findall(r'<iframe[^>]*src=[\"\']?([^\"\'\s>]+)[\"\']?[^>]*>', html, re.IGNORECASE)
        
        # Eğer sayfada doğrudan m3u8 gizlendiyse ilk aşamada kurtar
        m_direct = re.search(r'(https?://[^\s\"\'<>]*\.m3u8[^\s\"\'<>]*)', html)
        if m_direct:
            return (title, m_direct.group(1).replace('\\/', '/'))
            
        # Bulunan tüm alternatif player iframelerini sırayla tara (Hatalı olanı atla, çalışan m3u8'i bul)
        for embed_url in iframes:
            try:
                if embed_url.startswith('//'): embed_url = 'https:' + embed_url
                elif embed_url.startswith('/'): embed_url = 'https://seirsanduk.online' + embed_url
                
                embed_r = scraper.get(embed_url, headers={'Referer': url, 'Origin': 'https://seirsanduk.online'}, timeout=8)
                embed_html = embed_r.text
                
                # 1. Aşama: Oynatıcı kodlarının içinde .m3u8 akışı var mı bak
                m_sub = re.search(r'(https?://[^\s\"\'<>\\#]*\.m3u8[^\s\"\'<>\\#]*)', embed_html)
                if m_sub:
                    return (title, m_sub.group(1).replace('\\/', '/'))
                
                # 2. Aşama: Gizli span ve şifreli dizileri birleştirme (Klasik JagoBD/SeirSanduk şifresi)
                src_match = re.search(r'src:\s*([a-zA-Z0-9_]+)\s*\(\),', embed_html)
                if src_match:
                    func_name = src_match.group(1)
                    func_match = re.search(rf'function\s+{func_name}\s*\(\)\s*\{{\s*return\s*\(?([^;}}]+)\)?\s*;?', embed_html)
                    if func_match:
                        expression = func_match.group(1)
                        base_url = ""
                        
                        arrays = re.findall(r'(\[.*?\])\.join\([\'"][\'"]\)', expression)
                        for arr in arrays: base_url += "".join(ast.literal_eval(arr))
                        
                        var_joins = re.findall(r'([a-zA-Z0-9_]+)\.join\([\'"][\'"]\)', expression)
                        for var in var_joins:
                            var_match = re.search(rf'var\s+{var}\s*=\s*(\[.*?\]);', embed_html)
                            if var_match: base_url += "".join(ast.literal_eval(var_match.group(1)))
                            
                        doc_joins = re.findall(r'document\.getElementById\([\'"]([a-zA-Z0-9_]+)[\'"]\)\.innerHTML', expression)
                        for span_id in doc_joins:
                            span_match = re.search(rf'<span[^>]*id=[\'\"]?{span_id}[\'\"]?[^>]*>(.*?)</span>', embed_html)
                            if span_match: base_url += span_match.group(1).strip()
                            
                        if "http" in base_url:
                            return (title, base_url.replace('\\/', '/'))
            except:
                continue # Bu player butonu bozuksa veya boşsa bir sonrakine geç
        return None
    except:
        return None

if __name__ == '__main__':
    m3u8_content = generate_playlist()
    if m3u8_content:
        with open('playlist.m3u8', 'w', encoding='utf-8') as f:
            f.write(m3u8_content)
        print("\n [BAŞARILI] playlist.m3u8 dosyası güncellendi.")
