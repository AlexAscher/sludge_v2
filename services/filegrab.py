import aiohttp
import os
import logging
from typing import Optional
from config import FILEGRAB_BASE_URL, FILEGRAB_API_KEY, FILEGRAB_TIMEOUT, TEMP_DIR

logger = logging.getLogger(__name__)


async def download_via_filegrab(source_url: str, dest_filename: Optional[str] = None) -> str:
    """
    Uses FileGrab API to prepare and download a file from source_url.
    Returns local path to downloaded file in TEMP_DIR.
    """
    headers = {"Content-Type": "application/json"}
    payload = {"url": source_url}
    if FILEGRAB_API_KEY:
        payload["key"] = FILEGRAB_API_KEY
    timeout = aiohttp.ClientTimeout(total=FILEGRAB_TIMEOUT)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 0) Pre-check if file is downloadable
        check_endpoint = f"{FILEGRAB_BASE_URL}/check-file-downloadability"
        try:
            async with session.post(check_endpoint, json=payload, headers=headers) as check_resp:
                check_text = await check_resp.text()
                if check_resp.status != 200:
                    logger.error(f"FileGrab check returned {check_resp.status}: {check_text}")
                    # map common statuses to friendly messages
                    if check_resp.status == 400:
                        raise Exception("FileGrab: invalid URL or unsupported link (400)")
                    if check_resp.status == 401:
                        raise Exception("FileGrab: invalid API key (401)")
                    if check_resp.status == 403:
                        raise Exception("FileGrab: server denied access to the file (403)")
                    if check_resp.status == 404:
                        raise Exception("FileGrab: file not found (404)")
                    if check_resp.status == 429:
                        raise Exception("FileGrab: rate limited (429)")
                    raise Exception(f"FileGrab check failed: {check_resp.status} - {check_text}")
                else:
                    try:
                        check_json = await check_resp.json()
                        downloadable = check_json.get("file-downloadable", True)
                        if not downloadable:
                            raise Exception("FileGrab reports the file is not downloadable")
                    except Exception:
                        # If parsing fails, continue but log
                        logger.info("FileGrab check returned non-json or missing fields; continuing to download attempt")
        except Exception as e:
            logger.exception("FileGrab request failed during check")
            raise

        # 1) Optionally get file-type / name to choose extension before download
        try:
            type_endpoint = f"{FILEGRAB_BASE_URL}/get-file-type"
            async with session.post(type_endpoint, json=payload, headers=headers) as type_resp:
                if type_resp.status == 200:
                    try:
                        type_json = await type_resp.json()
                        file_type = type_json.get("file-type")
                        mime = type_json.get("mime-type")
                    except Exception:
                        file_type = None
                        mime = None
                else:
                    file_type = None
                    mime = None
        except Exception:
            file_type = None
            mime = None

        # 2) Call download endpoint
        download_endpoint = f"{FILEGRAB_BASE_URL}/download-file"
        try:
            async with session.post(download_endpoint, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    cd = resp.headers.get("Content-Disposition", "")
                    filename = None
                    if "filename=" in cd:
                        try:
                            filename = cd.split("filename=")[-1].strip().strip('"')
                        except Exception:
                            filename = None
                    if not filename:
                        filename = os.path.basename(source_url.split("?")[0]) or "file"
                        if "." not in filename:
                            # prefer file_type/mime from earlier call
                            if file_type:
                                filename += f".{file_type.lstrip('.')}"
                            elif mime:
                                if "video" in mime:
                                    filename += ".mp4"
                                elif "image" in mime:
                                    filename += ".jpg"

                    if dest_filename:
                        filename = dest_filename

                    dest_path = os.path.join(TEMP_DIR, filename)
                    with open(dest_path, "wb") as f:
                        f.write(data)

                    return dest_path
                else:
                    text = await resp.text()
                    logger.error(f"FileGrab returned status {resp.status}: {text}")
                    if resp.status == 400:
                        raise Exception("FileGrab API error: 400 - invalid URL or unsupported resource")
                    if resp.status == 401:
                        raise Exception("FileGrab API error: 401 - invalid API key")
                    if resp.status == 403:
                        raise Exception("FileGrab API error: 403 - access denied to the file")
                    if resp.status == 404:
                        raise Exception("FileGrab API error: 404 - file not found")
                    if resp.status == 429:
                        raise Exception("FileGrab API error: 429 - rate limited")
                    raise Exception(f"FileGrab API error: {resp.status} - {text}")
        except Exception as e:
            logger.exception("FileGrab download failed")
            raise
