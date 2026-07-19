from http.server import BaseHTTPRequestHandler
import cloudscraper
from bs4 import BeautifulSoup
import re
import ast
from concurrent.futures import ThreadPoolExecutor

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            m3u8_content = self.generate_playlist()
            self.send_response(200)
            self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
            # 20 dakika CDN cache, 10 dakika arka plan yenileme
            self.send_header('Cache-Control', 's-maxage=1200, stale-while-revalidate=600')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(m3u8_content.encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Error: {str(e)}".encode('utf-8'))

    def generate_playlist(self):
        # Bot korumasını ve AdBlock duvarını aşan özel tarayıcı simülatörü
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        scraper.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'bg,en-US;q=0.7,en;q=0.3',
            'Referer': 'https://www.seirsanduk.online/',
            'Origin': 'https://www.seirsanduk.online'
        })
        
        channel_links = {}
        results = []
        
        try:
            # Doğru hedef site: Seir Sanduk
            r = scraper.get("https://www.seirsanduk.online/", timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    # id=hd-diema-sport-hd gibi link parametrelerini yakala
                    if 'id=' in href:
                        title = a.get('title') or a.text.strip()
                        if href.startswith('?'): 
                            href = f"https://www.seirsanduk.online/{href}"
                        if title and title.lower() not in ['forum', 'връзка с нас', 'privacy policy']:
                            channel_links[href] = title.strip()
        except: 
            pass
                
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(self.extract_link, scraper, href, title) for href, title in channel_links.items()]
            for future in futures:
                res = future.result()
                if res and isinstance(res, tuple) and len(res) == 2: 
                    results.append(res)
                    
        playlist = "#EXTM3U\n"
        for title, url in results:
            playlist += f'#EXTINF:-1 tvg-id="" tvg-name="{title}" tvg-logo="" group-title="SeirSanduk",{title}\n'
            playlist += f'#EXTVLCOPT:http-referrer=https://www.seirsanduk.online/\n'
            playlist += f'{url}|Referer=https://www.seirsanduk.online/\n'
        return playlist

    def extract_link(self, scraper, url, title):
        try:
            r = scraper.get(url, timeout=12)
            iframes = re.findall(r'<iframe[^>]*src=[\"\']?([^\"\'\s>]+)[\"\']?[^>]*>', r.text, re.IGNORECASE)
            for embed_url in iframes:
                if embed_url.startswith('//'): 
                    embed_url = 'https:' + embed_url
                elif embed_url.startswith('/'): 
                    embed_url = 'https://www.seirsanduk.online' + embed_url
                
                # Gizli alt sunucu doğrulama başlıkları eklendi
                embed_r = scraper.get(embed_url, headers={'Referer': url, 'Origin': 'https://www.seirsanduk.online'}, timeout=10)
                embed_html = embed_r.text
                
                # Şifreli parçaları birleştiren JavaScript çözücü (İlk mesajındaki gizli span sistemi)
                src_match = re.search(r'src:\s*([a-zA-Z0-9_]+)\s*\(\),', embed_html)
                if src_match:
                    func_name = src_match.group(1)
                    func_match = re.search(rf'function\s+{func_name}\s*\(\)\s*\{{\s*return\s*\(?([^;}}]+)\)?\s*;?', embed_html)
                    if func_match:
                        expression = func_match.group(1)
                        base_url = ""
                        
                        arrays = re.findall(r'(\[.*?\])\.join\([\'"][\'"]\)', expression)
                        for arr in arrays: 
                            base_url += "".join(ast.literal_eval(arr))
                        
                        var_joins = re.findall(r'([a-zA-Z0-9_]+)\.join\([\'"][\'"]\)', expression)
                        for var in var_joins:
                            var_match = re.search(rf'var\s+{var}\s*=\s*(\[.*?\]);', embed_html)
                            if var_match: 
                                base_url += "".join(ast.literal_eval(var_match.group(1)))
                            
                        doc_joins = re.findall(r'document\.getElementById\([\'"]([a-zA-Z0-9_]+)[\'"]\)\.innerHTML', expression)
                        for span_id in doc_joins:
                            span_match = re.search(rf'<span[^>]*id=[\'\"]?{span_id}[\'\"]?[^>]*>(.*?)</span>', embed_html)
                            if span_match: 
                                base_url += span_match.group(1).strip()
                            
                        if "http" in base_url: 
                            return (title, base_url.replace('\\/', '/'))
                
                m = re.search(r'(https?://[^\s\"\'<>\\#]*\.m3u8[^\s\"\'<>\\#]*)', embed_html)
                if m: 
                    return (title, m.group(1).replace('\\/', '/'))
        except: 
            pass
        return None
