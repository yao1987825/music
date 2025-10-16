# download_music.py

import requests
import json
import time
import sys
import os
import re
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Set

# --- 全局配置 ---
BASE_URL = "https://api.vkeys.cn/v2/music/tencent"
DOWNLOAD_DIR = Path("downloads")  # 下载目录

# --- API 常量和重试配置 ---
INITIAL_REQUEST_DELAY = 1.0
MAX_RETRIES = 3
RETRY_DELAY_MULTIPLIER = 2
API_TIMEOUT = 20

def print_status(message, end='\n'):
    """统一的打印函数，方便管理输出并确保立即显示。"""
    print(f"[STATUS] {message}", end=end)
    sys.stdout.flush()

def sanitize_filename(filename: str) -> str:
    """清理文件名，移除或替换无效字符，确保跨平台兼容性。"""
    filename = re.sub(r'[\\/:*?"<>|]', '_', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    return filename[:200]

def download_streaming_file(url: str, target_path: Path, retries=MAX_RETRIES) -> bool:
    """使用流式下载文件，包含重试和错误处理。"""
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
            return False

        if attempt < retries:
            time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    return False

def save_lyric_file(content: str, target_path: Path) -> bool:
    """保存歌词文件。"""
    if not content or not content.strip():
        return True
    
    try:
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print_status(f"歌词文件保存成功: {target_path.name}")
        return True
    except IOError as e:
        print_status(f"歌词文件写入失败 ({target_path.name}): {e}")
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
                print_status(f"API 返回错误: {data.get('message', '未知业务错误')}")
                return None
        except requests.exceptions.RequestException as e:
            print_status(f"API 请求失败 (尝试 {attempt + 1}/{MAX_RETRIES + 1}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
    return None

def process_single_song(query: str, expected_files: Set[Path]) -> bool:
    """
    处理单首歌曲下载，并将成功生成的文件路径添加到 expected_files 集合中。
    """
    print_status(f"\n{'='*15} 开始处理: {query} {'='*15}")
    
    processed_query = query.replace('-', ' ').strip()
    search_api = f"{BASE_URL}?word={urllib.parse.quote(processed_query)}"
    search_data = vkeys_api_request(search_api)
    
    if not search_data:
        print_status(f"❌ 搜索 '{query}' 失败或无结果。")
        return False
    
    song_info = search_data[0]
    song_id, title, artist = song_info['id'], song_info['song'], song_info['singer']
    print_status(f"找到最匹配结果: {title} - {artist} (ID: {song_id})")

    filename_prefix = sanitize_filename(f"{title} - {artist}")

    # 获取音乐链接
    details_api = f"{BASE_URL}/geturl?id={song_id}"
    details = vkeys_api_request(details_api)
    if not details or not details.get('url'):
        return False

    music_format = details.get('format', 'mp3')
    music_file_path = DOWNLOAD_DIR / f"{filename_prefix}.{music_format}"
    
    # 获取歌词
    lyric_api = f"{BASE_URL}/lyric?id={song_id}"
    lyrics_data = vkeys_api_request(lyric_api)
    lrc_content = lyrics_data.get('lrc', '') if lyrics_data else ''
    trans_content = lyrics_data.get('trans', '') if lyrics_data else ''
    lrc_file_path = DOWNLOAD_DIR / f"{filename_prefix}.lrc"
    trans_file_path = DOWNLOAD_DIR / f"{filename_prefix}.trans.txt"
    
    # 执行下载和保存
    # 只有当文件不存在或下载/保存成功时，才将其加入期望列表
    if music_file_path.exists() or download_streaming_file(details['url'], music_file_path):
        expected_files.add(music_file_path)

    if lrc_content and (lrc_file_path.exists() or save_lyric_file(lrc_content, lrc_file_path)):
        expected_files.add(lrc_file_path)

    if trans_content and (trans_file_path.exists() or save_lyric_file(trans_content, trans_file_path)):
        expected_files.add(trans_file_path)

    print_status(f"✅ 歌曲 '{title}' 处理完毕。")
    return True

def sync_directory(expected_files: Set[Path]):
    """将 downloads 目录与期望的文件列表同步，删除多余的文件。"""
    print_status("\n" + "="*60)
    print_status("--- 步骤 3: 同步目录，清理旧文件 ---")
    
    if not DOWNLOAD_DIR.exists():
        print_status("下载目录不存在，无需清理。")
        return

    actual_files = {p for p in DOWNLOAD_DIR.rglob('*') if p.is_file()}
    files_to_delete = actual_files - expected_files

    if not files_to_delete:
        print_status("目录已是最新状态，没有文件需要删除。")
        return

    print_status(f"发现 {len(files_to_delete)} 个需要删除的旧文件...")
    for f in files_to_delete:
        try:
            f.unlink()
            print_status(f"  - 已删除: {f.name}")
        except OSError as e:
            print_status(f"  - 删除失败: {f.name} ({e})")
    print_status("目录清理完成。")


def main(filepath: str):
    print_status("--- 欢迎使用 GitHub Actions 音乐下载与同步工作流 ---")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True) # 确保下载目录存在
    
    print_status(f"--- 步骤 1: 读取歌曲列表文件: {filepath} ---")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        sys.exit(1)

    song_queries = [line.strip() for line in lines if line.strip() and not line.strip().startswith('#')]

    if not song_queries:
        print_status("歌曲列表为空。")
    else:
        print_status(f"找到 {len(song_queries)} 首歌曲待处理。")
    
    print_status("\n" + "="*60)
    print_status("--- 步骤 2: 处理和下载歌曲 ---")
    
    # 这个集合将保存所有应该存在于 downloads 目录中的文件
    expected_files_from_list: Set[Path] = set()
    
    for i, query in enumerate(song_queries, 1):
        print_status(f"\n--- 任务进度: ({i}/{len(song_queries)}) ---")
        process_single_song(query, expected_files_from_list)
        time.sleep(2) 

    # 执行同步清理
    sync_directory(expected_files_from_list)
    
    print_status("\n" + "="*60)
    print_status("--- 工作流执行完毕 ---")
    print_status("【工作流结果】: 成功完成。")
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    
    main(sys.argv[1])
