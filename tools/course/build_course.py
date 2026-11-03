"""Build the experts-method course (Eyal 2026-11-03): one HTML fragment with inline (base64 WebP) charts.

  python tools/course/charts.py        # charts from app/data candles -> /workspace/course/img (needs matplotlib)
  python tools/course/backtest.py      # exploratory v7 backtest -> /workspace/course/bt_trades.json
  python tools/course/bt_table.py      # subset table -> /workspace/course/bt_table.json
  python tools/course/build_course.py  # -> app/data/course.json (the app page #/course, private bucket) + standalone HTML

Read-only teaching material: changes no rule, data the scanner uses, drawing or routine.
"""
import base64, io, json, os, re
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORK = Path(os.environ.get('COURSE_WORK', '/workspace/course'))
IMG = WORK / 'img'

def img64(name):
    im = Image.open(IMG / f'{name}.png').convert('RGB')
    b = io.BytesIO(); im.save(b, 'WEBP', quality=82, method=6)
    return 'data:image/webp;base64,' + base64.b64encode(b.getvalue()).decode()

def bt_tables():
    t = json.load(open(WORK / 'bt_table.json'))
    names = {'L': 'L: לימיט בראש האזור', 'C': 'C: אישור (סגירה שבועית מעל האזור, קנייה בפתיחה הבאה)'}
    out = []
    for v in ('L', 'C'):
        rows = ''.join(
            f"<tr><td>{g}</td><td class='n'>{s['n']}</td><td class='n'>{s['win']}%</td><td class='n'>{s['aw']:+.2f}</td><td class='n'>{s['al']:+.2f}</td>"
            f"<td class='n'><b>{s['E']:+.2f}R</b></td><td class='n'>{s['lo']:+.2f} – {s['hi']:+.2f}</td></tr>"
            for g, s in t[v] if s)
        out.append(f"<h3>{names[v]}</h3><div class='tbl'><table><tr><th>קבוצה</th><th>עסקאות</th><th>הצלחה</th><th>רווח ממוצע R</th><th>הפסד ממוצע R</th><th>תוחלת</th><th>רווח בר-סמך 95%</th></tr>{rows}</table></div>")
    return ''.join(out) + "<p class='src'>רווח בר-סמך: Bootstrap של 1,000 דגימות. עסקאות חופפות בזמן, ולכן הרווח האמיתי רחב יותר. \"פטיש\" = פטיש שבועי על האזור ב-12 השבועות שלפני הכניסה.</p>"

def stack_tables(html):
    """text tables (no numeric td.n cells) get class 'stk' + data-l labels: on phones each row becomes a card"""
    def one(m):
        t = m.group(0)
        if "class='n'" in t or 'class="n"' in t:
            return t
        heads = [re.sub(r'<[^>]+>', '', h) for h in re.findall(r'<th>(.*?)</th>', t)]
        def row(r):
            i = iter(heads)
            return re.sub(r'<td>', lambda _: f'<td data-l="{next(i, "")}">', r.group(0))
        t = re.sub(r'<tr>(?:(?!</tr>).)*?<td>.*?</tr>', row, t, flags=re.S)
        return t.replace('<table>', '<table class="stk">', 1)
    return re.sub(r'<table>.*?</table>', one, html, flags=re.S)

def build():
    html = ''.join((HERE / f).read_text() for f in ('content_a.html', 'content_b.html', 'content_c.html'))
    html = stack_tables(html.replace('{{bt_tables}}', bt_tables()))
    names = sorted(set(re.findall(r'\{\{img:(\w+)\}\}', html)))
    for n in names:
        html = html.replace('{{img:%s}}' % n, img64(n))
    css = (HERE / 'course.css').read_text()
    gen = datetime.now(timezone.utc).isoformat(timespec='seconds')
    doc = {'version': 1, 'generated_at': gen, 'charts': len(names), 'css': css, 'html': f'<div class="course" dir="rtl">{html}</div>'}
    out = REPO / 'app' / 'data' / 'course.json'
    out.write_text(json.dumps(doc, ensure_ascii=False))
    js = ("document.addEventListener('click',function(e){var a=e.target.closest('[data-goto]');if(!a)return;e.preventDefault();"
          "var m=document.getElementById(a.dataset.goto);if(m){m.open=true;m.scrollIntoView({behavior:'smooth',block:'start'});}});")
    page = (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>קורס שיטת המומחים</title><style>html,body{{margin:0;background:#131722;color:#d1d4dc;font:15px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans Hebrew",Arial,sans-serif}}{css}</style></head>'
            f'<body>{doc["html"]}<script>{js}</script></body></html>')
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'expert_method_course.html').write_text(page)
    print(out, out.stat().st_size, 'bytes,', len(names), 'charts')

if __name__ == '__main__':
    build()
