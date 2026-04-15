import json
import time
import uuid
import base64
import hmac
import hashlib
import httpx
from datetime import datetime, timezone
from .config import Config, ZAI_SALT_KEY
from .display import print_status, print_response_start, stream_live


def generate_x_signature(prompt, token, user_id, timestamp, request_id):
    """
    Generate X-Signature for Z.ai API using HMAC-SHA256.

    Algorithm from chatglm.py:
    1. bucket = timestamp / 300000 (5-min windows)
    2. w_key = HMAC(salt_key, bucket)
    3. sorted_params = "key1,val1|key2,val2|key3,val3"
    4. prompt_b64 = base64(prompt)
    5. data_to_sign = "{sorted_params}|{prompt_b64}|{timestamp}"
    6. signature = HMAC(w_key, data_to_sign)
    """
    # Calculate bucket (5-minute window)
    bucket = int(int(timestamp) / 300000)

    # Generate w_key
    w_key = hmac.new(
        ZAI_SALT_KEY.encode(), str(bucket).encode(), hashlib.sha256
    ).hexdigest()

    # Sort params and build payload
    payload_dict = {
        "timestamp": timestamp,
        "requestId": request_id,
        "user_id": user_id,
    }
    sorted_items = sorted(payload_dict.items(), key=lambda x: x[0])
    sorted_payload = ",".join([f"{k},{v}" for k, v in sorted_items])

    # Base64 encode prompt
    prompt_b64 = base64.b64encode(prompt.strip().encode()).decode()

    # Build data to sign
    data_to_sign = f"{sorted_payload}|{prompt_b64}|{timestamp}"

    # Generate signature
    signature = hmac.new(
        w_key.encode(), data_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    return signature


class GLMClient:
    def __init__(self):
        self.config = Config()
        self.cookies = self._load_cookies()
        self.token = self._load_token()
        self.user_id = self._extract_user_id()
        self.chat_id = None
        self.last_assistant_message_id = None
        self.first_user_message_id = None
        self.client = httpx.Client(http2=True, timeout=120.0)
        self.cached_headers = None
        
    def close(self):
        self.client.close()
        
    def __del__(self):
        try:
            self.close()
        except:
            pass

    def _load_cookies(self):
        try:
            with open(self.config.COOKIES_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _load_token(self):
        try:
            with open(self.config.TOKEN_FILE, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def _get_cookie_string(self):
        """Build cookie string for API requests."""
        cookie_parts = []
        # Always include the token cookie
        if "token" in self.cookies:
            cookie_parts.append(f"token={self.cookies['token']}")
        # Add other essential cookies
        for name, value in self.cookies.items():
            if name not in ["token"] and name.startswith(("ssxmod", "cdn", "acw")):
                cookie_parts.append(f"{name}={value}")
        return "; ".join(cookie_parts)

    def _extract_user_id(self):
        """Extract user_id from JWT token (payload is base64)."""
        if not self.token:
            return ""
        try:
            parts = self.token.split(".")
            if len(parts) == 3:
                # Decode payload
                payload = parts[1]
                # Add padding if needed
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += "=" * padding
                decoded = base64.urlsafe_b64decode(payload)
                data = json.loads(decoded)
                return data.get("id", "")
        except Exception:
            pass
        return ""

    def _build_headers(self, prompt=None):
        """Build request headers for API calls, including X-Signature."""
        if self.cached_headers:
            return self.cached_headers.copy()
            
        headers = self.config.BASE_HEADERS.copy()

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        cookie_string = self._get_cookie_string()
        if cookie_string:
            headers["Cookie"] = cookie_string

        # Add X-FE-Version
        headers["X-FE-Version"] = self.config.FE_VERSION

        self.cached_headers = headers
        return headers.copy()

    def _build_headers_for_completion(self, prompt, request_id, timestamp):
        """Build headers with X-Signature for completion requests."""
        headers = self._build_headers(prompt)

        # Generate X-Signature
        signature = generate_x_signature(
            prompt, self.token, self.user_id, timestamp, request_id
        )
        headers["X-Signature"] = signature

        return headers

    def _get_base_completion_params(self):
        if not hasattr(self, '_cached_base_params'):
            self._cached_base_params = {
                "user_id": self.user_id,
                "version": "0.0.1",
                "platform": "web",
                "token": self.token if self.token else "",
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "language": "en-US",
                "languages": "en-US",
                "timezone": "Europe/Madrid",
                "cookie_enabled": "true",
                "screen_width": "1280",
                "screen_height": "800",
                "screen_resolution": "1280x800",
                "viewport_height": "444",
                "viewport_width": "1191",
                "viewport_size": "1191x444",
                "color_depth": "32",
                "pixel_ratio": "2",
                "search": "",
                "hash": "",
                "host": "chat.z.ai",
                "hostname": "chat.z.ai",
                "protocol": "https:",
                "referrer": f"{self.config.BASE_URL}/",
                "title": f"Z.ai - Free AI Chatbot & Agent powered by {self.config.MODEL}",
                "timezone_offset": "-120",
                "is_mobile": "false",
                "is_touch": "false",
                "max_touch_points": "1",
                "browser_name": "Chrome",
                "os_name": "Windows",
            }
        return self._cached_base_params.copy()

    def _build_completion_params(self, chat_id, request_id, timestamp):
        """
        Build the ~37 query params required by /api/v2/chat/completions.
        """
        now = datetime.now(timezone.utc)
        params = self._get_base_completion_params()
        
        params.update({
            "timestamp": timestamp,
            "requestId": request_id,
            "current_url": f"{self.config.BASE_URL}/c/{chat_id}",
            "pathname": f"/c/{chat_id}",
            "local_time": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
            "utc_time": now.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "signature_timestamp": timestamp,
        })
        return params

    def _create_chat(self, prompt):
        """Create a new chat session via POST /api/v1/chats/new."""
        if self.chat_id:
            return self.chat_id

        self.config.print_status("Creating new chat...", "cyan")

        self.first_user_message_id = str(uuid.uuid4())
        message_id = self.first_user_message_id
        payload = {
            "chat": {
                "id": "",
                "title": "New Chat",
                "models": [self.config.MODEL],
                "params": {},
                "history": {
                    "messages": {
                        message_id: {
                            "id": message_id,
                            "parentId": None,
                            "childrenIds": [],
                            "role": "user",
                            "content": prompt,
                            "timestamp": int(time.time()),
                            "models": [self.config.MODEL],
                        }
                    },
                    "currentId": message_id,
                },
                "tags": [],
                "flags": [],
                "features": [
                    {
                        "type": "tool_selector",
                        "server": "tool_selector_h",
                        "status": "hidden",
                    }
                ],
                "mcp_servers": ["advanced-search"],
                "enable_thinking": True,
                "auto_web_search": True,
                "message_version": 1,
                "extra": {},
                "timestamp": int(time.time() * 1000),
                "type": "default",
            }
        }

        headers = self._build_headers(prompt)
        headers["Accept"] = "application/json"
        headers["Referer"] = f"{self.config.BASE_URL}/"

        try:
            resp = self.client.post(
                f"{self.config.API_V1}/chats/new",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            self.chat_id = data["id"]
            self.config.print_status(f"Chat created: {self.chat_id[:8]}...", "green")
            return self.chat_id
        except httpx.HTTPStatusError as e:
            self.config.print_status(
                f"Failed to create chat: {e.response.status_code}", "red"
            )
            self.config.print_status(f"Response: {e.response.text[:200]}", "red")
            return None
        except Exception as e:
            self.config.print_status(f"Create chat error: {e}", "red")
            return None

    def _get_base_completion_payload(self):
        if hasattr(self, '_cached_base_payload'):
            return self._cached_base_payload.copy()
            
        self._cached_base_payload = {
            "stream": True,
            "model": self.config.MODEL,
            "params": {},
            "extra": {},
            "mcp_servers": ["advanced-search"],
            "features": {
                "image_generation": False,
                "web_search": False,
                "auto_web_search": True,
                "preview_mode": True,
                "flags": [],
                "vlm_tools_enable": False,
                "vlm_web_search_enable": False,
                "vlm_website_mode": False,
                "enable_thinking": True,
            },
            "background_tasks": {
                "title_generation": True,
                "tags_generation": True,
            },
        }
        return self._cached_base_payload.copy()

    def _build_completion_payload(self, prompt, chat_id, assistant_message_id, user_message_id, parent_id):
        """Build the JSON payload for chat completions."""
        current_time = datetime.now(timezone.utc)

        payload = self._get_base_completion_payload()
        
        payload.update({
            "chat_id": chat_id,
            "messages": [{"role": "user", "content": prompt}],
            "signature_prompt": prompt,
            "id": assistant_message_id,
            "current_user_message_id": user_message_id,
            "current_user_message_parent_id": parent_id,
            "variables": {
                "{{USER_NAME}}": "User",
                "{{USER_LOCATION}}": "Unknown",
                "{{CURRENT_DATETIME}}": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                "{{CURRENT_DATE}}": current_time.strftime("%Y-%m-%d"),
                "{{CURRENT_TIME}}": current_time.strftime("%H:%M:%S"),
                "{{CURRENT_WEEKDAY}}": current_time.strftime("%A"),
                "{{CURRENT_TIMEZONE}}": "Europe/Madrid",
                "{{USER_LANGUAGE}}": "en-US",
            }
        })
        
        return payload

    def chat(self, prompt):
        """Send a message and stream the response."""
        if not self.token:
            print_status("No auth token found", "red")
            return

        # Create chat if needed
        is_new_chat = False
        if not self.chat_id:
            chat_id = self._create_chat(prompt)
            if not chat_id:
                print_status("Failed to create chat session", "red")
                return
            is_new_chat = True
        else:
            chat_id = self.chat_id

        print_status("Sending message to GLM...", "cyan")

        # Context tracking IDs
        if is_new_chat:
            user_message_id = self.first_user_message_id
            parent_id = None
        else:
            user_message_id = str(uuid.uuid4())
            parent_id = self.last_assistant_message_id
            
        assistant_message_id = str(uuid.uuid4())

        # Generate request IDs and timestamp
        request_id = self.config.generate_request_id()
        timestamp = str(int(time.time() * 1000))

        # Build headers with X-Signature
        headers = self._build_headers_for_completion(prompt, request_id, timestamp)
        headers["Accept"] = "*/*"
        headers["Accept-Language"] = "en-US"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Site"] = "same-origin"
        headers["Sec-GPC"] = "1"
        headers["DNT"] = "1"
        headers["Referer"] = f"{self.config.BASE_URL}/c/{chat_id}"

        # Build query params
        params = self._build_completion_params(chat_id, request_id, timestamp)

        # Build payload
        payload = self._build_completion_payload(prompt, chat_id, assistant_message_id, user_message_id, parent_id)

        try:
            with self.client.stream(
                "POST",
                f"{self.config.API_V2}/chat/completions",
                headers=headers,
                params=params,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    print_status(f"Request failed: {resp.status_code}", "red")
                    try:
                        error_body = resp.text
                        print_status(f"Error: {error_body[:300]}", "red")
                    except Exception:
                        pass
                    return

                print_response_start()

                def content_generator():
                    raw_buffer = ""
                    for line in resp.iter_lines():
                        if line.startswith("data:"):
                            json_str = line[5:].strip()
                            if not json_str:
                                continue

                            try:
                                data = json.loads(json_str)
                                if data.get("type") == "chat:completion":
                                    inner_data = data.get("data", {})
                                    phase = inner_data.get("phase", "")

                                    delta = inner_data.get("delta_content", "")
                                    edit_content = inner_data.get("edit_content", "")
                                    edit_index = inner_data.get("edit_index", -1)

                                    if edit_content and edit_index >= 0:
                                        raw_buffer = raw_buffer[:edit_index] + edit_content
                                        yield {"phase": "replace_buffer", "content": raw_buffer}
                                    elif delta:
                                        raw_buffer += delta
                                        yield {"phase": phase if phase and phase != "done" else "answer", "content": delta}

                                    # Handle usage info safely by yielding it
                                    if phase == "other":
                                        usage = inner_data.get("usage", {})
                                        if usage:
                                            total_tokens = usage.get("total_tokens", "?")
                                            yield {"phase": "usage", "content": str(total_tokens)}
                                        continue
                                        
                                    # Handle done: evaluate break AFTER yielding content 
                                    if phase == "done" or inner_data.get("done"):
                                        break

                            except json.JSONDecodeError:
                                pass

                final_content = stream_live(content_generator())
                self.last_assistant_message_id = assistant_message_id
                return final_content

        except httpx.ConnectError as e:
            print_status(f"Connection error: {e}", "red")
        except Exception as e:
            print_status(f"Chat error: {e}", "red")

    def reset_chat(self):
        """Reset the current chat session."""
        self.chat_id = None
        self.last_assistant_message_id = None
        self.first_user_message_id = None
