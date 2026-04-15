from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.live import Live
from rich.rule import Rule
from rich.text import Text
import time
import re

console = Console()
HTML_CLEANER = re.compile(r"<[^>]+>")

# Minimum interval between expensive Markdown rebuilds (seconds).
# Data is always captured instantly; only the *render* is throttled.
_RENDER_INTERVAL = 0.12


def print_status(message, style="white"):
    console.print(f"[{style}][[GLM]][/{style}] {message}", justify="left")


def print_response_start():
    console.print()
    console.print(Rule("[bold cyan]Response[/bold cyan]", style="cyan", align="left"))
    console.print()


def stream_live(content_generator):
    full_thinking = ""
    full_answer = ""
    tokens_used = None
    last_render_time = 0.0
    has_changed = False

    def build_render_group():
        elements = []

        if full_thinking:
            # Z.ai sends thinking inside <details> tags which rich.Markdown natively hides entirely.
            # We strip HTML tags from the thinking text so it renders properly in the terminal.
            clean_thinking = HTML_CLEANER.sub("", full_thinking).strip()
            if clean_thinking:
                md_thinking = Markdown(clean_thinking, code_theme="monokai", justify="left")
                elements.append(Panel(md_thinking, title="[dim]Thinking...[/dim]", border_style="dim"))

        if full_answer:
            # Also remove dangling </details> tags that occasionally leak into the answer delta
            clean_answer = full_answer.replace("</details>", "") if "</details>" in full_answer else full_answer
            clean_answer = clean_answer.strip()
            if clean_answer:
                elements.append(Markdown(clean_answer, code_theme="monokai", justify="left"))

        if not elements:
            return Text("")

        return Group(*elements)

    def _do_refresh(live):
        nonlocal last_render_time, has_changed
        renderable = build_render_group()
        title = "[bold white]GLM[/bold white]"
        if tokens_used:
            title += f" [dim](Tokens: {tokens_used})[/dim]"
        panel = Panel(
            renderable,
            border_style="bright_cyan",
            padding=(1, 2),
            title=title,
            title_align="left",
        )
        live.update(panel, refresh=True)
        last_render_time = time.monotonic()
        has_changed = False

    with Live(console=console, auto_refresh=False) as live:
        for chunk in content_generator:
            if isinstance(chunk, dict):
                phase = chunk.get("phase")
                content = chunk.get("content", "")

                if content:
                    has_changed = True

                if phase == "replace_buffer":
                    if "<details" in content:
                        if "</details>" in content:
                            parts = content.split("</details>", 1)
                            full_thinking = parts[0] + "</details>"
                            full_answer = parts[1]
                        else:
                            full_thinking = content
                            full_answer = ""
                    else:
                        full_answer = content
                        full_thinking = ""
                elif phase == "thinking":
                    full_thinking += content
                elif phase == "usage":
                    tokens_used = content
                elif phase == "answer" or phase == "done" or not phase:
                    full_answer += content
                else:
                    full_answer += content
            elif isinstance(chunk, str):
                if chunk:
                    has_changed = True
                full_answer += chunk

            # Smart render throttle: capture data instantly but only rebuild
            # the expensive Markdown object at bounded intervals to avoid O(n²)
            # re-parsing on every single SSE chunk during long responses.
            if has_changed and (time.monotonic() - last_render_time) >= _RENDER_INTERVAL:
                _do_refresh(live)

        # Always draw the final frame
        if has_changed:
            _do_refresh(live)

    return full_answer


def get_user_input(prompt_text="You"):
    return Prompt.ask(f"\n[bold green]{prompt_text}[/bold green]")


def print_goodbye():
    console.print("\n[yellow]Goodbye![/yellow]\n", justify="left")
