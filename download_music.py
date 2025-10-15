import requests
import re
import json
import urllib.parse
import time
import sys
import os
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup

# --- 全局配置 ---
# 注意：这些 Cookies 和 Headers 可能有有效期，如果代码运行失败，
# 务必从浏览器中获取最新的 Cookies 和 Headers 并更新这里的字典。
# 警告：请在 GitHub Secrets 中存储敏感信息，这里仅为示例。
# 从环境变量加载 Cookies 和 Headers
# 如果环境变量不存在，则使用空字典作为默认值，防止json.loads报错
cookies_str = os.getenv('MUSIC_DOWNLOAD_COOKIES', '{}')
get_html_headers_str = os.getenv('MUSIC_DOWNLOAD_GET_HTML_HEADERS', '{}')
post_api_headers_str = os.getenv('MUSIC_DOWNLOAD_POST_API_HEADERS', '{}')

try:
    cookies = json.loads(cookies_str)
    get_html_headers = json.loads(get_html_headers_str)
    post_api_headers = json.loads(post_api_headers_str)
except json.JSONDecodeError as e:
    print(f"错误: 无法解析环境变量中的 JSON 数据: {e}")
    sys.exit(1)


# --- 常量和配置 ---
INITIAL_REQUEST_DELAY = 1.0
MAX_RETRIES = 3
RETRY_DELAY_MULTIPLIER = 2
DOWNLOAD_DIR = Path("downloads") # 这将把文件下载到仓库根目录下的 downloads 文件夹
FFMPEG_AVAILABLE = False
RETRY_TIME_PATTERN = re.compile(r'请 (\d+) 秒后再试。')
BR_TAG_PATTERN = re.compile(r'<br\s*/?>', re.IGNORECASE)


def print_status(message, end='\n'):
    """统一的打印函数，方便管理输出"""
    print(message, end=end)
    sys.stdout.flush()

# --- 请在这里粘贴你完整脚本中其余的函数定义 ---
# 例如：
def sanitize_filename(filename):
    """清理文件名，移除无效字符."""
    # 实现略...
    return "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-')).strip()

def check_ffmpeg_available():
    """检查 FFmpeg 是否可用."""
    global FFMPEG_AVAILABLE
    try:
        subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True)
        FFMPEG_AVAILABLE = True
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        FFMPEG_AVAILABLE = False
        return False

def convert_aac_to_mp3(file_path):
    """将 AAC 文件转换为 MP3."""
    if not FFMPEG_AVAILABLE:
        print_status(f"FFmpeg 未安装或不可用，无法转换文件: {file_path}")
        return file_path

    # 实现略... (这个函数会返回新的MP3路径或原路径)
    mp3_path = file_path.with_suffix('.mp3')
    print_status(f"尝试将 {file_path} 转换为 {mp3_path}...")
    try:
        subprocess.run(['ffmpeg', '-i', str(file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(mp3_path)], check=True, capture_output=True)
        print_status(f"转换成功: {mp3_path}")
        os.remove(file_path) # 删除原始AAC文件
        return mp3_path
    except subprocess.CalledProcessError as e:
        print_status(f"FFmpeg 转换失败: {e.stderr.decode()}")
        return file_path
    except Exception as e:
        print_status(f"转换过程中发生错误: {e}")
        return file_path


def download_file(url, target_path_str, retries=MAX_RETRIES):
    """下载文件，包含重试和错误处理"""
    target_path = Path(target_path_str)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        print_status(f"文件已存在，跳过下载: {target_path.name}")
        return True

    print_status(f"开始下载 {target_path.name}...")
    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, headers=get_html_headers, cookies=cookies, timeout=10) as r:
                r.raise_for_status() # 检查 HTTP 状态码
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                with open(target_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            # print(f"\rDownloading: {downloaded_size / (1024*1024):.2f}MB / {total_size / (1024*1024):.2f}MB", end='')
                # print_status(f"\r下载完成: {target_path.name} (大小: {downloaded_size / (1024*1024):.2f}MB)", end='\n')
                print_status(f"下载成功: {target_path.name}")
                return True
        except requests.exceptions.HTTPError as e:
            print_status(f"HTTP 错误 {e.response.status_code} 下载 {url}: {e}")
            if e.response.status_code == 403:
                print_status("可能需要更新 Cookies 或 Headers。")
                return False
        except requests.exceptions.RequestException as e:
            print_status(f"下载请求错误 {url}: {e}")
        except IOError as e:
            print_status(f"文件写入错误 {target_path}: {e}")

        if attempt < retries:
            delay = INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt)
            print_status(f"下载失败，在 {delay:.1f} 秒后重试 (尝试 {attempt + 1}/{retries})...")
            time.sleep(delay)
        else:
            print_status(f"下载 {target_path} 失败，已达最大重试次数。")
    return False

def download_lyric_file(content, filename_prefix, extension):
    """下载歌词文件."""
    if not content:
        return False
    
    file_path = DOWNLOAD_DIR / f"{filename_prefix}.{extension}"
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print_status(f"歌词文件下载成功: {file_path}")
        return True
    except IOError as e:
        print_status(f"歌词文件写入失败: {e}")
        return False

def download_music_file(music_url, title, artist, lrc_content, txt_content):
    """下载音乐文件，并处理歌词、MP3转换."""
    if not music_url:
        print_status("没有找到音乐下载链接，跳过音乐下载。")
        return False

    filename_prefix = sanitize_filename(f"{title} - {artist}")
    file_extension = "mp3"  # 默认假定mp3，如果URL是aac，后面会处理
    if '.aac' in music_url: # 简单的检查
        file_extension = "aac"

    music_file_path = DOWNLOAD_DIR / f"{filename_prefix}.{file_extension}"
    
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True) # 确保目录存在

    download_success = download_file(music_url, music_file_path)

    if download_success and music_file_path.exists() and file_extension == "aac":
        # 如果是aac文件且FFmpeg可用，尝试转换
        converted_path = convert_aac_to_mp3(music_file_path)
        if converted_path != music_file_path: # 如果转换成功，文件名会改变
            music_file_path = converted_path # 更新路径
            file_extension = "mp3"


    # 下载歌词（LRC和TXT）
    download_lyric_file(lrc_content, filename_prefix, 'lrc')
    download_lyric_file(txt_content, filename_prefix, 'txt')

    return download_success


# 请将 get_song_details_from_html, get_music_url, search_songs 这三个函数也粘贴到这里
# 确保它们能正常运行，尤其是需要全局的 cookies 和 headers。

def get_song_details_from_html(song_id, max_retries=MAX_RETRIES):
    """根据歌曲ID获取歌曲的详细页HTML内容，并从中解析播放链接。"""
    detail_url = f"https://www.gequhai.com/play/{song_id}.html"
    print_status(f"正在获取歌曲详情页: {detail_url}")

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(detail_url, headers=get_html_headers, cookies=cookies, timeout=10)
            response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
            return response.text
        except requests.exceptions.RequestException as e:
            print_status(f"获取歌曲详情页失败 (尝试 {attempt+1}/{max_retries+1}): {e}")
            if attempt < max_retries:
                time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    print_status(f"无法获取歌曲详情页: {detail_url}，已达最大重试次数。")
    return None

def get_music_url(song_id):
    """获取指定歌曲ID的播放链接和歌词。"""
    html_content = get_song_details_from_html(song_id)
    if not html_content:
        return None, None, None

    soup = BeautifulSoup(html_content, 'html.parser')

    # 解析歌词 (LRC)
    lrc_container = soup.find('div', class_='lrc-box')
    lrc_content = lrc_container.get_text(separator='\n').strip() if lrc_container else ""

    # 解析歌词 (TXT，去除时间戳)
    txt_content = ""
    if lrc_content:
        # 移除行首的 [mm:ss.xx] 或 [mm:ss]
        txt_content = re.sub(r'\[\d{2}:\d{2}(?:\.\d{2})?\]', '', lrc_content)
        txt_content = BR_TAG_PATTERN.sub('\n', txt_content).strip() # 处理 <br> 标签

    # 尝试查找音乐播放链接
    # 查找 <audio> 标签的 src 属性
    audio_tag = soup.find('audio', id=f'xplayer-{song_id}')
    music_url = None
    if audio_tag and audio_tag.get('src'):
        music_url = audio_tag['src'].strip()
        print_status(f"直接从 audio 标签找到链接: {music_url}")
        # 如果找到链接，通常不需要进一步的API请求
        return {'url': music_url, 'type': 'audio'}, lrc_content, txt_content


    # 如果 audio 标签没有 src 或不存在，尝试从 JSON-LD 结构中查找（不太常见）
    script_ld_json = soup.find('script', {'type': 'application/ld+json'})
    if script_ld_json:
        try:
            ld_json_data = json.loads(script_ld_json.string)
            if isinstance(ld_json_data, list): # 有些网站会返回数组
                ld_json_data = ld_json_data[0] # 取第一个
            
            # 尝试根据 schema markup 常见的属性查找
            if 'audio' in ld_json_data and 'contentUrl' in ld_json_data['audio']:
                music_url = ld_json_data['audio']['contentUrl']
                print_status(f"从 LD+JSON audio 找到链接: {music_url}")
                return {'url': music_url, 'type': 'audio'}, lrc_content, txt_content
            elif 'encoding' in ld_json_data and isinstance(ld_json_data['encoding'], list):
                for encoding_item in ld_json_data['encoding']:
                    if encoding_item.get('@type') == 'AudioObject' and encoding_item.get('contentUrl'):
                        music_url = encoding_item['contentUrl']
                        print_status(f"从 LD+JSON encoding 找到链接: {music_url}")
                        return {'url': music_url, 'type': 'audio'}, lrc_content, txt_content

        except json.JSONDecodeError as e:
            print_status(f"解析 JSON-LD 失败: {e}")
        except Exception as e:
            print_status(f"处理 LD+JSON 时发生错误: {e}")


    # 这是你原始脚本中通过POST API获取链接的方式
    # 如果以上两种方式都未能直接找到下载链接，再尝试POST API
    api_url = "https://www.gequhai.com/api/getmusic.php"
    post_data = {
        'id': song_id,
        'type': 'json',
        'key': 'SecretKey' # 这里的 'SecretKey' 可能是动态的，如果无效需要更新
    }
    
    print_status(f"尝试通过 POST API 获取音乐链接 (ID: {song_id})...")
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(api_url, data=post_data, headers=post_api_headers, cookies=cookies, timeout=10)
            response.raise_for_status()
            music_data = response.json()

            if music_data and music_data.get('code') == 1 and music_data.get('data') and music_data['data'].get('url'):
                print_status(f"通过 API 成功获取音乐链接: {music_data['data']['url'][:60]}...")
                return music_data['data'], lrc_content, txt_content
            else:
                error_msg = music_data.get('msg', '未知错误')
                print_status(f"API 返回错误: {error_msg}")
                # 检查是否是请求过快提示
                match = RETRY_TIME_PATTERN.search(error_msg)
                if match:
                    wait_time = int(match.group(1))
                    print_status(f"API 请求过快，将在 {wait_time} 秒后重试。")
                    time.sleep(wait_time + 1) # 多等一秒
                    continue # 立即重试，不计入常规重试延迟
                print_status(f"API未返回有效音乐数据: {music_data}")

        except requests.exceptions.RequestException as e:
            print_status(f"POST API 请求失败 (尝试 {attempt+1}/{MAX_RETRIES+1}): {e}")
        except json.JSONDecodeError:
            print_status("API 返回的不是有效的 JSON 格式。")
        except Exception as e:
            print_status(f"处理 API 响应时发生错误: {e}")

        if attempt < MAX_RETRIES:
            delay = INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt)
            print_status(f"在 {delay:.1f} 秒后重试...")
            time.sleep(delay)
    
    print_status(f"无法获取歌曲 {song_id} 的播放链接，已达最大重试次数。")
    return None, lrc_content, txt_content

def search_songs(query, max_retries=MAX_RETRIES):
    """搜索歌曲并返回结果列表。"""
    encoded_query = urllib.parse.quote(query)
    search_url = f"https://www.gequhai.com/s/{encoded_query}"
    print_status(f"正在搜索: {search_url}")

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(search_url, headers=get_html_headers, cookies=cookies, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            # 查找所有 class 为 ".song-item" 的 li 元素
            song_items = soup.find_all('li', class_='song-item')

            if not song_items:
                print_status("没有找到歌曲结果。")
                return []

            found_songs = []
            for item in song_items:
                link_tag = item.find('a', class_='song-title')
                artist_tag = item.find('span', class_='song-artist')

                if link_tag and artist_tag:
                    title = link_tag.get_text(strip=True)
                    artist = artist_tag.get_text(strip=True).replace(' - ', '')
                    song_id_match = re.search(r'/play/(\d+)\.html', link_tag['href'])

                    if song_id_match:
                        song_id = song_id_match.group(1)
                        found_songs.append({
                            'id': song_id,
                            'title': title,
                            'artist': artist,
                            'url': f"https://www.gequhai.com/play/{song_id}.html"
                        })
                
            return found_songs

        except requests.exceptions.RequestException as e:
            print_status(f"搜索请求失败 (尝试 {attempt+1}/{max_retries+1}): {e}")
        
        if attempt < max_retries:
            delay = INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt)
            print_status(f"在 {delay:.1f} 秒后重试...")
            time.sleep(delay)
    
    print_status("搜索歌曲失败，已达最大重试次数。")
    return []

# --- 主程序执行部分 (已修改为命令行模式) ---
if __name__ == "__main__":
    
    # 检查是否提供了命令行参数
    if len(sys.argv) < 2:
        print_status("错误: 缺少搜索关键词参数。用法: python download_music.py \"歌曲名 歌手名\"")
        # 退出状态码 1，表示执行失败
        sys.exit(1) 
    
    # 获取命令行参数，即搜索关键词
    search_query = sys.argv[1].strip()

    if not search_query:
        print_status("未输入搜索关键词，程序退出。")
        sys.exit(1) 

    print_status(f"--- 欢迎使用 GitHub Actions 音乐下载工作流 ---")
    print_status(f"【目标关键词】: '{search_query}'")
    
    # 预先检查 FFmpeg 可用性（在 Actions 环境中通常需要手动安装）
    if check_ffmpeg_available():
        print_status("【格式转换】FFmpeg 检查成功，AAC 文件将自动转换为 MP3。")
    else:
        print_status("【格式转换】FFmpeg 警告: 转换功能可能不可用。")
    print_status("-" * 20)

    # 1. 搜索歌曲
    found_songs = search_songs(search_query)

    if not found_songs:
        print_status(f"没有找到与 '{search_query}' 相关的歌曲。程序退出。")
        sys.exit(0)
    
    # --- 关键修改：只处理第一首歌曲 ---
    song_to_process = found_songs[0]
    
    print_status(f"\n--- 步骤 2: 目标歌曲 (列表第一首) ---")
    print_status(f"歌曲: {song_to_process['title']} - {song_to_process['artist']} (ID: {song_to_process['id']})")
    print_status("-" * 20)
    
    # 2. 获取播放链接和歌词
    music_data, lrc_content, txt_content = get_music_url(song_to_process['id'])

    # 3. 下载文件和歌词
    download_success = download_music_file(music_data.get('url') if music_data else None,
                                           song_to_process['title'],
                                           song_to_process['artist'],
                                           lrc_content,
                                           txt_content)
                                           
    print_status("-" * 20)
    if download_success:
        print_status(f"【成功】文件和歌词已下载/更新。")
        # 退出状态码 0，表示执行成功
        sys.exit(0)
    else:
        print_status(f"【失败】未能成功下载音乐文件。请检查源链接或 Cookies。")
        # 退出状态码 1，表示执行失败
        sys.exit(1)
