import requests
import json
import time
import sys
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any

# --- 全局配置 ---
# 请注意，vkeys.cn的API可能需要注册或有调用限制，
# 若调用失败，请检查API文档或联系API提供方。
BASE_URL = "https://api.vkeys.cn/v2/music/tencent"
DOWNLOAD_DIR = Path("downloads")  # 下载文件将保存到的目录
FFMPEG_AVAILABLE = False  # FFmpeg 是否可用，初始为 False

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
    filename = re.sub(r'[[\s]]+', ' ', filename).strip()  # 将多个空格替换为单个，并去除首尾空格
    filename = filename[:200]  # 限制文件名长度，避免过长
    return filename


def check_ffmpeg_available():
    """检查 FFmpeg 是否已安装并可用。"""
    global FFMPEG_AVAILABLE
    try:
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


def convert_to_mp3(file_path: Path):
    """
    将文件转换为 MP3 格式。支持 FLAC 和 AAC 作为输入。
    需要 FFmpeg 安装在系统路径中。
    """
    if not FFMPEG_AVAILABLE:
        print_status(f"FFmpeg 未安装或不可用，无法转换文件: {file_path.name}")
        return file_path

    if not file_path.exists():
        print_status(f"原始文件不存在，无法转换: {file_path.name}")
        return file_path

    mp3_path = file_path.with_suffix('.mp3')
    print_status(f"尝试将 {file_path.name} 转换为 {mp3_path.name}...")

    try:
        # 使用 ffmpeg 进行转换，-vn 移除视频流，-acodec libmp3lame 指定MP3编码器，-q:a 2 质量为VBR-2 (高质量)
        subprocess.run(['ffmpeg', '-i', str(file_path), '-vn', '-acodec', 'libmp3lame', '-q:a', '2', str(mp3_path)],
                       check=True, capture_output=True, timeout=600)  # 600秒超时
        print_status(f"转换成功: {mp3_path.name}")
        os.remove(file_path)  # 删除原始文件
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
                        # 'album': song_data['album'] # 可以根据需要添加更多信息
                    })
                return adapted_results[:10]  # 返回前10条，如同原脚本
            else:
                print_status(f"API 搜索返回错误或无数据: {data.get('message', '未知错误')}")
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
    print
