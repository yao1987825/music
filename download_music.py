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

# --- 全局配置 (硬编码，请注意安全风险并定期更新) ---
# 这些 Cookies 和 Headers 可能有有效期，如果代码运行失败，
# 务必从浏览器中获取最新的 Cookies 和 Headers 并更新这里的字典。
# 警告：直接硬编码敏感信息不安全，推荐使用GitHub Secrets或环境变量。
cookies = {
    'Hm_tf_no8z3ihhnja': '1759891990',
    'Hm_lvt_no8z3ihhnja': '1759891990,1759914819,1759943487,1759975751',
    'Hm_lvt_49c19bcfda4e5fdfea1a9bb225456abe': '1759891991,1759914819,1759943486,1759975753',
    'HMACCOUNT': 'F2D39E6791DCFBD4',
    'PHPSESSID': 'ba8veihlq2066mpmrbvi4tngm3',
    'server_name_session': '48ac7eb90472522710b482184d07bcd6',
    'Hm_lpvt_49c19bcfda4e5fdfea1a9bb225456abe': '1759982677',
    'Hm_lpvt_no8z3ihhnja': '1759982679',
}

get_html_headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'cache-control': 'max-age=0',
    'dnt': '1',
    'priority': 'u=0, i',
    'referer': 'https://www.gequhai.com/', # *** 修改此处：改为网站根目录 ***
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
}

post_api_headers = {
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'dnt': '1',
    'origin': 'https://www.gequhai.com',
    'priority': 'u=1, i',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    'x-custom-header': 'SecretKey', # 这个 'SecretKey' 可能需要从网站实时获取或有有效期
    'x-requested-with': 'XMLHttpRequest',
}


# --- 常量和配置 ---
INITIAL_REQUEST_DELAY = 1.0 # 初始请求延迟
MAX_RETRIES = 3 # 最大重试次数
RETRY_DELAY_MULTIPLIER = 2 # 重试延迟乘数
DOWNLOAD_DIR = Path("downloads") # 下载文件将保存到的目录
FFMPEG_AVAILABLE = False # FFmpeg 是否可用，初始为 False
RETRY_TIME_PATTERN = re.compile(r'请 (\d+) 秒后再试。') # 用于解析API响应中的等待时间
BR_TAG_PATTERN = re.compile(r'<br\s*/?>', re.IGNORECASE) # 用于清理歌词中的HTML br标签


def print_status(message, end='\n'):
    """统一的打印函数，方便管理输出并确保立即显示。"""
    print(f"[STATUS] {message}", end=end)
    sys.stdout.flush() # 强制刷新输出缓冲区


def sanitize_filename(filename):
    """清理文件名，移除或替换无效字符，确保文件名合法和跨平台兼容。"""
    filename = re.sub(r'[\\/:*?"<>|]', '', filename) # 移除Windows/Linux不允许的字符
    filename = re.sub(r'[\s]+', ' ', filename).strip() # 将多个空格替换为单个，并去除首尾空格
    filename = filename[:200] # 限制文件名长度，避免过长
    return filename


def check_ffmpeg_available():
    """检查 FFmpeg 是否已安装并可用。"""
    global FFMPEG_AVAILABLE
    try:
        # 尝试运行 ffmpeg -version 命令，如果成功则 FFmpeg 可用
        subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True, timeout=5)
        FFMPEG_AVAILABLE = True
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        FFMPEG_AVAILABLE = False
        return False
    except Exception as e:
        print_status(f"检查FFmpeg时发生错误: {e}")
        FFMPEG_AVAILABLE = False
        return False


def convert_aac_to_mp3(file_path):
    """
    将 AAC 文件转换为 MP3 格式。
    需要 FFmpeg 安装在系统路径中。
    """
    if not FFMPEG_AVAILABLE:
        print_status(f"FFmpeg 未安装或不可用，无法转换文件: {file_path}")
        return file_path

    mp3_path = file_path.with_suffix('.mp3')
    print_status(f"尝试将 {file_path.name} 转换为 {mp3_path.name}...")

    try:
        # 使用 ffmpeg 进行转换，-vn 移除视频流，-acodec libmp3lame 指定MP3编码器，-q:a 2 质量为VBR-2 (高质量)
        subprocess.run(['ffmpeg', '-i', str(file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(mp3_path)],
                       check=True, capture_output=True, timeout=600) # 600秒超时
        print_status(f"转换成功: {mp3_path.name}")
        os.remove(file_path) # 删除原始AAC文件
        return mp3_path
    except subprocess.CalledProcessError as e:
        print_status(f"FFmpeg 转换失败 ({file_path.name}): {e.stderr.decode(errors='ignore')}")
        return file_path
    except FileNotFoundError:
        print_status(f"FFmpeg 命令未找到，请确保已安装并配置 PATH。")
        return file_path
    except subprocess.TimeoutExpired:
        print_status(f"FFmpeg 转换超时 ({file_path.name})。")
        return file_path
    except Exception as e:
        print_status(f"转换过程中发生错误 ({file_path.name}): {e}")
        return file_path


def download_file(url, target_path_str, retries=MAX_RETRIES):
    """下载文件，包含重试和错误处理。"""
    target_path = Path(target_path_str)
    
    # 确保下载目录存在
    target_path.parent.mkdir(parents=True, exist_ok=True) 

    if target_path.exists():
        print_status(f"文件已存在，跳过下载: {target_path.name}")
        return True

    print_status(f"开始下载 {target_path.name} (从: {url})...")
    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, headers=get_html_headers, cookies=cookies, timeout=15) as r:
                r.raise_for_status() # 检查 HTTP 状态码，如果不是 2xx 则抛出异常
                
                total_size = int(r.headers.get('content-length', 0))
                # print_status(f"文件大小: {total_size / (1024*1024):.2f}MB") # 可选，显示文件大小

                with open(target_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk: # 过滤掉保持连接的空行
                            f.write(chunk)
                print_status(f"下载成功: {target_path.name}")
                return True

        except requests.exceptions.HTTPError as e:
            print_status(f"HTTP 错误 {e.response.status_code} 下载 {url}: {e.response.text[:100]}...")
            if e.response.status_code == 403:
                print_status("可能是反爬机制或 Cookies/Headers 过期。")
                return False # 403通常意味着权限问题，不值得重试
        except requests.exceptions.Timeout:
            print_status(f"下载请求超时: {url}")
        except requests.exceptions.ConnectionError as e:
            print_status(f"连接错误: {e}")
        except requests.exceptions.RequestException as e:
            print_status(f"下载请求发生未知错误 {url}: {e}")
        except IOError as e:
            print_status(f"文件写入错误 {target_path}: {e}")

        if attempt < retries:
            delay = INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt)
            print_status(f"下载失败，在 {delay:.1f} 秒后重试 (尝试 {attempt + 1}/{retries})...")
            time.sleep(delay)
        else:
            print_status(f"下载 {target_path.name} 失败，已达最大重试次数。")
    return False


def download_lyric_file(content, filename_prefix, extension):
    """下载歌词文件 (LRC 或 TXT)。"""
    if not content:
        print_status(f"没有歌词内容，跳过下载 .{extension} 文件。")
        return False
    
    file_path = DOWNLOAD_DIR / f"{filename_prefix}.{extension}"
    
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True) # 再次确保目录存在
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print_status(f"歌词文件下载成功: {file_path.name}")
        return True
    except IOError as e:
        print_status(f"歌词文件写入失败 ({file_path.name}): {e}")
        return False


def download_music_file(music_url, title, artist, lrc_content, txt_content):
    """
    下载音乐文件，并处理歌词、可能的 AAC 到 MP3 转换。
    如果 music_url 为 None，则只下载歌词。
    """
    filename_prefix = sanitize_filename(f"{title} - {artist}")
    all_success = True

    # 1. 下载音乐文件
    if music_url:
        file_extension = "mp3"  # 默认假定mp3
        if '.aac' in music_url.lower(): # 简单检查URL是否包含.aac
            file_extension = "aac"

        music_file_path = DOWNLOAD_DIR / f"{filename_prefix}.{file_extension}"
        
        song_download_success = download_file(music_url, music_file_path)
        
        if song_download_success:
            if music_file_path.exists() and file_extension == "aac":
                # 如果是aac文件且FFmpeg可用，尝试转换
                converted_path = convert_aac_to_mp3(music_file_path)
                if converted_path != music_file_path: # 如果转换成功，文件名会改变
                    music_file_path = converted_path # 更新路径
                    print_status(f"音乐已转换为MP3: {music_file_path.name}")
                else:
                    print_status(f"AAC文件保持原样 (未转换或转换失败): {music_file_path.name}")
            else:
                 print_status(f"音乐文件已下载: {music_file_path.name}")
        else:
            print_status(f"音乐文件 '{filename_prefix}.{file_extension}' 下载失败。")
            all_success = False
    else:
        print_status("没有找到音乐下载链接，跳过音乐文件下载。")

    # 2. 下载歌词文件
    if not download_lyric_file(lrc_content, filename_prefix, 'lrc'):
        all_success = False
    if not download_lyric_file(txt_content, filename_prefix, 'txt'):
        all_success = False

    return all_success


def get_song_details_from_html(song_id, max_retries=MAX_RETRIES):
    """根据歌曲ID获取歌曲的详细页HTML内容。"""
    detail_url = f"https://www.gequhai.com/play/{song_id}.html"
    print_status(f"正在获取歌曲详情页: {detail_url}")

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(detail_url, headers=get_html_headers, cookies=cookies, timeout=15)
            response.raise_for_status()
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

    # 解析歌词 (LRC 格式)
    lrc_container = soup.find('div', class_='lrc-box')
    lrc_content = lrc_container.get_text(separator='\n').strip() if lrc_container else ""

    # 解析歌词 (TXT 格式，去除时间戳)
    txt_content = ""
    if lrc_content:
        # 移除行首的 [mm:ss.xx] 或 [mm:ss]
        txt_content = re.sub(r'\[\d{2}:\d{2}(?:\.\d{2})?\]', '', lrc_content)
        txt_content = BR_TAG_PATTERN.sub('\n', txt_content).strip() # 处理 <br> 标签

    music_url = None
    music_data = {}

    # 优先级 1: 尝试从 <audio> 标签的 src 属性中直接获取
    audio_tag = soup.find('audio', id=f'xplayer-{song_id}')
    if audio_tag and audio_tag.get('src'):
        music_url = audio_tag['src'].strip()
        print_status(f"直接从 <audio> 标签找到链接: {music_url[:60]}...")
        music_data = {'url': music_url, 'type': 'audio'}
        return music_data, lrc_content, txt_content

    # 优先级 2: 尝试从 JSON-LD 结构中查找（较少见，但有些网站会用）
    script_ld_json = soup.find('script', {'type': 'application/ld+json'})
    if script_ld_json:
        try:
            ld_json_data = json.loads(script_ld_json.string)
            if isinstance(ld_json_data, list):
                ld_json_data = ld_json_data[0] # 取第一个对象
            
            # 根据 schema.org 常见的属性查找音乐URL
            if 'audio' in ld_json_data and 'contentUrl' in ld_json_data['audio']:
                music_url = ld_json_data['audio']['contentUrl']
                print_status(f"从 LD+JSON 'audio' 找到链接: {music_url[:60]}...")
                music_data = {'url': music_url, 'type': 'ld+json_audio'}
                return music_data, lrc_content, txt_content
            elif 'encoding' in ld_json_data and isinstance(ld_json_data['encoding'], list):
                for encoding_item in ld_json_data['encoding']:
                    if encoding_item.get('@type') == 'AudioObject' and encoding_item.get('contentUrl'):
                        music_url = encoding_item['contentUrl']
                        print_status(f"从 LD+JSON 'encoding' 找到链接: {music_url[:60]}...")
                        music_data = {'url': music_url, 'type': 'ld+json_encoding'}
                        return music_data, lrc_content, txt_content

        except json.JSONDecodeError as e:
            print_status(f"解析 JSON-LD 失败: {e}")
        except Exception as e:
            print_status(f"处理 LD+JSON 时发生错误: {e}")

    # 优先级 3: 尝试通过 POST API 获取链接 (你原始脚本的方式)
    api_url = "https://www.gequhai.com/api/getmusic.php"
    post_data = {
        'id': song_id,
        'type': 'json',
        'key': post_api_headers.get('x-custom-header', 'SecretKey') # 使用headers中的key或默认值
    }
    
    print_status(f"尝试通过 POST API 获取音乐链接 (ID: {song_id})...")
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(api_url, data=post_data, headers=post_api_headers, cookies=cookies, timeout=15)
            response.raise_for_status()
            music_data_api = response.json()

            if music_data_api and music_data_api.get('code') == 1 and music_data_api.get('data') and music_data_api['data'].get('url'):
                print_status(f"通过 API 成功获取音乐链接: {music_data_api['data']['url'][:60]}...")
                return music_data_api['data'], lrc_content, txt_content
            else:
                error_msg = music_data_api.get('msg', '未知API错误')
                print_status(f"API 返回错误: {error_msg}")
                # 检查是否是请求过快提示
                match = RETRY_TIME_PATTERN.search(error_msg)
                if match:
                    wait_time = int(match.group(1))
                    print_status(f"API 请求过快，将在 {wait_time + 1} 秒后重试。")
                    time.sleep(wait_time + 1) # 多等一秒
                    continue # 立即重试，不计入常规重试延迟
                print_status(f"API 未返回有效音乐数据或 'code' 不为 1: {music_data_api}")

        except requests.exceptions.RequestException as e:
            print_status(f"POST API 请求失败 (尝试 {attempt+1}/{MAX_retries+1}): {e}")
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
    # *** 修正 URL 编码方式，移除空格 ***
    # 观察到gequhai.com在搜索"唯一 邓紫棋"时，其URL路径变为 /s/唯一邓紫棋
    # 即网站会将搜索词中的空格移除或特殊处理，而不是编码为 %20
    cleaned_query_for_url = query.replace(' ', '')
    encoded_query = urllib.parse.quote(cleaned_query_for_url)
    search_url = f"https://www.gequhai.com/s/{encoded_query}"
    # *** 修正结束 ***

    print_status(f"正在搜索: {search_url}")

    for attempt in range(max_retries + 1):
        try:
            response = requests.get(search_url, headers=get_html_headers, cookies=cookies, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            # 查找所有 class 为 "song-item" 的 li 元素
            song_items = soup.find_all('li', class_='song-item')

            if not song_items:
                print_status("没有找到歌曲结果。")
                # DEBUG 打印收到 HTML 片段，如果问题仍然存在，请取消注释查看网站实际返回内容
                # print_status(f"DEBUG: Received HTML (first 1000 chars):\n{response.text[:1000]}")
                return []

            found_songs = []
            for item in song_items:
                link_tag = item.find('a', class_='song-title')
                artist_tag = item.find('span', class_='song-artist')

                if link_tag and artist_tag:
                    title = link_tag.get_text(strip=True)
                    artist = artist_tag.get_text(strip=True).replace(' - ', '').strip() # 清理artist信息
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
                time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    
    print_status("搜索歌曲失败，已达最大重试次数。")
    return []


# --- 主程序执行部分 (入口点) ---
if __name__ == "__main__":
    
    # 检查是否提供了命令行参数
    if len(sys.argv) < 2:
        print_status("错误: 缺少搜索关键词参数。用法: python download_music.py \"歌曲名 歌手名\"")
        sys.exit(1) # 退出状态码 1，表示执行失败
    
    # 获取命令行参数，即搜索关键词
    search_query = sys.argv[1].strip()

    if not search_query:
        print_status("未输入搜索关键词，程序退出。")
        sys.exit(1)

    print_status(f"--- 欢迎使用 GitHub Actions 音乐下载工作流 ---")
    print_status(f"【目标关键词】: '{search_query}'")
    print_status("-" * 40)
    
    # 预先检查 FFmpeg 可用性
    if check_ffmpeg_available():
        print_status("【格式转换】FFmpeg 检查成功，AAC 文件将尝试转换为 MP3。")
    else:
        print_status("【格式转换】FFmpeg 警告: 转换功能可能不可用，AAC 文件将保持原样。")
    print_status("-" * 40)

    # 1. 搜索歌曲
    print_status("\n--- 步骤 1: 搜索歌曲 ---")
    found_songs = search_songs(search_query)

    if not found_songs:
        print_status(f"没有找到与 '{search_query}' 相关的歌曲。程序退出。")
        sys.exit(0) # 退出状态码 0，表示成功执行但没有结果

    # --- 关键修改：只处理第一首歌曲 ---
    song_to_process = found_songs[0]
    
    print_status(f"\n--- 步骤 2: 目标歌曲 (列表第一首) ---")
    print_status(f"歌曲: {song_to_process['title']} - {song_to_process['artist']} (ID: {song_to_process['id']})")
    print_status("-" * 40)
    
    # 2. 获取播放链接和歌词
    print_status("\n--- 步骤 3: 获取音乐播放链接和歌词内容 ---")
    music_data, lrc_content, txt_content = get_music_url(song_to_process['id'])
    
    if not music_data and not lrc_content and not txt_content:
        print_status(f"未能获取到歌曲 '{song_to_process['title']}' 的任何下载链接或歌词。程序退出。")
        sys.exit(1)

    # 3. 下载文件和歌词
    print_status("\n--- 步骤 4: 下载文件和歌词 ---")
    download_success = download_music_file(music_data.get('url') if music_data else None,
                                           song_to_process['title'],
                                           song_to_process['artist'],
                                           lrc_content,
                                           txt_content)
                                           
    print_status("-" * 40)
    if download_success:
        print_status(f"【成功】文件和歌词已下载/更新到 '{DOWNLOAD_DIR}' 目录。")
        sys.exit(0) # 退出状态码 0，表示执行成功
    else:
        print_status(f"【失败】未能成功下载所有文件。请检查源链接、Cookies 或网络连接。")
        sys.exit(1) # 退出状态码 1，表示执行失败
