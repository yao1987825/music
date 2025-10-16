# download_music.py

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
BASE_URL = "https://api.vkeys.cn/v2/music/tencent"
DOWNLOAD_DIR = Path("downloads")  # 下载文件将保存到的目录

# --- API 常量和重试配置 ---
INITIAL_REQUEST_DELAY = 1.0
MAX_RETRIES = 3
RETRY_DELAY_MULTIPLIER = 2
API_TIMEOUT = 20  # 请求超时时间(秒)

def print_status(message, end='\n'):
    """统一的打印函数，方便管理输出并确保立即显示。"""
    print(f"[STATUS] {message}", end=end)
    sys.stdout.flush()

def sanitize_filename(filename: str) -> str:
    """清理文件名，移除或替换无效字符，确保跨平台兼容性。"""
    filename = re.sub(r'[\\/:*?"<>|]', '_', filename) # 将非法字符替换为下划线
    filename = re.sub(r'\s+', ' ', filename).strip() # 合并多余空格
    return filename[:200] # 限制文件名长度

def download_streaming_file(url: str, target_path: Path, retries=MAX_RETRIES) -> bool:
    """使用流式下载文件，包含重试和错误处理。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        print_status(f"文件已存在，跳过下载: {target_path.name}")
        return True

    print_status(f"开始下载 {target_path.name}...")
    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, timeout=API_TIMEOUT) as r:
                r.raise_for_status()
                with open(target_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                print_status(f"下载成功: {target_path.name}")
                return True
        except requests.exceptions.RequestException as e:
            print_status(f"下载请求错误 (尝试 {attempt + 1}/{retries+1}): {e}")
        except IOError as e:
            print_status(f"文件写入错误 {target_path}: {e}")
            return False # 写入错误通常不可恢复，直接失败

        if attempt < retries:
            delay = INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt)
            time.sleep(delay)
    print_status(f"下载 {target_path.name} 失败，已达最大重试次数。")
    return False

def save_lyric_file(content: str, filename_prefix: str, extension: str) -> bool:
    """保存歌词文件。"""
    if not content or not content.strip():
        print_status(f"无有效歌词内容，跳过保存 .{extension} 文件。")
        return True # 没有内容不算失败
    
    file_path = DOWNLOAD_DIR / f"{filename_prefix}.{extension}"
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print_status(f"歌词文件保存成功: {file_path.name}")
        return True
    except IOError as e:
        print_status(f"歌词文件写入失败 ({file_path.name}): {e}")
        return False

def vkeys_api_request(url: str) -> Dict[str, Any] | None:
    """通用的 vkeys API 请求函数，包含重试逻辑。"""
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=API_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if data.get("code") == 200 and data.get("data"):
                return data["data"]
            else:
                # 即使请求成功，API也可能返回业务错误
                print_status(f"API 返回错误: {data.get('message', '未知业务错误')}")
                return None
        except requests.exceptions.RequestException as e:
            print_status(f"API 请求失败 (尝试 {attempt + 1}/{MAX_RETRIES + 1}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    return None

def process_single_song(query: str) -> bool:
    """根据单个查询关键词，搜索、下载并保存歌曲和歌词。返回 True/False。"""
    print_status(f"\n{'='*15} 开始处理: {query} {'='*15}")
    
    # 1. 搜索歌曲
    processed_query = query.replace('-', ' ').strip()
    search_api = f"{BASE_URL}?word={urllib.parse.quote(processed_query)}"
    search_data = vkeys_api_request(search_api)
    
    if not search_data:
        print_status(f"❌ 搜索 '{query}' 失败或无结果。")
        return False
    
    song_info = search_data[0] # 只处理最相关的第一个结果
    song_id = song_info['id']
    title = song_info['song']
    artist = song_info['singer']
    print_status(f"找到最匹配结果: {title} - {artist} (ID: {song_id})")

    # 2. 获取歌曲详情和链接
    details_api = f"{BASE_URL}/geturl?id={song_id}"
    details = vkeys_api_request(details_api)
    if not details or not details.get('url'):
        print_status("❌ 获取歌曲下载链接失败。")
        return False

    music_url = details['url']
    music_format = details.get('format', 'mp3') # 默认用mp3，更通用
    filename_prefix = sanitize_filename(f"{title} - {artist}")
    music_file_path = DOWNLOAD_DIR / f"{filename_prefix}.{music_format}"

    # 3. 下载歌曲文件
    download_success = download_streaming_file(music_url, music_file_path)

    # 4. 获取并保存歌词
    lyric_api = f"{BASE_URL}/lyric?id={song_id}"
    lyrics_data = vkeys_api_request(lyric_api)
    lrc_content = lyrics_data.get('lrc', '') if lyrics_data else ''
    trans_content = lyrics_data.get('trans', '') if lyrics_data else ''

    lrc_save_success = save_lyric_file(lrc_content, filename_prefix, 'lrc')
    trans_save_success = save_lyric_file(trans_content, filename_prefix, 'trans.txt')

    final_status = download_success and lrc_save_success and trans_save_success
    if final_status:
        print_status(f"✅ 【成功】歌曲 '{title}' 已完整处理。")
    else:
        print_status(f"❌ 【失败】歌曲 '{title}' 处理过程中出现问题。")
    
    return final_status

def main(filepath: str):
    """读取指定的歌曲列表文件，并逐行下载。"""
    print_status(f"--- 欢迎使用 GitHub Actions 音乐下载工作流 (由 vkeys.cn 提供) ---")
    print_status(f"正在读取歌曲列表文件: {filepath}")
    print_status("-" * 60)
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print_status(f"错误: 歌曲列表文件 '{filepath}' 未找到。")
        sys.exit(1)

    song_queries = [line.strip() for line in lines if line.strip() and not line.strip().startswith('#')]

    if not song_queries:
        print_status("在文件中没有找到有效的歌曲名称。工作流正常结束。")
        sys.exit(0)

    total = len(song_queries)
    success_count = 0
    
    for i, query in enumerate(song_queries, 1):
        print_status(f"\n--- 任务进度: ({i}/{total}) ---")
        if process_single_song(query):
            success_count += 1
        # 在每个任务之间短暂休息，避免对API造成太大压力
        time.sleep(2) 

    print_status("\n" + "="*60)
    print_status("--- 所有任务完成 ---")
    print_status(f"总任务数: {total}")
    print_status(f"✅ 成功: {success_count}")
    print_status(f"❌ 失败: {total - success_count}")
    print_status("="*60)

    if success_count < total:
        print_status("【工作流结果】: 部分任务失败。")
        sys.exit(1) # 退出状态码 1，表示执行中存在失败
    else:
        print_status("【工作流结果】: 所有任务成功完成。")
        sys.exit(0) # 退出状态码 0，表示执行成功

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python download_music.py <歌曲列表文件路径>")
        print("例如: python download_music.py song-list.md")
        sys.exit(1)
    
    song_list_file = sys.argv[1]
    main(song_list_file)
