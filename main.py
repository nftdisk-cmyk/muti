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
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    
    scraper.headers.update({
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'bg,en-US;q=0.7,en;q=0.3',
        'Referer': 'https://seirsanduk.online',
        'Origin': 'https://seirsanduk.online',
        'Alt-Used': 'www.seirsanduk.online',
        'Sec-Fetch-Dest': 'iframe',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin'
    })
    
    print("1. Seir Sanduk platformundan spor ve ulusal kanallar toplanıyor...")
    for cat in categories:
        try:
            r = scraper.get(cat, timeout=15)
            if r.status_code != 200:
                continue
                
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a', href=True)
            
            for a in links:
                href = a['href']
                if 'id=' in href:
                    title = a.get('title') or a.text.strip()
                    
                    if href.startswith('?'):
                        href = f"https://seirsanduk.online{href}"
                    elif href.startswith('/'):
                        href = f"https://seirsanduk.online{href}"
                        
                    if not title or title.lower() in ['forum', 'връзка с нас', 'privacy policy']:
                        continue
                        
                    if href not in channel_links:
                        channel_links[href] = title.strip()
        except Exception as e:
            print(f"Kanal listesi çekilirken hata oluştu: {str(e)}")
            
    if not channel_links:
        print("Hata: Siteden hiçbir kanal bağlantısı ayıklanamadı!")
        return ""
        
    print(f"\n Toplam {len(channel_links)} kanal bulundu. Şifre çözücü döngüsü başlatılıyor...")
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(extract_m3u8_from_seir, scraper, href, title) for href, title in channel_links.items()]
        for future in futures:
            res = future.result()
            if res and isinstance(res, tuple) and len(res) == 2:
                results.append(res)
                print(f"   🔥 [BAŞARILI] {res} kanalı ve m3u8 şifresi kırıldı.")
                
    if not results:
        print("\n Hata: Kanallar bulundu fakat linkler sökülemedi!")
        return ""

    playlist = "#EXTM3U\n"
    for title, url in results:
        playlist += f'#EXTINF:-1 tvg-id="" tvg-name="{title}" tvg-logo="" group-title="SeirSanduk",{title}\n'
        playlist += f'{url}|Referer=https://seirsanduk.online&User-Agent=Mozilla/5.0\n'
        
    return playlist

def extract_m3u8_from_seir(scraper, url, title):
    try:
        r = scraper.get(url, timeout=15)
        html = r.text
        
        iframe_match = re.search(r'<iframe[^>]*src=[\"\']?([^\"\'\s>]+)[\"\']?[^>]*>', html, re.IGNORECASE)
        if not iframe_match:
            m = re.search(r'(https?://[^\s\"\'<>]*\.m3u8[^\s\"\'<>]*)', html)
            if m:
                return (title, m.group(1).replace('\\/', '/'))
            return None
            
        for embed_url in iframe_match.groups():
            if embed_url.startswith('//'):
                embed_url = 'https:' + embed_url
            elif embed_url.startswith('/'):
                embed_url = 'https://seirsanduk.online' + embed_url
                
            headers = {
                'Referer': url,
                'Origin': 'https://seirsanduk.online'
            }
            embed_r = scraper.get(embed_url, headers=headers, timeout=12)
            embed_html = embed_r.text
            
            # Güncellenen esnek regex: src ve parantez arasındaki boşluk varyasyonları çözüldü
            src_match = re.search(r'src\s*:\s*([a-zA-Z0-9_]+)\s*\(\s*\)\s*,', embed_html)
            if src_match:
                func_name = src_match.group(1)
                func_match = re.search(rf'function\s+{func_name}\s*\(\)\s*\{{\s*return\s*\(?([^;}}]+)\)?\s*;?', embed_html)
                if func_match:
                    expression = func_match.group(1)
                    base_url = ""
                    
                    # 1. Klasik Satır İçi Dizi Birleştirmeleri
                    arrays = re.findall(r'(\[.*?\])\.join\([\'"][\'"]\)', expression)
                    for arr in arrays:
                        try: base_url += "".join(ast.literal_eval(arr))
                        except: pass
                        
                    # 2. Değişken Tanımlı Dizi Birleştirmeleri
                    var_joins = re.findall(r'([a-zA-Z0-9_]+)\.join\([\'"][\'"]\)', expression)
                    for var in var_joins:
                        var_match = re.search(rf'var\s+{var}\s*=\s*(\[.*?\]);', embed_html)
                        if var_match:
                            try: base_url += "".join(ast.literal_eval(var_match.group(1)))
                            except: pass
                            
                    # 3. Gizli Span Elemanlarını Çözme (bieksisrcgtatufneh vb.)
                    doc_joins = re.findall(r'document\.getElementById\([\'"]([a-zA-Z0-9_]+)[\'"]\)\.innerHTML', expression)
                    if not doc_joins:
                        doc_joins = re.findall(r'document\.getElementById\(([a-zA-Z0-9_]+)\)\.innerHTML', expression)
                        
                    for span_id in doc_joins:
                        span_match = re.search(rf'<span[^>]*id=[\'\"]?{span_id}[\'\"]?[^>]*>(.*?)</span>', embed_html)
                        if span_match:
                            base_url += span_match.group(1).strip()
                            
                    if "http" in base_url:
                        return (title, base_url.replace('\\/', '/'))
                        
            m_sub = re.search(r'(https?://[^\s\"\'<>\\#]*\.m3u8[^\s\"\'<>\\#]*)', embed_html)
            if m_sub:
                return (title, m_sub.group(1).replace('\\/', '/'))
        return None
    except:
        return None

if __name__ == '__main__':
    print("M3U8 Otomatik Güncelleme Sistemi Başlatıldı...")
    m3u8_content = generate_playlist()
    if m3u8_content and len(m3u8_content) > 10:
        with open('playlist.m3u8', 'w', encoding='utf-8') as f:
            f.write(m3u8_content)
        print(f"\n [BAŞARILI] playlist.m3u8 dosyası güncellendi.")
    else:
        print("\n [HATA] Liste boş kaldı, dosya güncellenmedi.")
