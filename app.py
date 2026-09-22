"""Run: python app.py. Open http://127.0.0.1:8765 . No pip install required."""
import argparse
import csv
import html
import io
import json
import re

# Use the Windows certificate store when truststore is installed. This fixes
# school/VPN/antivirus HTTPS inspection without disabling certificate checks.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import pmc
import hashlib
import secrets
import tempfile
import threading
import socket
import xml.etree.ElementTree as ET
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from porter import stem
from engine import SearchEngine, TOKEN, tokens, terms, parse_xml

ROOT = Path(__file__).resolve().parent

def esc(value):
    return html.escape(str(value), quote=True)

def highlight(text, query):
    wanted = set(stem(t) for t in tokens(query))
    out, end = [], 0
    for m in TOKEN.finditer(text):
        if stem(m.group()) in wanted:
            out += [esc(text[end:m.start()]), '<mark>' + esc(m.group()) + '</mark>']
            end = m.end()
    return ''.join(out) + esc(text[end:])

def snippet(doc, query):
    wanted = set(stem(t) for t in tokens(query))
    match = next((m for m in TOKEN.finditer(doc.text) if stem(m.group()) in wanted), None)
    start = max(0, match.start()-100) if match else 0
    end = min(len(doc.text), start+420)
    return ('…' if start else '') + highlight(doc.text[start:end], query) + ('…' if end<len(doc.text) else '')


def document_term_counts(doc, query):
    """Return each distinct query stem and its abstract/body/full counts."""
    query_terms = list(dict.fromkeys(stem(t) for t in tokens(query)))
    return [
        (term,
         doc.abstract_stem_tf[term],
         doc.body_stem_tf[term],
         doc.full_stem_tf[term])
        for term in query_terms
    ]


def term_counts_html(doc, query):
    counts = document_term_counts(doc, query)
    if not counts:
        return ''
    abstract_total = sum(abstract for _, abstract, _, _ in counts)
    body_total = sum(body for _, _, body, _ in counts)
    full_total = sum(full for _, _, _, full in counts)
    rows = ''.join(
        f'<tr><td>{esc(term)}</td><td>{abstract:,} 次</td>'
        f'<td>{body:,} 次</td><td>{full:,} 次</td></tr>'
        for term, abstract, body, full in counts
    )
    return (
        '<details class="term-counts" open>'
        '<summary>這篇文章的搜尋詞分布：'
        f'摘要 {abstract_total:,} 次 · 正文 {body_total:,} 次 · 全文 {full_total:,} 次</summary>'
        '<div class="scroll"><table>'
        '<tr><th>搜尋詞</th><th>摘要次數</th><th>正文次數</th><th>全文總次數</th></tr>'
        f'{rows}</table></div>'
        '<p class="muted">AND／OR／PHRASE 依摘要＋正文判斷；下方 Words、Sentences、Characters 只統計摘要。</p>'
        '</details>'
    )

STYLE = '''
:root{color-scheme:light;--ink:#122d3d;--muted:#526a79;--teal:#00796f}*{box-sizing:border-box}
body{margin:0;background:#f2f6f8;color:var(--ink);font:16px/1.65 system-ui,"Microsoft JhengHei",sans-serif}
header{background:#102e3f;color:white;padding:30px max(5vw,20px)}.header-layout{max-width:1500px;margin:auto;display:grid;grid-template-columns:minmax(310px,1fr) minmax(620px,1.7fr);gap:36px;align-items:center}header h1{margin:6px 0;font-size:40px}
header p{margin:6px 0;color:#c0d9e2;font-size:20px}.eyebrow{letter-spacing:2px;font-size:16px;color:#8cddd0}.home-link{color:white;text-decoration:none}.home-link:hover,.home-link:focus{text-decoration:underline}
main{max-width:1500px;margin:auto;padding:26px 20px 60px}.panel,.card{background:white;border:1px solid #dbe5e9;border-radius:14px;padding:22px;margin:0 0 18px}
.header-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.header-metrics .metric{min-width:0;background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.2);padding:15px 16px;border-radius:12px}.header-metrics small{display:block;color:#bcd6df;white-space:nowrap}.header-metrics b{display:block;color:white;font-size:27px;line-height:1.25;margin-top:4px}.muted,small{color:var(--muted)}
form{display:flex;gap:12px;align-items:end;flex-wrap:wrap}label{display:block;font-size:14px}input,select,button{font:inherit;padding:11px;border:1px solid #b9cbd4;border-radius:7px}input{width:100%}.query{flex:1;min-width:220px}button{background:var(--teal);color:white;cursor:pointer;border-color:var(--teal)}a{color:#00736c}h2{font-size:22px;margin:0 0 12px}h3{font-size:19px;margin:5px 0 8px}.row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.chip{font-size:12px;background:#e6f4f2;color:#126f67;padding:3px 9px;border-radius:16px;display:inline-block}.stats{display:flex;flex-wrap:wrap;gap:16px;color:var(--muted);font-size:14px}mark{background:#ffe29a;padding:0 2px}pre{white-space:pre-wrap;word-break:break-word;font:inherit;max-height:560px;overflow:auto}summary{cursor:pointer;font-weight:600}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #dbe5e9;padding:9px}th{background:#edf4f6}.bar{height:8px;background:#e6f0f2;border-radius:4px;margin-top:10px}.bar span{display:block;height:100%;background:var(--teal);border-radius:4px}.warning{background:#fff3d8;padding:14px;border-radius:8px}code{background:#edf2f4;padding:2px 5px}footer{margin-top:30px;font-size:13px;color:var(--muted)}.scroll{overflow-x:auto}@media(max-width:650px){.metrics{grid-template-columns:repeat(2,1fr)}header h1{font-size:25px}}
.workspace{display:grid;grid-template-columns:340px minmax(0,1fr);gap:24px;align-items:start}
.sidebar{min-width:0}.results-pane{min-width:0}.sidebar .panel{padding:18px}.sidebar h2{font-size:19px}
.sidebar form{align-items:stretch}.sidebar .query{flex-basis:100%;min-width:0}.sidebar button{width:100%}
.sidebar .card{padding:14px}.sidebar h3{font-size:16px;overflow-wrap:anywhere}.sidebar .row{display:block}
.library-item{border-top:1px solid #dbe5e9;padding:14px 0;overflow-wrap:anywhere}.library-item .stats{font-size:12px;gap:5px}
.library-item>a{font-weight:600;font-size:14px}.sidebar .muted{font-size:13px}.results-pane .card h3{overflow-wrap:anywhere}
.library-filter{margin:8px 0 4px}.delete-form{margin-top:9px}.sidebar .delete-form button{width:auto;background:#b42318;border-color:#b42318;padding:6px 11px;font-size:13px}.delete-form button:hover,.delete-form button:focus{background:#8f1d14}.library-item[hidden]{display:none}
.term-counts{margin:14px 0;padding:12px 14px;background:#f5faf9;border:1px solid #cfe4df;border-radius:9px}.term-counts table{margin-top:8px}.term-counts th,.term-counts td{padding:6px 8px}
.page-nav{max-width:1500px;margin:24px auto 0;display:flex;gap:10px;flex-wrap:wrap}.page-nav a{color:#d7eeef;text-decoration:none;border:1px solid #52717e;border-radius:9px;padding:9px 20px;font-weight:600}.page-nav a[aria-current="page"]{background:#e6f4f2;color:#125f59;border-color:#e6f4f2}.page-nav a:hover{background:#244b5b;color:white}.page-nav a:focus-visible{outline:3px solid #8cddd0;outline-offset:3px}.management .library-item{padding:20px 0}.management .library-item>a{font-size:19px}.management .delete-form button{background:#b42318;border-color:#b42318;padding:6px 12px;font-size:14px}.management input[type=file]{min-width:0;max-width:100%}.search-workspace{grid-template-columns:260px minmax(0,1fr)}
@media(max-width:1100px){.header-layout{grid-template-columns:1fr}.header-metrics{grid-template-columns:repeat(4,1fr)}}
@media(max-width:950px){.workspace{grid-template-columns:290px minmax(0,1fr)}}
@media(max-width:720px){.workspace{grid-template-columns:1fr}.sidebar .library-list{max-height:350px;overflow:auto}main{padding:18px 12px}header h1{font-size:32px}.eyebrow{font-size:14px}header p{font-size:17px}.header-metrics{grid-template-columns:repeat(2,1fr)}.header-metrics b{font-size:24px}}
'''

def page(engine, params, upload_token="", notice="", pmc_html="", management=False):
    number = lambda doc: f"{engine.numbers[doc.id]:03d}"
    query = params.get('q', [''])[0][:500]
    selected = params.get('doc', [''])[0]
    selected_doc = engine.docs.get(selected)
    mode = params.get('mode', ['AND'])[0]
    if mode not in {'AND','OR','PHRASE'}:
        mode = 'AND'
    started = time.perf_counter()
    results, active_terms = engine.search(query, mode, selected if selected_doc else None)
    elapsed = (time.perf_counter()-started)*1000
    total_words = sum(d.counts['words'] for d in engine.docs.values())
    total_sentences = sum(d.counts['sentences'] for d in engine.docs.values())
    metrics = ''.join(f'<div class="metric"><small>{label}</small><b>{value:,}</b></div>' for label,value in [('全文文件',len(engine.docs)),('摘要單字總數',total_words),('摘要句子總數',total_sentences),('全文索引詞種類',len(engine.index))])
    options = ''.join(f'<option value="{v}" {"selected" if mode==v else ""}>{label}</option>' for v,label in [('AND','AND · 所有關鍵字'),('OR','OR · 任一關鍵字'),('PHRASE','PHRASE · 連續詞組')])
    scope_input = f'<input type="hidden" name="doc" value="{esc(selected)}">' if selected_doc else ''
    scope_title = f'只搜尋文章 {number(selected_doc)}' if selected_doc else '搜尋全部文獻'
    scope_note = (f'目前只比對「{esc(selected_doc.title)}」。<a href="/">回到全部文章搜尋</a>'
                  if selected_doc else '目前會搜尋文件集中的全部文章。可到「PMID查詢/上傳」點選已有文章，改為單篇搜尋。')
    content = f'''<section class="panel search-panel"><div class="row"><h2>{scope_title}</h2>{'<span class="chip">單篇模式</span>' if selected_doc else '<span class="chip">全部文章模式</span>'}</div>
<form action="/" method="get">{scope_input}<div class="query"><label for="q">輸入英文關鍵字</label><input id="q" name="q" value="{esc(query)}" placeholder="例如 cancer 或 gene expression" maxlength="500"></div><div><label for="mode">比對方式</label><select id="mode" name="mode">{options}</select></div><button>搜尋</button></form>
<p class="muted">{scope_note}<br>檢索摘要與正文，不檢索標題。AND / OR 忽略常見停用詞；PHRASE 保留停用詞，依連續詞幹順序比對。所有模式皆使用 Porter stemming。大小寫不影響結果。</p></section>'''
    if notice:
        content += '<section class="panel" role="status"><h2>操作結果</h2><pre>'+esc(notice)+'</pre></section>'
    main_content = content
    content = ''
    pmid_value = params.get('pmid', [''])[0][:40]
    trash_folder = engine.folder / 'trash'
    try:
        trash_files = sorted(
            (p.name for p in trash_folder.iterdir()
             if p.is_file() and p.suffix.lower() in {'.xml', '.nxml'}),
            reverse=True
        )
    except OSError:
        trash_files = []
    content += '<section class="panel"><div class="row"><h2>使用 PMID 查詢文章</h2><a href="https://pubmed.ncbi.nlm.nih.gov/" target="_blank" rel="noopener">前往 PubMed 搜尋論文 ↗</a></div><form action="/pmc" method="get" data-wait="正在向 NCBI 查詢，請稍候…"><div class="query"><label for="pmid">輸入 PMID</label><input id="pmid" name="pmid" value="'+esc(pmid_value)+'" placeholder="例如 42724776" maxlength="40" inputmode="numeric" required></div><button>查詢文章與 XML</button></form><p class="muted">系統會先把 PMID 轉成 PMCID，再取得可下載的 PMC 全文 XML。不是每個 PMID 都有對應的 PMC 全文；本地關鍵字搜尋只查已匯入的文章。</p>'+pmc_html+'</section>'
    content += '<section class="panel"><h2>上傳新文章</h2><form action="/upload" method="post" enctype="multipart/form-data"><input type="hidden" name="token" value="'+esc(upload_token)+'"><div class="query"><label for="files">選擇 PMC 全文 XML / NXML（可多選）</label><input id="files" name="files" type="file" accept=".xml,.nxml" multiple required></div><button>上傳並加入文件集</button></form><p class="muted">每檔最多 20 MB，每次最多 10 個檔案、合計最多 40 MB。上傳後立即可搜尋，並保留在 data 資料夾。PDF、Word 和只有摘要的 XML 不適用。</p></section>'
    import_panels = content
    content = ''
    deleted_items = ''.join('<li>'+esc(name)+'</li>' for name in trash_files[:30])
    deleted_more = f'<p class="muted">另外還有 {len(trash_files)-30} 個檔案未列出。</p>' if len(trash_files) > 30 else ''
    content += ('<details class="panel"><summary>已刪除檔案 · '+str(len(trash_files))+' 個</summary>'
                '<p>檔案保存在專案的 <code>data/trash</code> 資料夾。網站不會永久刪除 XML。</p>'
                + ('<ul>'+deleted_items+'</ul>' if deleted_items else '<p class="muted">目前沒有已刪除的 XML。</p>')
                + deleted_more + '</details>')
    content += '<details class="panel"><summary>AND 和 OR 差在哪？</summary><p>搜尋 cancer treatment：AND 要在同篇文章的摘要＋正文同時包含兩詞，不必相鄰；OR 包含任一詞即可。要找連續詞組請選 PHRASE。</p><p>文章刪除後會重新連續編號；搜尋排名依 BM25 分數排列。</p></details>'
    sidebar = content
    content = ''
    if engine.errors:
        content += '<details class="panel"><summary>讀取提示（'+str(len(engine.errors))+'）</summary><ul>'+''.join('<li>'+esc(e)+'</li>' for e in engine.errors)+'</ul></details>'
    if not engine.docs:
        content += '<p class="warning">尚無可用全文 XML。請前往 <a href="/manage">PMID查詢/上傳</a> 加入文章。</p>'
    diagnostics = content
    content = main_content + diagnostics
    if selected:
        doc = selected_doc
        if doc:
            content += f'<article class="panel"><span class="chip">文件詳情 · {esc(doc.id)}</span><h2>{number(doc)}. {esc(doc.title)}</h2><p>{esc(doc.journal)}</p>'
            content += '<div class="scroll"><table><tr><th>摘要統計</th><th>數量</th></tr>'
            for k,label in [('words','Words'),('sentences','Sentences'),('characters','Characters（含空白）')]:
                content += f'<tr><td>{label}</td><td>{doc.counts[k]:,}</td></tr>'
            content += '</table></div><h3>摘要</h3><pre>'+highlight(doc.abstract or '此文章無摘要。',query)+'</pre>'
            if re.fullmatch(r'PMC[1-9]\d*', doc.id):
                content += '<p><a href="https://pmc.ncbi.nlm.nih.gov/articles/'+esc(doc.id)+'/" target="_blank" rel="noopener">前往 PMC 查看原文 ↗</a></p>'
            content += '</article>'
        else:
            content += '<p class="warning">找不到指定文件。</p>'
    if query.strip():
        result_scope = f'文章 {number(selected_doc)}' if selected_doc else '全部文章'
        content += f'<div class="row"><h2>搜尋結果 · {len(results)} 篇</h2><span class="muted">範圍：{result_scope} · {elapsed:.3f} ms · BM25 排序</span></div>'
        raw_terms = tokens(query)
        unique_terms = list(dict.fromkeys(stem(t) for t in raw_terms))
        content += '<section class="panel"><h3>查詢分析與總數</h3><p>斷詞結果（'+str(len(raw_terms))+' 個詞）：'+(' '.join('<span class="chip">'+esc(t)+'</span>' for t in raw_terms) or '無')+'</p>'
        searched_total = 1 if selected_doc else len(engine.docs)
        content += f'<p><b>命中文章總數：{len(results)} 篇</b> ／ 本次搜尋範圍：{searched_total} 篇 ／ 本地文件總數：{len(engine.docs)} 篇</p>'
        content += '<p class="stats">'+ ' · '.join(f'{label}：{sum(d.counts[key] for d,_ in results):,}' for key,label in [('characters','命中文件摘要字元總數'),('words','摘要單字總數'),('sentences','摘要句子總數')]) + '</p>'
        content += '<div class="scroll"><table><tr><th>搜尋詞</th><th>比對處理</th><th>全文含此詞篇數</th><th>摘要次數</th><th>正文次數</th><th>全文總次數</th></tr>'
        for term in unique_terms:
            frequencies = {d.id: d.full_stem_tf[term] for d in engine.docs.values()}
            status = '參與詞組比對' if mode == 'PHRASE' else ('有效搜尋詞' if term in active_terms else '停用詞，忽略')
            abstract_total = sum(d.abstract_stem_tf[term] for d,_ in results)
            body_total = sum(d.body_stem_tf[term] for d,_ in results)
            full_total = sum(d.full_stem_tf[term] for d,_ in results)
            content += f'<tr><td>{esc(term)}</td><td>{status}</td><td>{sum(v>0 for v in frequencies.values())}</td><td>{abstract_total:,}</td><td>{body_total:,}</td><td>{full_total:,}</td></tr>'
        content += '</table></div><p class="muted">搜尋與全文總次數涵蓋摘要＋正文，不包含標題。以空白與一般標點斷開英文詞，保留 HIV-1 這類連字號詞；出現次數按 Porter 詞幹合併（testing、tested → test），不是詞組次數。Words、Sentences、Characters 仍只統計摘要。</p></section>'
        content += '<p class="muted">有效索引詞：'+esc(', '.join(active_terms) or '無（PHRASE 仍可比對停用詞詞組）')+'</p>'
        if results:
            export_params = {'q':query,'mode':mode}
            if selected_doc:
                export_params['doc'] = selected
            content += f'<p><a href="/export.csv?{esc(urlencode(export_params))}">下載這次搜尋結果 CSV</a></p>'
        else:
            content += '<p class="panel">沒有符合的文件。可嘗試較少關鍵字、改用 OR，或查看下方文件的用詞。僅含停用詞的 AND / OR 查詢不會回傳結果。</p>'
        max_score = results[0][1] if results else 0
        for rank,(doc,score) in enumerate(results[:100],1):
            link = '/?'+urlencode({'q':query,'mode':mode,'doc':doc.id})
            content += f'<article class="card"><div class="row"><span class="chip">搜尋排名 {rank} · 文章 {number(doc)} · {esc(doc.id)}</span><small>BM25 {score:.4f}</small></div><h3><a href="{esc(link)}">{number(doc)}. {esc(doc.title)}</a></h3>{document_links(doc)}<p>{snippet(doc,query)}</p>{term_counts_html(doc,query)}<div class="stats"><span>摘要 {doc.counts["words"]:,} words</span><span>{doc.counts["sentences"]:,} sentences</span><span>{doc.counts["characters"]:,} characters</span></div><div class="bar" aria-label="相對最高分"><span style="width:{100*score/max_score if max_score else 0:.2f}%"></span></div></article>'
        if len(results)>100:
            content += '<p>畫面顯示前 100 篇；CSV 含全部結果。</p>'
    results_content = content
    content = '<section class="panel"><h2>已有文章 · '+str(len(engine.docs))+' 篇</h2><label for="library-filter">搜尋已載入文章</label><input class="library-filter" id="library-filter" type="search" placeholder="輸入標題、PMCID 或編號" autocomplete="off"><p id="library-filter-status" class="muted" aria-live="polite">顯示 '+str(min(len(engine.docs),200))+' 篇</p><p><a href="/export.csv">下載全部文件統計 CSV</a></p><div class="library-list">'
    for doc in sorted(engine.docs.values(), key=lambda d: engine.numbers[d.id])[:200]:
        link = '/?'+urlencode({'doc':doc.id})
        same_file_count = sum(other.filename == doc.filename for other in engine.docs.values())
        confirmation = (f'確定要從文件集移除「{doc.title}」嗎？原始 XML 會移到 data/trash，可手動救回。'
                        if same_file_count == 1 else
                        f'這個 XML 內含 {same_file_count} 篇文章。刪除會一起移除它們，確定繼續嗎？原始 XML 會移到 data/trash。')
        searchable = f'{number(doc)} {doc.id} {doc.title}'.casefold()
        delete_form = ('<form class="delete-form" action="/delete" method="post" data-confirm="'+esc(confirmation)+'">'
                       '<input type="hidden" name="token" value="'+esc(upload_token)+'">'
                       '<input type="hidden" name="doc" value="'+esc(doc.id)+'">'
                       '<button type="submit">刪除文章</button></form>')
        content += f'<div class="library-item" data-search="{esc(searchable)}"><a href="{esc(link)}">{number(doc)}. {esc(doc.title)}</a><div class="muted">{esc(doc.id)}</div><div class="stats">摘要：{doc.counts["words"]:,} words · {doc.counts["sentences"]:,} sentences · {doc.counts["characters"]:,} characters</div>{document_links(doc)}{delete_form}</div>'
    content += '</div><p class="muted">最多列出 200 篇，CSV 包含全部。網站上傳／匯入立即更新；手動放入 data 後需重啟。</p></section>'
    if not query.strip() and not selected:
        results_content += '<section class="panel"><h2>開始探索你的文章</h2><p>在上方輸入英文關鍵字，這裡會列出符合的文章、斷詞與摘要統計。要挑選單篇文章，請前往 <a href="/manage">PMID查詢/上傳</a>，點選已有文章的標題。</p></section>'
    if management:
        notice_html = '<section class="panel" role="status"><h2>操作結果</h2><pre>'+esc(notice)+'</pre></section>' if notice else ''
        content = '<div class="workspace management"><aside class="sidebar" aria-label="查詢與上傳">'+import_panels+'</aside><section class="results-pane" aria-label="已有文章">'+notice_html+diagnostics+content+'</section></div>'
    else:
        content = '<div class="workspace search-workspace"><aside class="sidebar" aria-label="說明與已刪除檔案">'+sidebar+'</aside><section class="results-pane" aria-label="搜尋與文章結果">'+results_content+'</section></div>'
    content += f'<footer>Biomedical IR · 課程作業工具 · 建立索引 {engine.build_ms:.2f} ms<br>資料來源：NIH / NLM PubMed Central。隨附資料為下載時快照，可能不是最新版本；本工具未受 NIH / NLM 背書。<br>Words、Sentences、Characters 只統計摘要；搜尋詞分布分別列出摘要、正文與全文。關鍵字檢索涵蓋摘要與正文，不包含標題。句數採規則估計。</footer>'
    navigation = '<nav class="page-nav" aria-label="主要導覽">'+''.join('<a href="'+url+'"'+(' aria-current="page"' if active else '')+'>'+label+'</a>' for url,label,active in [('/', '文獻搜尋', not management),('/manage', 'PMID查詢/上傳', management)])+'</nav>'
    header = '<header><div class="header-layout"><div class="header-copy"><div class="eyebrow">BIOMEDICAL INFORMATION RETRIEVAL</div><h1><a class="home-link" href="/" title="回到主畫面">生醫文獻全文檢索</a></h1></div><div class="header-metrics" aria-label="文件集統計">'+metrics+'</div></div>'+navigation+'</header>'
    return '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Biomedical IR · 文獻搜尋</title><style>'+STYLE+'</style>'+header+'<main>'+content+'</main>'+WAIT_SCRIPT+'</html>'


WAIT_SCRIPT = """<script>
for (const form of document.querySelectorAll('form[data-wait]')) {
 form.addEventListener('submit', () => {
  const note = document.createElement('p'); note.setAttribute('role','status');
  note.textContent = form.dataset.wait; form.after(note);
  const button = form.querySelector('button'); if(button) button.disabled=true;
 });
}
for (const form of document.querySelectorAll('form[data-confirm]')) {
 form.addEventListener('submit', event => {
  if (!window.confirm(form.dataset.confirm)) event.preventDefault();
 });
}
const libraryFilter = document.querySelector('#library-filter');
const libraryStatus = document.querySelector('#library-filter-status');
if (libraryFilter) {
 const items = [...document.querySelectorAll('.library-item')];
 const applyLibraryFilter = () => {
  const words = libraryFilter.value.toLocaleLowerCase().trim().split(/\\s+/).filter(Boolean);
  let visible = 0;
  for (const item of items) {
   const haystack = item.dataset.search || '';
   const matched = words.every(word => haystack.includes(word));
   item.hidden = !matched;
   if (matched) visible += 1;
  }
  if (libraryStatus) libraryStatus.textContent = words.length ? `找到 ${visible} 篇` : `顯示 ${visible} 篇`;
 };
 libraryFilter.addEventListener('input', applyLibraryFilter);
}
window.addEventListener('pageshow',()=>document.querySelectorAll('form[data-wait] button').forEach(b=>b.disabled=false));
</script>"""


def document_links(doc):
    links = '<a href="/document.xml?'+esc(urlencode({'doc':doc.id}))+'">下載 XML</a>'
    if re.fullmatch(r'PMC[1-9]\d*',doc.id):
        links += ' · <a href="https://pmc.ncbi.nlm.nih.gov/articles/'+esc(doc.id)+'/" target="_blank" rel="noopener">PMC 原文 ↗</a>'
    return '<p class="stats">'+links+'</p>'


def pmc_cards(pmid, pmcid, versions, errors, token, engine):
    out = '<h3>查詢總數：'+str(int(bool(versions)))+' 篇文章 · 可下載版本 '+str(len(versions))+' 個</h3>'
    out += '<p><b>PMID：'+esc(pmid)+'</b> → <b>PMCID：'+esc(pmcid)+'</b> · <a href="https://pubmed.ncbi.nlm.nih.gov/'+esc(pmid)+'/" target="_blank" rel="noopener">查看 PubMed ↗</a></p>'
    out += '<p class="muted">以下為官方資料服務中可取得的 XML 版本；版本號不保證代表最新正式出版稿。</p>'
    for meta in versions:
        version = str(meta['version'])
        query = esc(urlencode({'pmcid':pmcid,'version':version}))
        out += '<article class="card"><h3>'+esc(meta.get('title') or pmcid)+'</h3><p>'+esc(meta.get('citation',''))+'</p><p>'+esc(pmcid)+' · 版本 '+esc(version)+' · '+('作者稿' if meta.get('is_manuscript') in (True,'yes') else '非作者稿')+' · 授權 '+esc(meta.get('license_code','未標示'))+'</p>'
        if meta.get('is_retracted') in (True,'yes'):
            out += '<p class="warning">官方標示此文章已撤稿。</p>'
        out += '<p><a href="https://pmc.ncbi.nlm.nih.gov/articles/'+pmcid+'/" target="_blank" rel="noopener">前往 PMC 看文章 ↗</a> · <a href="/pmc.xml?'+query+'">下載官方 XML</a></p>'
        if pmcid in engine.docs:
            out += '<p>本站已有這篇文章。<a href="/?'+esc(urlencode({'doc':pmcid}))+'">查看本站文章與統計</a></p>'
        else:
            out += '<form action="/pmc-import" method="post" data-wait="正在下載 XML 並建立索引，請稍候…"><input type="hidden" name="token" value="'+esc(token)+'"><input type="hidden" name="pmcid" value="'+pmcid+'"><input type="hidden" name="version" value="'+esc(version)+'"><button>下載並加入文件集</button></form>'
        out += '</article>'
    for error in errors:
        out += '<p class="warning">'+esc(error)+'</p>'
    return out


def make_handler(engine):
    state = {'engine': engine}
    upload_lock = threading.Lock()
    upload_token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            engine = state['engine']
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            attachment = None
            if url.path in {'/', '/manage'}:
                data = page(engine,params,upload_token,management=url.path == '/manage').encode('utf-8')
                content_type = 'text/html; charset=utf-8'
            elif url.path == '/pmc':
                value = params.get('pmid',[''])[0]
                try:
                    pmid, pmcid = pmc.resolve_pmid(value)
                    versions, errors = pmc.lookup(pmcid)
                    extra = pmc_cards(pmid,pmcid,versions,errors,upload_token,engine)
                except (ValueError, ET.ParseError, OSError) as exc:
                    extra = '<p class="warning">'+esc(exc)+'</p>'
                    if re.fullmatch(r'(?:PMID\s*[:#]?\s*)?[1-9]\d*',value.strip(),re.I):
                        pmid_link = re.sub(r'\D','',value)
                        extra += '<a href="https://pubmed.ncbi.nlm.nih.gov/'+esc(pmid_link)+'/" target="_blank" rel="noopener">前往 PubMed 核對文章 ↗</a>'
                data = page(engine,params,upload_token,pmc_html=extra,management=True).encode('utf-8')
                content_type = 'text/html; charset=utf-8'
            elif url.path == '/pmc.xml':
                try:
                    data, meta = pmc.article_xml(params.get('pmcid',[''])[0],params.get('version',[''])[0])
                    attachment = f'{meta["pmcid"]}.{meta["version"]}.xml'
                    content_type = 'application/xml; charset=utf-8'
                except (ValueError, ET.ParseError, OSError) as exc:
                    self.render_notice(str(exc),400); return
            elif url.path == '/document.xml':
                doc = engine.docs.get(params.get('doc',[''])[0])
                if not doc:
                    self.send_error(404); return
                try:
                    data = (engine.folder/doc.filename).read_bytes()
                except OSError:
                    self.render_notice('XML 檔案已被移動或刪除。',404); return
                attachment = f'article-{engine.numbers[doc.id]:03d}.xml'
                content_type = 'application/xml; charset=utf-8'
            elif url.path == '/export.csv':
                q = params.get('q',[''])[0][:500]
                mode = params.get('mode',['AND'])[0]
                if mode not in {'AND','OR','PHRASE'}:
                    self.send_error(400,'Unknown mode'); return
                scoped_doc = params.get('doc',[''])[0] or None
                rows = engine.search(q,mode,scoped_doc)[0] if q.strip() else [(d,0) for d in engine.docs.values()]
                f = io.StringIO(newline='')
                writer = csv.writer(f)
                writer.writerow(['number','id','title','BM25','characters','characters_no_space','words','sentences','indexed_terms','unique_terms','filename'])
                def safe(v):
                    # Prevent spreadsheet formula evaluation for externally supplied text.
                    return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
                for d,s in rows:
                    writer.writerow([engine.numbers[d.id],safe(d.id),safe(d.title),round(s,6),*d.counts.values(),safe(d.filename)])
                data = ('\ufeff'+f.getvalue()).encode('utf-8')
                content_type = 'text/csv; charset=utf-8'
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff')
            if attachment:
                self.send_header('Content-Disposition',f'attachment; filename="{attachment}"')
            if url.path.endswith('.csv'):
                self.send_header('Content-Disposition','attachment; filename="results.csv"')
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            post_path = urlsplit(self.path).path
            if post_path == '/pmc-import':
                self.import_pmc(); return
            if post_path == '/delete':
                self.delete_document(); return
            if post_path != '/upload':
                self.send_error(404); return
            limit = 42 * 1024 * 1024  # 40 MB file payload plus multipart envelope.
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400, 'Invalid Content-Length'); return
            if length <= 0 or length > limit or self.headers.get('Transfer-Encoding'):
                self.send_error(413, 'Upload is too large or has no valid length'); return
            content_type = self.headers.get('Content-Type', '')
            if not content_type.lower().startswith('multipart/form-data'):
                self.send_error(400, 'Expected multipart/form-data'); return
            self.connection.settimeout(30)
            try:
                raw = self.rfile.read(length)
            except (socket.timeout, OSError):
                self.send_error(408, 'Upload timed out'); return
            if len(raw) != length:
                self.send_error(400, 'Incomplete upload'); return
            message = BytesParser(policy=policy.default).parsebytes(
                ('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode('utf-8')+raw)
            if not message.is_multipart():
                self.send_error(400, 'Invalid multipart boundary'); return
            parts = list(message.iter_parts())
            supplied = next((p.get_payload(decode=True) for p in parts
                             if p.get_param('name', header='content-disposition') == 'token'), b'')
            if not secrets.compare_digest(supplied or b'', upload_token.encode()):
                self.send_error(403, 'Reload the page and try uploading again'); return
            files = [p for p in parts if p.get_param('name', header='content-disposition') == 'files'
                     and p.get_filename()]
            if not 1 <= len(files) <= 10:
                self.send_error(400, 'Select between 1 and 10 files'); return
            payloads = [(p.get_filename(), p.get_payload(decode=True) or b'') for p in files]
            if sum(len(raw) for _,raw in payloads) > 40*1024*1024:
                self.send_error(413, 'Total file size exceeds 40 MB'); return
            messages = []
            # Serialize writes; GET requests always read a complete immutable index snapshot.
            with upload_lock:
                for filename, raw in payloads:
                    basename = filename.replace('\\', '/').split('/')[-1]
                    suffix = Path(basename).suffix.lower()
                    if suffix not in {'.xml', '.nxml'}:
                        messages.append(f'{basename}: 不支援此格式，請選 XML / NXML。'); continue
                    if not raw or len(raw) > 20*1024*1024:
                        messages.append(f'{basename}: 檔案為空或超過 20 MB。'); continue
                    current = state['engine']
                    # Ignore client path entirely. Content-derived names prevent overwrites.
                    digest = hashlib.sha256(raw).hexdigest()
                    target = current.folder / ('upload_'+digest+'.xml')
                    if target.exists():
                        messages.append(f'{basename}: 相同內容已存在，未重複加入。'); continue
                    try:
                        with tempfile.TemporaryDirectory(dir=current.folder) as folder:
                            candidate = Path(folder)/target.name
                            candidate.write_bytes(raw)
                            docs = parse_xml(candidate)
                            ids = [d.id for d in docs]
                            duplicate = set(ids) & set(current.docs)
                            if duplicate or len(set(ids)) != len(ids):
                                messages.append(f'{basename}: 文件 ID 重複，整個檔案略過。'); continue
                            candidate.replace(target)
                        try:
                            updated = SearchEngine(current.folder)
                            if not all(doc_id in updated.docs for doc_id in ids):
                                raise ValueError('New document was not indexed')
                        except Exception:
                            target.unlink(missing_ok=True)
                            raise
                        state['engine'] = updated
                        numbers = ', '.join(f'{updated.numbers[i]:03d}' for i in ids)
                        messages.append(f'{basename}: 已加入 {len(docs)} 篇文章（編號 {numbers}），可立即搜尋與查看統計。')
                    except (ValueError, ET.ParseError, OSError) as exc:
                        messages.append(f'{basename}: 上傳失敗，請確認是含正文的有效 PMC JATS XML。原因：{exc}')
                engine = state['engine']
            data = page(engine, {}, upload_token, '\n'.join(messages),management=True).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(data)
        def render_notice(self, text, status=200, params=None):
            management = urlsplit(self.path).path in {'/upload', '/delete', '/pmc-import', '/pmc.xml'}
            data = page(state['engine'],params or {},upload_token,text,management=management).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def delete_document(self):
            """Remove one XML-backed item from the active set without destroying it."""
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('刪除請求格式不正確。')
                values = parse_qs(self.rfile.read(length).decode('utf-8'))
                token = values.get('token', [''])[0]
                if not secrets.compare_digest(token.encode(), upload_token.encode()):
                    self.render_notice('頁面已過期，請重新整理後再刪除。', 403); return
                doc_id = values.get('doc', [''])[0]
                with upload_lock:
                    current = state['engine']
                    doc = current.docs.get(doc_id)
                    if doc is None:
                        self.render_notice('找不到這篇文章，可能已經被移除。', 404); return
                    target = (current.folder / doc.filename).resolve()
                    if target.parent != current.folder or not target.is_file():
                        raise ValueError('找不到安全的原始 XML 檔案。')
                    removed_ids = [d.id for d in current.docs.values() if d.filename == doc.filename]
                    trash = current.folder / 'trash'
                    trash.mkdir(exist_ok=True)
                    stamp = time.strftime('%Y%m%d-%H%M%S')
                    destination = trash / f'{stamp}_{target.name}'
                    suffix = 2
                    while destination.exists():
                        destination = trash / f'{stamp}_{suffix}_{target.name}'
                        suffix += 1
                    sidecar = target.with_suffix('.metadata.json')
                    number_path = current.folder / 'document_numbers.json'
                    original_numbers = (number_path.read_bytes()
                                        if number_path.exists() else None)
                    moved = []
                    try:
                        target.replace(destination)
                        moved.append((target, destination))
                        if sidecar.is_file():
                            sidecar_destination = trash / (destination.stem + '.metadata.json')
                            sidecar.replace(sidecar_destination)
                            moved.append((sidecar, sidecar_destination))
                        updated = SearchEngine(current.folder)
                        if any(removed_id in updated.docs for removed_id in removed_ids):
                            raise ValueError('文章仍存在於索引中。')
                        expected_numbers = list(range(1, len(updated.docs) + 1))
                        if sorted(updated.numbers.values()) != expected_numbers:
                            raise ValueError('文章重新編號失敗。')
                    except Exception:
                        number_temp = number_path.with_suffix('.json.tmp')
                        number_temp.unlink(missing_ok=True)
                        if original_numbers is None:
                            number_path.unlink(missing_ok=True)
                        else:
                            number_path.write_bytes(original_numbers)
                        for original, archived in reversed(moved):
                            if archived.exists() and not original.exists():
                                archived.replace(original)
                        raise
                    state['engine'] = updated
                count = len(removed_ids)
                self.render_notice(f'已從文件集移除 {count} 篇文章，其餘文章已重新連續編號。原始檔已移至 data/trash，需要時仍可救回。')
            except (ValueError, UnicodeDecodeError, OSError) as exc:
                self.render_notice(str(exc), 400)

        def import_pmc(self):
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0<length<=4096 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('匯入請求格式不正確。')
                self.connection.settimeout(30)
                values = parse_qs(self.rfile.read(length).decode('utf-8'))
                token = values.get('token',[''])[0]
                if not secrets.compare_digest(token.encode(),upload_token.encode()):
                    self.render_notice('頁面已過期，請重新整理後再匯入。',403); return
                pmcid = pmc.normalize_pmcid(values.get('pmcid',[''])[0])
                version = values.get('version',[''])[0]
                if pmcid in state['engine'].docs:
                    self.render_notice('本站已有這篇文章，未重複加入。',params={'doc':[pmcid]}); return
                raw, meta = pmc.article_xml(pmcid,version)
                with upload_lock:
                    current = state['engine']
                    if pmcid in current.docs:
                        self.render_notice('本站已有這篇文章，未重複加入。',params={'doc':[pmcid]}); return
                    target = current.folder/f'{pmcid}.{version}.xml'
                    sidecar = current.folder/f'{pmcid}.{version}.metadata.json'
                    if target.exists() or sidecar.exists():
                        raise ValueError('已有同名檔案，請先檢查 data 資料夾，系統不會覆寫。')
                    try:
                        with tempfile.TemporaryDirectory(dir=current.folder) as tempdir:
                            temporary = Path(tempdir)/target.name
                            temporary.write_bytes(raw)
                            temporary.replace(target)
                        sidecar.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
                        updated = SearchEngine(current.folder)
                        if pmcid not in updated.docs:
                            raise ValueError('無法建立新文章索引。')
                    except Exception:
                        target.unlink(missing_ok=True)
                        sidecar.unlink(missing_ok=True)
                        raise
                    state['engine'] = updated
                self.render_notice(f'已下載並加入 {pmcid}，文章編號 {updated.numbers[pmcid]:03d}。可立即搜尋、查看統計及下載 XML。',params={'doc':[pmcid]})
            except (ValueError, ET.ParseError, OSError) as exc:
                self.render_notice(str(exc),400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Local biomedical full-text search')
    parser.add_argument('--data',type=Path,default=ROOT/'data')
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    args.data.mkdir(parents=True,exist_ok=True)
    engine = SearchEngine(args.data)
    try:
        server = ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(engine))
    except OSError as exc:
        raise SystemExit(f'Cannot open port {args.port}: {exc}. Try --port 8766')
    print(f'Loaded {len(engine.docs)} documents; {len(engine.errors)} warnings.',flush=True)
    print(f'Open http://127.0.0.1:{args.port} in your browser. Ctrl+C to stop.',flush=True)
    for error in engine.errors:
        print('Warning:',error,flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
