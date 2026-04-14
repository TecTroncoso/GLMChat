from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.live import Live
from rich.rule import Rule
import time

console = Console()


def print_status(message, style="white"):
    console.print(f"[{style}][[GLM]][/{style}] {message}", justify="left")


def print_response_start():
    console.print()
    console.print(Rule("[bold cyan]Response[/bold cyan]", style="cyan", align="left"))
    console.print()


from rich.console import Group
from rich.text import Text

def stream_live(content_generator):
    full_thinking = ""
    full_answer = ""
    last_update = 0.0
    tokens_used = None

    def build_render_group():
        import re
        elements = []
        
        if full_thinking:
            # Z.ai sends thinking inside <details> tags which rich.Markdown natively hides entirely.
            # We strip HTML tags from the thinking text so it renders properly in the terminal.
            clean_thinking = re.sub(r"<[^>]+>", "", full_thinking).strip()
            if clean_thinking:
                md_thinking = Markdown(clean_thinking, code_theme="monokai", justify="left")
                elements.append(Panel(md_thinking, title="[dim]Thinking...[/dim]", border_style="dim"))
                
        if full_answer:
            # Also remove dangling </details> tags that occasionally leak into the answer delta
            clean_answer = full_answer.replace("</details>", "").strip()
            elements.append(Markdown(clean_answer, code_theme="monokai", justify="left"))
            
        if not elements:
            return Text("")
            
        return Group(*elements)

    with Live(console=console, refresh_per_second=10) as live:
        for chunk in content_generator:
            if isinstance(chunk, dict):
                phase = chunk.get("phase")
                content = chunk.get("content", "")
                
                if phase == "thinking":
                    full_thinking += content
                elif phase == "usage":
                    tokens_used = content
                elif phase == "answer" or phase == "done" or not phase:
                    full_answer += content
                else:
                    full_answer += content
            elif isinstance(chunk, str):
                full_answer += chunk
                
            # Throttle markdown parsing and UI updating to ~10 FPS (every 0.1s)
            current_time = time.time()
            if current_time - last_update >= 0.1:
                renderable = build_render_group()
                title = f"[bold white]GLM[/bold white]"
                if tokens_used:
                    title += f" [dim](Tokens: {tokens_used})[/dim]"
                    
                panel = Panel(
                    renderable,
                    border_style="bright_cyan",
                    padding=(1, 2),
                    title=title,
                    title_align="left",
                )
                live.update(panel)
                last_update = current_time
                    
        # Ensure the final output is drawn
        renderable = build_render_group()
        if renderable:
            title = f"[bold white]GLM[/bold white]"
            if tokens_used:
                title += f" [dim](Tokens: {tokens_used})[/dim]"
                
            panel = Panel(
                renderable,
                border_style="bright_cyan",
                padding=(1, 2),
                title=title,
                title_align="left",
            )
            live.update(panel)

    return full_answer


def get_user_input(prompt_text="You"):
    return Prompt.ask(f"\n[bold green]{prompt_text}[/bold green]")


def print_goodbye():
    console.print("\n[yellow]Goodbye![/yellow]\n", justify="left")
