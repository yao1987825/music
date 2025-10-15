import requests
import json
import time
import sys
import os
import re
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any

# --- 全局配置 ---
# 请注意，vkeys.cn的API可能需要注册或有调用限制，
# 若调用失败，请检查API文档或联系API提供方。
BASE_URL = "https://api.vkeys.cn/v2/music/tencent"
DOWNLOAD_DIR = Path("downloads")  # 下载文件将保存到的目录

# --- API 常量和重试配置 ---
INITIAL_REQUEST_DELAY = 1.0  # 初始请求延迟
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY_MULTIPLIER = 2  # 重试延迟乘数
API_TIMEOUT = 15 # API 请求超时时间(秒)


def print_status(message, end='\n'):
    """统一的打印函数，方便管理输出并确保立即显示。"""
    print(f"[STATUS] {message}", end=end)
    sys.stdout.flush()  # 强制刷新输出缓冲区


def sanitize_filename(filename):
    """清理文件名，移除或替换无效字符，确保文件名合法和跨平台兼容。"""
    filename = re.sub(r'[\\/:*?"<>|]', '', filename)  # 移除Windows/Linux不允许的字符
    filename = re.sub(r'[\s]+', ' ', filename).strip()  # 将多个空格替换为单个，并去除首尾空格
    filename = filename[:200]  # 限制文件名长度，避免过长
    return filename


def download_streaming_file(url: str, target_path: Path, retries=MAX_RETRIES) -> bool:
    """下载文件，包含重试和错误处理。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)  # 确保下载目录存在

    if target_path.exists():
        print_status(f"文件已存在，跳过下载: {target_path.name}")
        return True

    print_status(f"开始下载 {target_path.name} (从: {url})...")
    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, timeout=API_TIMEOUT) as r:
                r.raise_for_status()  # 检查 HTTP 状态码，如果不是 2xx 则抛出异常

                # 可选: 打印文件大小信息 (requests.get() 后再访问 headers 有时才准确)
                # total_size = int(r.headers.get('content-length', 0))
                # if total_size > 0:
                #     print_status(f"文件大小: {total_size / (1024*1024):.2f}MB")

                with open(target_path, 'wb') as f:
                    # 不使用 tqdm，直接写入，方便 Actions 日志
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                print_status(f"下载成功: {target_path.name}")
                return True

        except requests.exceptions.HTTPError as e:
            print_status(f"HTTP 错误 {e.response.status_code} 下载 {url}: {e.response.text[:100]}...")
            if e.response.status_code == 403:
                print_status("下载链接可能已失效或被拒绝。")
                return False
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


def save_lyric_file(content: str, filename_prefix: str, extension: str) -> bool:
    """保存歌词文件。"""
    if not content:
        print_status(f"没有歌词内容，跳过保存 .{extension} 文件。")
        return False

    file_path = DOWNLOAD_DIR / f"{filename_prefix}.{extension}"

    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)  # 再次确保目录存在
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print_status(f"歌词文件保存成功: {file_path.name}")
        return True
    except IOError as e:
        print_status(f"歌词文件写入失败 ({file_path.name}): {e}")
        return False


# --- vkeys.cn API 封装函数 ---

def vkeys_search_songs(query: str) -> List[Dict[str, Any]] | None:
    """调用腾讯音乐搜索 API 获取初步结果列表。"""
    processed_query = query.replace('-', ' ').strip()
    search_api = f"{BASE_URL}?word={urllib.parse.quote(processed_query)}"

    print_status(f"正在向 API 搜索 '{processed_query}' 获取初步结果列表...")

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(search_api, timeout=API_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 200 and data.get("data"):
                # 适配原脚本的接口：id, title, artist
                adapted_results = []
                for song_data in data["data"]:
                    adapted_results.append({
                        'id': song_data['id'],
                        'title': song_data['song'],
                        'artist': song_data['singer'],
                        'album': song_data.get('album', '')
                    })
                return adapted_results[:10]  # 返回前10条
            else:
                print_status(f"API 搜索返回错误或无数据: {data.get('message', '未知错误')}")
                # DEBUG: uncomment to see full API response
                # print_status(f"DEBUG: Search API response: {json.dumps(data, indent=2)}")
                return None

        except requests.RequestException as e:
            print_status(f"API 搜索请求失败 (尝试 {attempt + 1}/{MAX_RETRIES + 1}): {e}")

        if attempt < MAX_RETRIES:
            time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    print_status(f"API 搜索歌曲失败，已达最大重试次数。")
    return None


def vkeys_get_song_details(song_id: int) -> Dict[str, Any] | None:
    """根据歌曲 ID 调用 vkeys.cn 获取详细信息和播放链接。"""
    url_api = f"{BASE_URL}/geturl?id={song_id}"
    print_status(f"正在获取歌曲 {song_id} 的详情和下载链接...")

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(url_api, timeout=API_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 200 and data.get("data") and data["data"].get("url"):
                return data["data"] # 返回完整的 data 字典，包含 url, format 等
            else:
                print_status(f"获取歌曲 {song_id} 链接 API 返回错误或无数据: {data.get('message', '未知错误')}")
                # DEBUG: uncomment to see full API response
                # print_status(f"DEBUG: Get URL API response: {json.dumps(data, indent=2)}")
                return None

        except requests.RequestException as e:
            print_status(f"获取歌曲 {song_id} 链接请求失败 (尝试 {attempt + 1}/{MAX_RETRIES + 1}): {e}")
        
        if attempt < MAX_RETRIES:
            time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    print_status(f"获取歌曲 {song_id} 链接失败，已达最大重试次数。")
    return None


def vkeys_get_song_lyrics(song_id: int) -> Dict[str, Any] | None:
    """根据歌曲 ID 调用 vkeys.cn 获取歌词详情（包含lrc, trans, yrc）。"""
    lyric_api = f"{BASE_URL}/lyric?id={song_id}"
    print_status(f"正在获取歌曲 {song_id} 的歌词...")

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(lyric_api, timeout=API_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("code") == 200 and data.get("data"):
                return data["data"]
            else:
                print_status(f"获取歌曲 {song_id} 歌词 API 返回错误或无数据: {data.get('message', '未知错误')}")
                # DEBUG: uncomment to see full API response
                # print_status(f"DEBUG: Get Lyric API response: {json.dumps(data, indent=2)}")
                return None

        except requests.RequestException as e:
            print_status(f"获取歌曲 {song_id} 歌词请求失败 (尝试 {attempt + 1}/{MAX_RETRIES + 1}): {e}")
        
        if attempt < MAX_RETRIES:
            time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    print_status(f"获取歌曲 {song_id} 歌词失败，已达最大重试次数。")
    return None


# --- 核心流程：下载器封装，适配 Actions 输出 ---

def download_music_and_lyrics(song_info: Dict[str, Any]):
    """
    处理单首歌曲的下载和歌词保存，适配 GitHub Actions 的非交互式流程。
    """
    song_id = song_info['id']
    title = song_info['title']
    artist = song_info['artist']

    print_status(f"\n--- 步骤 2: 目标歌曲 ---")
    print_status(f"歌曲: {title} - {artist} (ID: {song_id})")
    print_status("-" * 40)

    all_success = True

    # 1. 获取歌曲 URL 详情
    print_status("\n--- 步骤 3: 获取音乐播放链接 ---")
    details = vkeys_get_song_details(song_id)
    music_url = details.get('url') if details else None
    music_format = details.get('format', 'flac') if details else 'flac' # 默认flac

    if not music_url:
        print_status("❌ 歌曲链接获取失败或API未提供有效URL。")
        return False # 返回 False 表示有失败

    filename_prefix = sanitize_filename(f"{title} - {artist}")
    music_filename = f"{filename_prefix}.{music_format}"
    music_file_path = DOWNLOAD_DIR / music_filename
    
    # 2. 下载歌曲文件
    print_status("\n--- 步骤 4: 下载音乐文件 ---")
    download_success = download_streaming_file(music_url, music_file_path)
    if not download_success:
        print_status(f"❌ 音乐文件 '{music_filename}' 下载失败。")
        all_success = False

    # 3. 获取并保存歌词
    print_status("\n--- 步骤 5: 获取并保存歌词 ---")
    lyrics_data = vkeys_get_song_lyrics(song_id)
    
    lrc_content = lyrics_data.get('lrc', '') if lyrics_data else ''
    trans_content = lyrics_data.get('trans', '') if lyrics_data else '' # 翻译歌词

    lyric_save_success = True
    if lrc_content:
        if not save_lyric_file(lrc_content, filename_prefix, 'lrc'):
            lyric_save_success = False
    else:
        print_status("⚠️ 未找到LRC歌词内容。")

    if trans_content:
        if not save_lyric_file(trans_content, filename_prefix + "_trans", 'txt'): # 将翻译保存为txt
            lyric_save_success = False
    else:
        print_status("⚠️ 未找到翻译歌词内容。")
    
    if not lyric_save_success:
        print_status("❌ 至少一个歌词文件保存失败。")
        all_success = False

    print_status("-" * 40)
    if all_success:
        print_status(f"✅ 【成功】歌曲 '{title}' 已下载到 '{DOWNLOAD_DIR}' 目录。")
    else:
        print_status(f"❌ 【失败】歌曲 '{title}' 下载或保存歌词时发生问题。")

    return all_success


# --- 主程序入口点 (GitHub Actions 兼容) ---
if __name__ == "__main__":
    
    if len(sys.argv) < 2:
        print_status("错误: 缺少搜索关键词参数。用法: python download_music.py \"歌曲名 歌手名\"")
        sys.exit(1)
    
    search_query = sys.argv[1].strip()

    if not search_query:
        print_status("未输入搜索关键词，程序退出。")
        sys.exit(1)

    print_status(f"--- 欢迎使用 GitHub Actions 音乐下载工作流 (由 vkeys.cn 提供) ---")
    print_status(f"【目标关键词】: '{search_query}'")
    print_status("-" * 40)
    
    # 1. 搜索歌曲
    print_status("\n--- 步骤 1: 搜索歌曲 ---")
    found_songs = vkeys_search_songs(search_query)

    if not found_songs:
        print_status(f"❌ 没有找到与 '{search_query}' 相关的歌曲。程序退出。")
        sys.exit(0) # 退出状态码 0，表示成功执行但没有结果
    
    # --- 只处理第一首歌曲 ---
    song_to_process = found_songs[0]
    
    download_status = download_music_and_lyrics(song_to_process)
                                           
    print_status("-" * 40)
    if download_status:
        print_status(f"✅ 【工作流成功】所有指定文件已下载/更新。")
        sys.exit(0) # 退出状态码 0，表示执行成功
    else:
        print_status(f"❌ 【工作流失败】未能完全成功下载所有文件。")
        sys.exit(1) # 退出状态码 1，表示执行失败
