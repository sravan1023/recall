"""Recall web app: Change Triage (streamed) + MR list view + GitLab webhook.

FastAPI + HTMX + SSE + Tailwind. Run locally:
    uvicorn server:app --reload --port 8080
"""

from __future__ import annotations

import json
import os

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from recall_agent.workflows import change_triage_stream, prior_art_review

load_dotenv()

API = "https://gitlab.com/api/v4"
DEMO_PID = os.environ.get("GITLAB_PROJECT_ID_DEMO", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

app = FastAPI(title="Recall")

_PAGE_HEAD = """
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Recall — Change Triage</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root{
    --bg:#15110d; --paper:#e8dcc1; --paper-edge:#c9b78f; --ink:#2c2117; --ink-soft:#6f6048;
    --gold:#b88a3e; --red:#9c2f22; --amber:#946212; --faded:#7d705a;
  }
  html,body{min-height:100%;}
  body{
    font-family:'Spectral',Georgia,serif; color:#e8dcc4; background:var(--bg);
    background-image:
      radial-gradient(1100px 520px at 50% -8%, rgba(150,104,48,.20), transparent 62%),
      radial-gradient(800px 800px at 100% 100%, rgba(70,48,22,.18), transparent 60%);
    background-attachment:fixed;
  }
  .serif{font-family:'Spectral',Georgia,serif;}
  .mono{font-family:'IBM Plex Mono',ui-monospace,monospace;}
  .label{font-family:'IBM Plex Mono',monospace; text-transform:uppercase; letter-spacing:.2em; font-size:.62rem; color:#a7926a;}
  .paper{
    background-color:var(--paper); color:var(--ink);
    background-image:radial-gradient(rgba(44,33,23,.05) 1px, transparent 1px);
    background-size:3px 3px;
    border:1px solid var(--paper-edge);
    box-shadow:inset 0 1px 0 rgba(255,255,255,.45), 0 14px 34px rgba(0,0,0,.5);
  }
  .band{font-family:'IBM Plex Mono',monospace; text-transform:uppercase; letter-spacing:.12em;
    font-size:.58rem; font-weight:600; padding:.2rem .55rem; border-radius:999px;
    border:1px solid currentColor; display:inline-flex; align-items:center; gap:.4rem; line-height:1;}
  .band::before{content:""; width:.42rem; height:.42rem; border-radius:999px; background:currentColor;}
  .band.strong{color:var(--red);} .band.moderate{color:var(--amber);} .band.weak{color:var(--faded);}
  .band.filed{color:#73904f;} .band.none{color:var(--faded);}
  .chip{font-family:'IBM Plex Mono',monospace; font-size:.7rem; color:#c2ad82; border:1px solid #51422c;
    border-radius:999px; padding:.32rem .7rem; background:rgba(0,0,0,.18); cursor:pointer; transition:all .15s;}
  .chip:hover{color:#f0e6cf; border-color:var(--gold); background:rgba(184,138,62,.12);}
  .btn{transition:all .15s;} .btn:disabled{opacity:.55; cursor:progress;}
  .rule{height:1px;background:linear-gradient(90deg,transparent,#5b4a31,transparent);}
  .teletype{font-family:'IBM Plex Mono',monospace; background:#100c08; border:1px solid #2d241a; color:#b7a47f;}
  .navlink{font-family:'IBM Plex Mono',monospace; text-transform:uppercase; letter-spacing:.18em; font-size:.66rem; color:#a7926a; padding-bottom:2px; border-bottom:1px solid transparent;}
  .navlink:hover{color:#e8dcc4; border-bottom-color:var(--gold);}
  a{color:var(--gold);}
  input,select{font-family:'Spectral',serif;}
  ::placeholder{color:#8a7c63;}
  .prose-ink :is(h1,h2,h3,strong){color:var(--ink);} 
</style>
</head><body class="min-h-screen">
<header class="border-b border-[#3a3025] px-6 py-5">
  <div class="max-w-5xl mx-auto flex items-end gap-5">
    <div>
      <div class="serif text-4xl font-semibold tracking-tight leading-none text-[#f0e6cf]">Recall</div>
    </div>
    <nav class="ml-auto flex gap-6 items-center">
      <a href="/" class="navlink">Change Triage</a>
      <a href="/mrs" class="navlink">Prior-Art</a>
    </nav>
  </div>
</header>
<main class="max-w-5xl mx-auto px-6 py-9">
"""

_PAGE_FOOT = (
    '<footer class="max-w-5xl mx-auto px-6 pb-10 pt-8">'
    '<div class="rule mb-3"></div>'
    '<p class="label">Recall surfaces evidence from your GitLab history</p>'
    "</footer></main></body></html>"
)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def triage_page():
    body = """
<div class="label mb-2">Change Triage</div>
<h1 class="serif text-3xl font-semibold mb-1 text-[#f0e6cf]">What changed that broke this?</h1>
<p class="text-[#bfae8c] mb-6 max-w-2xl leading-relaxed">Describe the symptom and the time window to review.
Recall scans the merge requests in that window and returns a ranked list of likely culprits &mdash; each with
its outcome, cited evidence, and a confidence rating.</p>

<form id="f" class="paper rounded-md p-5">
  <label class="label block mb-2" for="symptom">Reported symptom</label>
  <input id="symptom" name="symptom" required autocomplete="off"
    placeholder="e.g. markdown docs are being unexpectedly rewritten"
    class="w-full rounded-sm bg-[#f4ecd9] border border-[#c9b78f] px-4 py-3 text-[#2c2117] focus:outline-none focus:ring-2 focus:ring-[#b88a3e]/40 focus:border-[#b88a3e]">
  <div class="flex flex-wrap items-end gap-4 mt-4">
    <div>
      <label class="label block mb-2" for="window">Window under review</label>
      <select id="window" class="rounded-sm bg-[#f4ecd9] border border-[#c9b78f] px-3 py-2 text-[#2c2117] focus:outline-none focus:border-[#b88a3e]">
        <option value="0.25">Last 6 hours</option>
        <option value="1">Last 24 hours</option>
        <option value="7" selected>Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="90">Last 90 days</option>
        <option value="365">Last year</option>
      </select>
    </div>
    <button id="run" class="btn ml-auto rounded-sm bg-[#2c2117] hover:bg-[#3a2c1d] px-6 py-2.5 label !text-[#e8dcc1] border border-[#1c150e]">Run triage</button>
  </div>
</form>

<div class="flex flex-wrap items-center gap-2 mt-3">
  <span class="label mr-1">Examples</span>
  <button class="chip" data-q="markdown docs are being unexpectedly rewritten" data-w="365">markdown files rewritten</button>
  <button class="chip" data-q="CI pipeline started failing on the docs job" data-w="90">CI docs job failing</button>
  <button class="chip" data-q="branch inference / stack operations behaving oddly" data-w="90">stack inference broke</button>
</div>

<div id="empty" class="mt-10 text-center text-[#8a7c63]">
  <div class="serif text-lg text-[#bfae8c]">Nothing to triage yet</div>
  <p class="text-sm mt-1">Enter a symptom above, or pick an example, to get a ranked list of suspects.</p>
</div>

<div id="results" class="hidden mt-9">
  <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-4">
    <h2 class="serif text-xl text-[#f0e6cf]">Findings</h2>
    <span id="rmeta" class="label"></span>
    <span id="rstatus" class="ml-auto band weak"></span>
  </div>

  <div id="summary" class="paper prose-ink rounded-sm p-4 mb-7 serif text-[15px] leading-relaxed text-[#2c2117]"></div>

  <div class="grid lg:grid-cols-3 gap-6">
    <div class="lg:col-span-2">
      <div class="flex items-center justify-between mb-3">
        <div class="label">Suspects &mdash; ranked</div>
        <div class="flex items-center gap-3 text-[10px]">
          <span class="band strong">strong</span><span class="band moderate">moderate</span><span class="band weak">weak</span>
        </div>
      </div>
      <div id="suspects" class="space-y-3"></div>
    </div>
    <aside>
      <div class="label mb-3">Reasoning trace</div>
      <div id="reasoning" class="teletype rounded-sm text-[11px] p-3 space-y-1.5 leading-relaxed min-h-[6rem]"></div>
    </aside>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const f=$('f'), runBtn=$('run');

function bandLegend(counts){
  const parts=[]; ['strong','moderate','weak'].forEach(b=>{ if(counts[b]) parts.push(counts[b]+' '+b); });
  return parts.join(' · ');
}

document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{
  $('symptom').value=c.dataset.q; $('window').value=c.dataset.w; f.requestSubmit();
}));

f.addEventListener('submit',e=>{
  e.preventDefault();
  const symptom=$('symptom').value.trim(); if(!symptom) return;
  const windowSel=$('window'); const window_days=windowSel.value;
  const windowLabel=windowSel.options[windowSel.selectedIndex].text.toLowerCase();

  $('empty').classList.add('hidden');
  $('results').classList.remove('hidden');
  $('reasoning').innerHTML=''; $('suspects').innerHTML='';
  $('summary').innerHTML='<span class="text-[#6f6048] italic">Compiling summary…</span>';
  $('rmeta').textContent='';
  $('rstatus').className='band moderate'; $('rstatus').textContent='reviewing';
  runBtn.disabled=true; const runLabel=runBtn.textContent; runBtn.textContent='Reviewing…';

  let narrationBuf='';
  const es=new EventSource(`/api/triage/stream?symptom=${encodeURIComponent(symptom)}&window_days=${window_days}`);
  es.onmessage=ev=>{
    const d=JSON.parse(ev.data);
    if(d.type==='status'){
      const p=document.createElement('div');
      p.innerHTML='<span class="text-[#b88a3e]">›</span> '+d.message;
      $('reasoning').appendChild(p);
    } else if(d.type==='suspects'){
      const counts={strong:0,moderate:0,weak:0};
      const box=$('suspects'); box.innerHTML='';
      if(!d.data.length){
        box.innerHTML='<div class="paper rounded-sm p-4 text-sm text-[#6f6048]">No merge requests in this window. Try a wider window.</div>';
      }
      d.data.forEach((s,i)=>{
        const band=(s.band||'weak'); counts[band]=(counts[band]||0)+1;
        const why=(s.reasons&&s.reasons.length)?s.reasons[0]:'';
        const el=document.createElement('div');
        el.className='paper rounded-sm p-4';
        el.innerHTML=`<div class="flex items-start gap-4">
          <div class="mono text-xl font-semibold text-[#b0a079] leading-none pt-1 w-6 text-right">${i+1}</div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-3 mb-1.5">
              <span class="band ${band}">${band}</span>
              <a href="https://gitlab.com/gitlab-org/cli/-/merge_requests/${s.mr_id}" target="_blank" class="ml-auto mono text-xs text-[#8a6a32] hover:underline shrink-0">MR !${s.mr_id} ↗</a>
            </div>
            <div class="serif text-[15px] text-[#2c2117] leading-snug">${s.title}</div>
            <div class="text-xs text-[#6f6048] mt-2">Outcome: <b class="text-[#2c2117]">${s.outcome||'unlabeled'}</b>${s.outcome_evidence?(' — '+s.outcome_evidence):''}</div>
            ${why?`<div class="text-xs text-[#8a6a32] mt-1">Why flagged: ${why}</div>`:''}
            <div class="mono text-[11px] text-[#8a7c63] mt-2 truncate">${(s.files_touched||[]).slice(0,4).join('  ·  ')||'—'}</div>
          </div></div>`;
        box.appendChild(el);
      });
      $('rmeta').textContent=`${d.reviewed} MRs reviewed · ${windowLabel}` + (bandLegend(counts)?` · ${bandLegend(counts)}`:'');
    } else if(d.type==='token'){
      narrationBuf+=d.text; $('summary').innerHTML=marked.parse(narrationBuf);
    } else if(d.type==='done'){
      $('rstatus').className='band filed'; $('rstatus').textContent='complete';
      runBtn.disabled=false; runBtn.textContent=runLabel; es.close();
    }
  };
  es.onerror=()=>{
    $('rstatus').className='band strong'; $('rstatus').textContent='error';
    if(!$('summary').textContent.trim()||$('summary').textContent.includes('Compiling')){
      $('summary').innerHTML='<span class="text-[#9c2f22]">The triage run was interrupted. Please try again.</span>';
    }
    runBtn.disabled=false; runBtn.textContent=runLabel; es.close();
  };
});
</script>
"""
    return HTMLResponse(_PAGE_HEAD + body + _PAGE_FOOT)


@app.get("/api/triage/stream")
def triage_stream(symptom: str, window_days: float = 7):
    def gen():
        for event in change_triage_stream(symptom, window_days=window_days):
            yield f"data: {json.dumps(event)}\n\n"

    async def sse():
        async for chunk in iterate_in_threadpool(gen()):
            yield chunk

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/mrs", response_class=HTMLResponse)
def mrs_page():
    cards = ""
    if DEMO_PID:
        headers = {"PRIVATE-TOKEN": os.environ["GITLAB_TOKEN"]}
        mrs = requests.get(
            f"{API}/projects/{DEMO_PID}/merge_requests",
            headers=headers,
            params={"state": "all", "per_page": 20, "order_by": "updated_at", "sort": "desc"},
            timeout=30,
        ).json()
        for m in mrs:
            notes = requests.get(
                f"{API}/projects/{DEMO_PID}/merge_requests/{m['iid']}/notes",
                headers=headers,
                params={"per_page": 50},
                timeout=30,
            ).json()
            recall_note = next((n for n in notes if "Recall — prior art" in (n.get("body") or "")), None)
            badge = (
                '<span class="band filed">prior-art filed</span>'
                if recall_note
                else '<span class="band none">no entry</span>'
            )
            comment_html = ""
            if recall_note:
                safe = (recall_note["body"] or "").replace("<", "&lt;")
                comment_html = (
                    '<div class="teletype rounded-sm p-3 mt-3 text-xs whitespace-pre-wrap leading-relaxed">'
                    f"{safe}</div>"
                )
            cards += f"""
<div class="paper rounded-sm p-4">
  <div class="flex items-center gap-3">
    <a href="{m['web_url']}" target="_blank" class="mono text-xs text-[#8a6a32] hover:underline">MR !{m['iid']}</a>
    <span class="serif text-[15px] text-[#2c2117] leading-snug">{m['title']}</span>
    <span class="ml-auto shrink-0">{badge}</span>
  </div>{comment_html}
</div>"""
    if not cards:
        cards = '<p class="text-[#8a7c63] text-sm italic">No merge requests in the demo repo yet.</p>'
    body = (
        '<div class="label mb-2">Prior-Art Review</div>'
        '<h1 class="serif text-3xl font-semibold mb-1 text-[#f0e6cf]">Has anyone tried this before?</h1>'
        '<p class="text-[#bfae8c] mb-7 max-w-2xl leading-relaxed">Merge requests in the demo repository. When one '
        'opens, a GitLab webhook triggers Recall to post a prior-art note back through the '
        'GitLab MCP server.</p>'
        f'<div class="space-y-3">{cards}</div>'
    )
    return HTMLResponse(_PAGE_HEAD + body + _PAGE_FOOT)


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks, x_gitlab_token: str = Header(default="")):
    if WEBHOOK_SECRET and x_gitlab_token != WEBHOOK_SECRET:
        return JSONResponse({"error": "invalid token"}, status_code=401)
    payload = await request.json()
    if payload.get("object_kind") != "merge_request":
        return {"status": "ignored", "reason": "not a merge_request event"}
    attrs = payload.get("object_attributes", {})
    if attrs.get("action") not in ("open", "reopen", "update"):
        return {"status": "ignored", "reason": f"action={attrs.get('action')}"}
    project_id = str(payload.get("project", {}).get("id") or DEMO_PID)
    mr_iid = attrs.get("iid")
    background.add_task(prior_art_review, project_id, int(mr_iid), True)
    return {"status": "queued", "mr_iid": mr_iid}
