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
            # 检查 API 响应码和数据字段
            if data.get("code") == 200 and data.get("data"):
                return data["data"]
            else:
                # 记录 API 逻辑错误
                if 'msg' in data:
                    print_status(f"API 响应逻辑错误: {data['msg']} (Code: {data.get('code')})")
                return None
        except requests.exceptions.RequestException as e:
            print_status(f"API 请求失败 (尝试 {attempt + 1}/{MAX_RETRIES+1}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(INITIAL_REQUEST_DELAY * (RETRY_DELAY_MULTIPLIER ** attempt))
        except json.JSONDecodeError:
            print_status("API 响应不是有效的 JSON 格式。")
            return None
    return None

def process_single_song(query: str, expected_files: Set[Path]) -> bool:
    """处理单首歌曲下载，并将成功生成的文件路径添加到 expected_files 集合中。
    优化点：确保已存在的文件被添加到 expected_files，避免被 sync_directory 删除。"""
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

    # --- 音乐文件处理：保持原始格式 ---
    details_api = f"{BASE_URL}/geturl?id={song_id}"
    details = vkeys_api_request(details_api)

    if not details or not details.get('url'):
        print_status(f"❌ 无法获取歌曲 {title} - {artist} 的下载链接或原始格式信息。")
        return False

    # music_format 即为原始格式，符合要求
    music_format = details.get('format', 'mp3') 
    music_file_path = DOWNLOAD_DIR / f"{filename_prefix}.{music_format}"
    
    # 1. 检查文件是否存在并加入预期列表
    file_was_present = music_file_path.exists()
    if file_was_present:
        expected_files.add(music_file_path)
        print_status(f"音乐文件已存在，标记为预期文件: {music_file_path.name}")
    
    # 2. 如果文件不存在，则开始下载
    download_success = False
    if not file_was_present:
        download_success = download_streaming_file(details['url'], music_file_path)
        if download_success:
            expected_files.add(music_file_path)
    
    # 如果音乐文件既不存在，又下载失败，则停止处理歌词，返回失败
    if not file_was_present and not download_success:
        print_status(f"❌ 音乐文件下载失败，跳过歌词处理。")
        return False

    # --- 歌词文件处理 ---
    lyric_api = f"{BASE_URL}/lyric?id={song_id}"
    lyrics_data = vkeys_api_request(lyric_api)
    
    lrc_content = lyrics_data.get('lrc', '') if lyrics_data else ''
    trans_content = lyrics_data.get('trans', '') if lyrics_data else ''
    lrc_file_path = DOWNLOAD_DIR / f"{filename_prefix}.lrc"
    trans_file_path = DOWNLOAD_DIR / f"{filename_prefix}.trans.txt"
    
    # 处理 LRC
    if lrc_file_path.exists():
        expected_files.add(lrc_file_path)
    elif lrc_content:
        if save_lyric_file(lrc_content, lrc_file_path):
            expected_files.add(lrc_file_path)

    # 处理翻译
    if trans_file_path.exists():
        expected_files.add(trans_file_path)
    elif trans_content:
        if save_lyric_file(trans_content, trans_file_path):
            expected_files.add(trans_file_path)

    # 只要音乐文件在 expected_files 中，就认为该歌曲处理成功
    return music_file_path in expected_files

def sync_directory(expected_files: Set[Path]):
    """将 downloads 目录与期望的文件列表同步，删除多余的文件。"""
    print_status("\n" + "="*60)
    print_status("--- 步骤 3: 同步目录，清理旧文件 ---")
    
    if not DOWNLOAD_DIR.exists():
        print_status("下载目录不存在，无需清理。")
        return

    # 只考虑 downloads 目录下的一级文件
    actual_files = {p for p in DOWNLOAD_DIR.iterdir() if p.is_file()}
    files_to_delete = actual_files - expected_files

    if not files_to_delete:
        print_status("目录已是最新状态，没有文件需要删除。")
        return

    for f in files_to_delete:
        try:
            f.unlink()
            print_status(f"  - 已删除: {f.name}")
        except OSError as e:
            print_status(f"  - 删除失败: {f.name} ({e})")
    print_status("目录清理完成。")


def parse_markdown_table(lines: List[str]) -> List[str]:
    """从 Markdown 文件行中解析出表格里的歌曲查询列表。"""
    queries = []
    is_table_content = False
    for line in lines:
        cleaned_line = line.strip()
        if not cleaned_line.startswith('|'):
            is_table_content = False  # 如果遇到非表格行，就重置状态
            continue

        if '---' in cleaned_line:
            is_table_content = True  # 从分隔线之后开始算是表格内容
            continue

        if not is_table_content:
            continue

        # 切分表格行
        columns = [col.strip() for col in cleaned_line.split('|')]
        # 期望格式: ['', '歌手', '歌曲', ''] -> 长度至少为4
        if len(columns) >= 4:
            # columns[0] 为空字符串
            artist = columns[1].strip()
            song_title = columns[2].strip()
            
            # 确保提取的不是空内容
            if artist and song_title:
                queries.append(f"{artist} {song_title}")
    return queries


def main(filepath: str):
    print_status("--- 欢迎使用 GitHub Actions 音乐下载与同步工作流 ---")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    print_status(f"--- 步骤 1: 读取并解析歌曲列表文件: {filepath} ---")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print_status(f"❌ 错误：未找到文件 {filepath}")
        sys.exit(1)

    # 使用新的解析函数
    song_queries = parse_markdown_table(lines)

    if not song_queries:
        print_status("在 Markdown 表格中没有找到有效的歌曲。")
    else:
        print_status(f"从表格中解析出 {len(song_queries)} 首歌曲待处理。")
    
    print_status("\n" + "="*60)
    print_status("--- 步骤 2: 处理和下载歌曲 ---")
    
    expected_files_from_list: Set[Path] = set()
    
    for i, query in enumerate(song_queries, 1):
        print_status(f"\n--- 任务进度: ({i}/{len(song_queries)}) ---")
        process_single_song(query, expected_files_from_list)
        time.sleep(2)  # 增加延迟以降低 API 压力和避免封禁

    sync_directory(expected_files_from_list)
    
    print_status("\n" + "="*60)
    print_status("--- 工作流执行完毕 ---")
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_status("用法: python download_music.py <markdown_filepath>")
        sys.exit(1)
        
    main(sys.argv[1])
