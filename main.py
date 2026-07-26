import cloudscraper
from bs4 import BeautifulSoup
import re
import ast
import time
import os
from concurrent.futures import ThreadPoolExecutor

def load_previous_playlist(path="playlist.m3u8"):
    """Bir önceki çalıştırmadan başarılı olmuş (title -> url_satırı) eşleşmelerini okur.
    Bu run'da bir kanal bulunamazsa eski hali korunacak, tamamen silinmeyecek."""
    previous = {}
    if not os.path.exists(path):
        return previous

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    current_title = None
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith("#EXTINF"):
            m = re.search(r',(.*)$', line)
            current_title = m.group(1).strip() if m else None
        elif line and not line.startswith("#") and current_title:
            previous[current_title] = line
            current_title = None

    return previous

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
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'bg,en-US;q=0.7,en;q=0.3',
        'Referer': 'https://seirsanduk.online',
        'Origin': 'https://seirsanduk.online'
    })
    
    print("1. Seir Sanduk listesinden tüm kanallar toplanıyor...")
    for cat in categories:
        try:
            r = scraper.get(cat, timeout=15)
            if r.status_code != 200:
                continue
                
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a', href=True)
            
            for a in links:
                href = a['href']
                if 'id=' in href or '?id=' in href:
                    title = a.get('title') or a.text.strip()
                    
                    if href.startswith('?'):
                        href = f"https://seirsanduk.online{href}"
                    elif href.startswith('/'):
                        href = f"https://seirsanduk.online{href}"
                        
                    if not title or title.lower() in ['forum', 'връзка с нас', 'privacy policy']:
                        continue
                        
                    if href not in channel_links:
                        channel_links[href] = title.strip()
        except Exception:
            pass
            
    print(f"\n Toplam {len(channel_links)} kanal bulundu. Premium çözücü başlatılıyor...")
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for href, title in channel_links.items():
            futures.append(executor.submit(extract_m3u8_from_seir, scraper, href, title))
            time.sleep(0.6) # Sunucuyu şüphelendirmemek için insansı nefes payı
            
        for future in futures:
            res = future.result()
            if res and isinstance(res, tuple) and len(res) == 2:
                results.append(res)
                print(f"   🔥 [BAŞARILI] {res} kanalı listeye güvenle işlendi.")

    # --- Bu run'da bulunamayan kanalları önceki playlist'ten koru ---
    previous = load_previous_playlist()
    found_titles = {title for title, _ in results}
    kept_from_previous = 0

    for title, old_line in previous.items():
        if title not in found_titles:
            # Eski satırdan url'i ayıkla (| ile eklenmiş header'lardan önceki kısım)
            old_url = old_line.split("|")[0].strip()
            results.append((title, old_url))
            kept_from_previous += 1
            print(f"   ♻️  [KORUNDU] {title} bu run'da bulunamadı, önceki linki kullanıldı.")

    if kept_from_previous:
        print(f"\n {kept_from_previous} kanal bu run'da güncellenemedi, eski linkleriyle listede tutuldu.")

    if not results:
        print("\n Hata: Filtreye uygun çalışan hiçbir link bulunamadı!")
        return ""

    playlist = "#EXTM3U\n"
    for title, url in results:
        playlist += f'#EXTINF:-1 tvg-id="" tvg-name="{title}" tvg-logo="" group-title="SeirSanduk",{title}\n'
        
        if "ro.glebul" in url.lower():
            playlist += f'{url}|Referer=https://seirsanduk.online|User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36|Accept-Language=bg,en-US;q=0.7,en;q=0.3\n'
        else:
            playlist += f'{url}|Referer=https://seirsanduk.online|User-Agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\n'
        
    return playlist

def verify_stream_url(scraper, url, referer="https://seirsanduk.online"):
    """Bulunan m3u8 linkinin gerçekten oynatılabilir olup olmadığını kontrol eder.
    ro.glebul gibi decoy/redirect domainlerin sessizce playliste sızmasını engeller."""
    headers = {
        'Referer': referer,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        r = scraper.get(url, headers=headers, timeout=8, stream=True)
        if r.status_code != 200:
            return False
        # HLS manifest'i her zaman #EXTM3U ile başlar; ilk birkaç yüz byte yeterli
        chunk = next(r.iter_content(chunk_size=512), b"")
        text = chunk.decode("utf-8", errors="ignore")
        return text.strip().startswith("#EXTM3U")
    except Exception:
        return False

def extract_m3u8_from_seir(scraper, url, title, max_retries=3):
    for attempt in range(max_retries):
        result = _try_extract(scraper, url, title)
        if result:
            found_title, found_url = result
            if verify_stream_url(scraper, found_url):
                return result
            else:
                print(f"   ⚠️  [DECOY/ÖLÜ LİNK] {title} -> {found_url[:60]}... çalışmıyor, yeniden deneniyor.")
        if attempt < max_retries - 1:
            time.sleep(1.5)  # rate-limit/timeout ihtimaline karşı kısa bekleme, sonra tekrar dene
    return None

def _try_extract(scraper, url, title):
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
                
            embed_headers = {
                'Referer': url,
                'Origin': 'https://seirsanduk.online',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            embed_r = scraper.get(embed_url, headers=embed_headers, timeout=12)
            embed_html = embed_r.text
            
            src_match = re.search(r'src\s*:\s*([a-zA-Z0-9_]+)\s*\(\s*\)\s*,', embed_html)
            if src_match:
                func_name = src_match.group(1)
                func_match = re.search(rf'function\s+{func_name}\s*\(\)\s*\{{\s*return\s*\(?([^;}}]+)\)?\s*;?', embed_html)
                if func_match:
                    expression = func_match.group(1)
                    base_url = ""
                    
                    arrays = re.findall(r'(\[.*?\])\.join\([\'"][\'"]\)', expression)
                    for arr in arrays:
                        try: base_url += "".join(ast.literal_eval(arr))
                        except: pass
                        
                    var_joins = re.findall(r'([a-zA-Z0-9_]+)\.join\([\'"][\'"]\)', expression)
                    for var in var_joins:
                        var_match = re.search(rf'var\s+{var}\s*=\s*(\[.*?\]);', embed_html)
                        if var_match:
                            try: base_url += "".join(ast.literal_eval(var_match.group(1)))
                            except: pass
                            
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