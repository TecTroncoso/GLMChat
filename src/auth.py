import asyncio
import nodriver as uc
import json
from .config import Config, find_browser


class AuthExtractor:
    """
    Authenticates with Z.ai (chat.z.ai) via Google OAuth using nodriver.
    Extracts:
      - JWT token (from localStorage)
      - Cookies (token cookie required for API calls)

    X-Signature is generated dynamically using HMAC (no browser interception needed).
    """

    def __init__(self):
        self.config = Config()

    async def extract_credentials(self):
        self.config.print_status(
            "Starting browser (this might take a sec)...", "yellow"
        )
        browser_path = find_browser()
        if browser_path:
            self.config.print_status(f"Using: {browser_path}", "dim")
            browser = await uc.start(
                browser_executable_path=browser_path,
                headless=self.config.HEADLESS,
            )
        else:
            self.config.print_status("No browser found! Install Brave or Chrome", "red")
            return None, None

        try:
            page = await browser.get(f"{self.config.BASE_URL}/")

            self.config.print_status("Waiting for page to load...", "cyan")
            await page.sleep(5)

            # Click login button using XPath
            self.config.print_status("Looking for login button...", "cyan")
            try:
                login_btn = await page.xpath(
                    '//*[@id="chat-container"]/div[1]/nav/div[2]/div/div[3]/div/button',
                    timeout=10,
                )
                if login_btn:
                    await login_btn[0].click()
                    await page.sleep(2)
                else:
                    self.config.print_status(
                        "Login button not found, trying chat input...", "yellow"
                    )
                    try:
                        chat_input = await page.find(".chat-input textarea", timeout=5)
                        await chat_input.click()
                        await page.sleep(2)
                    except Exception:
                        pass
            except Exception as e:
                self.config.print_status(f"Login button click failed: {e}", "yellow")
                try:
                    chat_input = await page.find(".chat-input textarea", timeout=5)
                    await chat_input.click()
                    await page.sleep(2)
                except Exception:
                    pass

            # Click Google login button using XPath
            self.config.print_status("Clicking Google login button...", "cyan")
            try:
                google_btn = await page.xpath(
                    "/html/body/div/div[1]/div[3]/div/div/div[1]/form/div[3]/button[1]",
                    timeout=10,
                )
                if google_btn:
                    await google_btn[0].click()
                    await page.sleep(3)
                else:
                    self.config.print_status(
                        "Google button not found, trying fallback selectors...",
                        "yellow",
                    )
                    for selector in [
                        'button:has-text("Google")',
                        "div.google-login-btn",
                    ]:
                        try:
                            btn = await page.find(selector, timeout=3)
                            await btn.click()
                            await page.sleep(3)
                            break
                        except Exception:
                            continue
            except Exception as e:
                self.config.print_status(f"Google button click failed: {e}", "yellow")
                self.config.print_status("Please click Google login manually", "yellow")
                await page.sleep(10)

            # Wait for Google OAuth popup
            self.config.print_status("Waiting for Google OAuth...", "cyan")
            await page.sleep(3)

            # Check for new tabs (Google OAuth popup)
            tabs = browser.tabs
            if len(tabs) > 1:
                page = tabs[-1]
                await page.sleep(2)

            # Enter email
            self.config.print_status("Entering email...", "cyan")
            try:
                email_input = await page.find(
                    'input[type="email"]#identifierId', timeout=10
                )
                await email_input.click()
                await page.sleep(0.5)

                for char in self.config.ZAI_EMAIL:
                    await email_input.send_keys(char)
                    await page.sleep(0.05)

                await page.sleep(0.5)
                await page.send(
                    uc.cdp.input_.dispatch_key_event(
                        type_="rawKeyDown",
                        windows_virtual_key_code=13,
                        native_virtual_key_code=13,
                        key="Enter",
                        code="Enter",
                    )
                )
                await page.send(
                    uc.cdp.input_.dispatch_key_event(
                        type_="keyUp",
                        windows_virtual_key_code=13,
                        native_virtual_key_code=13,
                        key="Enter",
                        code="Enter",
                    )
                )
                await page.sleep(4)

                # Enter password
                self.config.print_status("Entering password...", "cyan")
                password_input = await page.find(
                    'input[type="password"][name="Passwd"]', timeout=10
                )
                await password_input.click()
                await page.sleep(0.5)

                for char in self.config.ZAI_PASSWORD:
                    await password_input.send_keys(char)
                    await page.sleep(0.05)

                await page.sleep(0.5)
                await page.send(
                    uc.cdp.input_.dispatch_key_event(
                        type_="rawKeyDown",
                        windows_virtual_key_code=13,
                        native_virtual_key_code=13,
                        key="Enter",
                        code="Enter",
                    )
                )
                await page.send(
                    uc.cdp.input_.dispatch_key_event(
                        type_="keyUp",
                        windows_virtual_key_code=13,
                        native_virtual_key_code=13,
                        key="Enter",
                        code="Enter",
                    )
                )
                await page.sleep(5)
            except Exception as e:
                self.config.print_status(
                    f"Could not enter credentials automatically: {e}", "yellow"
                )
                self.config.print_status(
                    "Please login manually, then come back here...", "yellow"
                )
                await page.sleep(15)

            # Wait for redirect back to Z.ai
            self.config.print_status("Waiting for redirect to Z.ai...", "cyan")
            await page.sleep(5)

            # Switch back to main tab
            tabs = browser.tabs
            page = tabs[0]
            await page.sleep(3)

            # Extract cookies
            self.config.print_status("Grabbing cookies...", "cyan")
            cookies_raw = await page.send(uc.cdp.network.get_cookies())

            cookie_dict = {}
            for cookie in cookies_raw:
                cookie_dict[cookie.name] = cookie.value

            # Extract JWT token
            self.config.print_status("Getting auth token...", "cyan")
            token = None
            try:
                for key in ["token", "access_token", "auth_token", "zai_token"]:
                    token = await page.evaluate(f'localStorage.getItem("{key}")')
                    if token:
                        break

                if not token:
                    for key in ["userToken", "user", "auth", "userInfo"]:
                        try:
                            token_obj = await page.evaluate(
                                f'JSON.parse(localStorage.getItem("{key}"))'
                            )
                            if token_obj and isinstance(token_obj, dict):
                                token = (
                                    token_obj.get("value")
                                    or token_obj.get("token")
                                    or token_obj.get("access_token")
                                )
                                if token:
                                    break
                        except Exception:
                            pass
            except Exception as e:
                self.config.print_status(f"Token extraction failed: {e}", "red")

            if token:
                self.config.print_status(f"Got token: {token[:30]}...", "green")
                with open(self.config.TOKEN_FILE, "w") as f:
                    f.write(token)
            else:
                self.config.print_status(
                    "Couldn't find token in localStorage", "yellow"
                )

            # Save cookies
            with open(self.config.COOKIES_FILE, "w") as f:
                json.dump(cookie_dict, f, indent=2)

            self.config.update_login_time()
            self.config.print_status(
                f"Success! Got {len(cookie_dict)} cookies", "green"
            )

            return cookie_dict, token

        except Exception as e:
            self.config.print_status(f"Login failed: {e}", "red")
            return None, None

        finally:
            if browser:
                try:
                    await browser.stop()
                except Exception:
                    pass


async def main():
    if not Config.ZAI_EMAIL or not Config.ZAI_PASSWORD:
        Config.print_status("No email/password in .env file!", "red")
        return

    extractor = AuthExtractor()
    cookies, token = await extractor.extract_credentials()

    if cookies and token:
        Config.print_status("Authentication successful!", "green")
    else:
        Config.print_status("Authentication failed!", "red")


if __name__ == "__main__":
    asyncio.run(main())
