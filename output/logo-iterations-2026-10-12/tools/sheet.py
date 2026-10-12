"""Write an HTML review sheet for the icon variants. Usage: sheet.py SVG_DIR OUT_HTML title subtitle name=label ..."""
import sys
from pathlib import Path

svg_dir, out_html, title, subtitle, *cards = sys.argv[1:]
sizes = (16, 24, 32, 48, 64)


def card(name, label):
    note = ""
    if "|" in label:
        label, note = label.split("|", 1)
    src = f"{name}.svg"
    small = lambda theme: "".join(
        f'<figure><img src="{src}" width="{size}" height="{size}"><figcaption>{size}</figcaption></figure>'
        for size in sizes)
    return f"""
    <article>
      <h2>{name.split('-')[0]} · {label}</h2>
      <p class="note">{note}</p>
      <img class="hero" src="{src}" width="220" height="220">
      <div class="row light">{small('light')}</div>
      <div class="row dark">{small('dark')}</div>
    </article>"""


html = f"""<!doctype html><meta charset="utf-8"><title>{title}</title>
<style>
  body {{ margin: 0; padding: 40px; background: #F3EFE6; font: 14px/1.4 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; color: #26221C; }}
  h1 {{ margin: 0 0 6px; font-size: 26px; }}
  .sub {{ margin: 0 0 28px; color: #6B6257; }}
  main {{ display: flex; gap: 18px; align-items: stretch; }}
  article {{ background: #fff; border-radius: 16px; padding: 18px 18px 14px; width: 232px; flex: none; }}
  h2 {{ margin: 0 0 4px; font-size: 15px; }}
  .note {{ margin: 0 0 12px; color: #6B6257; font-size: 12px; min-height: 34px; }}
  .hero {{ display: block; width: 220px; height: 220px; margin: 0 auto 14px; }}
  .row {{ display: flex; align-items: flex-end; justify-content: space-between; padding: 12px 10px; border-radius: 10px; }}
  .row + .row {{ margin-top: 8px; }}
  .light {{ background: #F7F4EE; }}
  .dark {{ background: #23201B; color: #A89F93; }}
  figure {{ margin: 0; text-align: center; }}
  figcaption {{ font-size: 10px; color: #8A8176; margin-top: 4px; }}
  .dark figcaption {{ color: #8A8176; }}
  img {{ image-rendering: auto; display: block; }}
  footer {{ margin-top: 24px; color: #6B6257; font-size: 13px; max-width: 900px; }}
</style>
<h1>{title}</h1>
<p class="sub">{subtitle}</p>
<main>{''.join(card(*entry.split('=', 1)) for entry in cards)}</main>
<footer>Small samples are the SVG rendered straight to the box size on light and dark grounds.</footer>
"""
Path(out_html).write_text(html)
