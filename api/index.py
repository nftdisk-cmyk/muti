from http.server import BaseHTTPRequestHandler
import cloudscraper
import requests
from bs4 import BeautifulSoup
import re
import ast
import base64
from urllib.parse import urlparse, parse_qs, quote
import time

# Çalışmayan/decoy olduğu bilinen domainler - yeni biri çıkarsa buraya ekle
BLOCKED_DOMAINS = ["ro.glebul"]

# main.py'nin GitHub Actions ile saatlik güncelediği, doğrulanmış linkleri içeren dosya.
# Canlı çözümleme başarısız olursa (hep ro.glebul dönerse vs.) buradaki son bilinen
# çalışan link fallback olarak kullanılır.
GITHUB_FALLBACK_URL = "https://raw.githubusercontent.com/nftdisk-cmyk/muti/main/playlist.m3u8"

# title ve href'i tek bir query param içine gömmek için ayraç (title/href içinde geçmesi olası değil)
_SEP = "\x01"


def encode_channel(title: str, href: str) -> str:
    raw = f"{title}{_SEP}{href}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_channel(code: str):
    # base64 padding eksikse tamamla
    padded = code + "=" * (-len(code) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    title, _, href = raw.partition(_SEP)
    return title, href


def fetch_github_fallback(url=GITHUB_FALLBACK_URL):
    """GitHub'daki son bilinen playlist'i title -> url eşlemesi olarak döner."""
    fallback = {}
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return fallback
        current_title = None
        for line in r.text.splitlines():
            line = line.rstrip()
            if line.startswith("#EXTINF"):
                m = re.search(r',(.*)$', line)
                current_title = m.group(1).strip() if m else None
            elif line and not line.startswith("#") and current_title:
                # Headerlar (|Referer=...) varsa ayıkla, sade url'i al
                fallback[current_title] = line.split("|")[0].strip()
                current_title = None
    except Exception:
        pass
    return fallback


def is_blocked(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in BLOCKED_DOMAINS)


def verify_stream_url(scraper, url, referer="https://seirsanduk.online", timeout=6):
    """Bir linkin gerçekten oynatılabilir olup olmadığını hızlıca kontrol eder.
    Fallback linkler için kullanılıyor - kırık link göstermektense kanalı listeden çıkarmak daha iyi."""
    headers = {
        'Referer': referer,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        r = scraper.get(url, headers=headers, timeout=timeout, stream=True)
        if r.status_code != 200:
            return False
        chunk = next(r.iter_content(chunk_size=512), b"")
        text = chunk.decode("utf-8", errors="ignore")
        return text.strip().startswith("#EXTM3U")
    except Exception:
        return False


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if 'play' in query:
            self.handle_resolve(query['play'][0])
        else:
            self.handle_playlist()

    def handle_playlist(self):
        try:
            m3u8_content = self.generate_playlist()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(m3u8_content.encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Error: {str(e)}".encode('utf-8'))

    def handle_resolve(self, code):
        try:
            title, href = decode_channel(code)
        except Exception:
            self.send_response(400)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Gecersiz kanal kodu")
            return

        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        scraper.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'bg,en-US;q=0.7,en;q=0.3',
            'Referer': 'https://seirsanduk.online',
            'Origin': 'https://www.seirsanduk.online'
        })

        result = self.extract_link(scraper, href, title)

        if not result:
            fallback = fetch_github_fallback()
            candidate_url = fallback.get(title)
            if candidate_url and verify_stream_url(scraper, candidate_url):
                result = (title, candidate_url)

        if result:
            _, found_url = result
            self.send_response(302)
            self.send_header('Location', found_url)
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(f"'{title}' su an cozumlenemedi.".encode('utf-8'))

    def generate_playlist(self):
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        scraper.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'bg,en-US;q=0.7,en;q=0.3',
            'Referer': 'https://seirsanduk.online',
            'Origin': 'https://www.seirsanduk.online'
        })

        channel_links = {}

        try:
            r = scraper.get("https://seirsanduk.online", timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if 'id=' in href or '?id=' in href:
                        title = a.get('title') or a.text.strip()
                        if href.startswith('?'):
                            href = f"https://seirsanduk.online{href}"
                        elif href.startswith('/'):
                            href = f"https://www.seirsanduk.online{href}"
                        if title and title.lower() not in ['forum', 'връзка с нас', 'privacy policy']:
                            channel_links[href] = title.strip()
        except Exception:
            pass

        host = self.headers.get('Host', 'muti-bice.vercel.app')
        base_url = f"https://{host}/api"

        playlist = "#EXTM3U\n"
        for href, title in channel_links.items():
            code = quote(encode_channel(title, href))
            resolver_url = f"{base_url}?play={code}"
            playlist += f'#EXTINF:-1 tvg-id="" tvg-name="{title}" tvg-logo="" group-title="SeirSanduk",{title}\n'
            playlist += f'{resolver_url}\n'
        return playlist

    def extract_link(self, scraper, url, title, max_retries=2):
        for attempt in range(max_retries):
            result = self._try_extract_link(scraper, url, title)
            if result:
                return result
            if attempt < max_retries - 1:
                time.sleep(1)  # blocked domain geldiyse kısa bekleyip tekrar dene
        return None

    def _try_extract_link(self, scraper, url, title):
        try:
            r = scraper.get(url, timeout=15)
            html = r.text
            iframe_match = re.search(r'<iframe[^>]*src=[\"\']?([^\"\'\s>]+)[\"\']?[^>]*>', html, re.IGNORECASE)
            if not iframe_match:
                m = re.search(r'(https?://[^\s\"\'<>]*\.m3u8[^\s\"\'<>]*)', html)
                if m:
                    found_url = m.group(1).replace('\\/', '/')
                    if is_blocked(found_url):
                        return None
                    return (title, found_url)
                return None

            for embed_url in iframe_match.groups():
                if embed_url.startswith('//'):
                    embed_url = 'https:' + embed_url
                elif embed_url.startswith('/'):
                    embed_url = 'https://www.seirsanduk.online' + embed_url

                embed_headers = {
                    'Referer': url,
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                embed_r = scraper.get(embed_url, headers=embed_headers, timeout=12)
                embed_html = embed_r.text

                src_match = re.search(r'src\s*:\s*([a-zA-Z0-9_]+)\s*\(\s*\)\s*,', embed_html)
                if src_match:
                    func_name = src_match.group(1)
                    func_match = re.search(
                        rf'function\s+{func_name}\s*\(\)\s*\{{\s*return\s*\(?([^;}}]+)\)?\s*;?', embed_html
                    )
                    if func_match:
                        expression = func_match.group(1)
                        base_url = ""

                        arrays = re.findall(r'(\[.*?\])\.join\([\'"][\'"]\)', expression)
                        for arr in arrays:
                            try:
                                base_url += "".join(ast.literal_eval(arr))
                            except Exception:
                                pass

                        var_joins = re.findall(r'([a-zA-Z0-9_]+)\.join\([\'"][\'"]\)', expression)
                        for var in var_joins:
                            var_match = re.search(rf'var\s+{var}\s*=\s*(\[.*?\]);', embed_html)
                            if var_match:
                                try:
                                    base_url += "".join(ast.literal_eval(var_match.group(1)))
                                except Exception:
                                    pass

                        doc_joins = re.findall(
                            r'document\.getElementById\([\'"]([a-zA-Z0-9_]+)[\'"]\)\.innerHTML', expression
                        )
                        if not doc_joins:
                            doc_joins = re.findall(
                                r'document\.getElementById\(([a-zA-Z0-9_]+)\)\.innerHTML', expression
                            )

                        for span_id in doc_joins:
                            span_match = re.search(
                                rf'<span[^>]*id=[\'\"]?{span_id}[\'\"]?[^>]*>(.*?)</span>', embed_html
                            )
                            if span_match:
                                base_url += span_match.group(1).strip()

                        if "http" in base_url:
                            found_url = base_url.replace('\\/', '/')
                            if is_blocked(found_url):
                                return None
                            return (title, found_url)

                m = re.search(r'(https?://[^\s\"\'<>\\#]*\.m3u8[^\s\"\'<>\\#]*)', embed_html)
                if m:
                    found_url = m.group(1).replace('\\/', '/')
                    if is_blocked(found_url):
                        return None
                    return (title, found_url)
        except Exception:
            pass
        return None