from __future__ import annotations


def render_home(*, mdblist: bool, tmdb: bool, nuvio: bool, stremio: bool, addon_url: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MDBridge</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:32px auto;padding:0 18px;line-height:1.45;background:#fafafa;color:#181818}}
.card{{background:white;border:1px solid #ddd;border-radius:12px;padding:18px;margin:14px 0}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}@media(max-width:650px){{.grid{{grid-template-columns:1fr}}}}
input{{box-sizing:border-box;width:100%;padding:9px;margin:5px 0 10px;border:1px solid #bbb;border-radius:7px}}
button{{padding:9px 14px;border:1px solid #999;border-radius:7px;background:#f4f4f4;cursor:pointer;margin:3px}}
code,pre{{background:#f1f1f1;border-radius:6px}}code{{padding:2px 5px;word-break:break-all}}pre{{padding:12px;overflow:auto}}
.ok{{color:#16751b}}.bad{{color:#a02222}}small{{color:#666}}
</style>
</head>
<body>
<h1>MDBridge</h1>
<p>MDBList is the canonical watched and resume database. MDBridge synchronizes Nuvio Cloud and the Stremio account cloud to it.</p>
<div class="card">
<b>Connections</b><br>
MDBList: <span class="{'ok' if mdblist else 'bad'}">{'configured' if mdblist else 'not configured'}</span> ·
TMDB: <span class="{'ok' if tmdb else 'bad'}">{'configured' if tmdb else 'not configured'}</span> ·
Nuvio: <span class="{'ok' if nuvio else 'bad'}">{'connected' if nuvio else 'not connected'}</span> ·
Stremio: <span class="{'ok' if stremio else 'bad'}">{'connected' if stremio else 'not connected'}</span>
</div>
<div class="card">
<h3>1. MDBList and TMDB</h3>
<div class="grid"><div><label>MDBList API key</label><input id="mdb" type="password" autocomplete="off"></div>
<div><label>TMDB Read Access Token</label><input id="tmdb" type="password" autocomplete="off"></div></div>
<button onclick="saveKeys()">Save keys</button> <span id="keymsg"></span>
</div>
<div class="card">
<h3>2. Nuvio</h3>
<small>Your password is used once to obtain Nuvio tokens and is not written to the MDBridge config file.</small>
<div class="grid"><div><label>Email</label><input id="nemail" type="email"></div><div><label>Password</label><input id="npass" type="password"></div></div>
<label>Profile number (normally 1)</label><input id="nprofile" type="number" min="1" max="6" value="1">
<button onclick="connectNuvio()">Connect Nuvio</button> <span id="nmsg"></span>
</div>
<div class="card">
<h3>3. Stremio</h3>
<p>Use Stremio's account link flow. This covers every TV signed into that Stremio account.</p>
<button onclick="startStremio()">Create Stremio link</button>
<div id="slink"></div>
</div>
<div class="card">
<h3>4. Optional Stremio catalog</h3>
<p>You do <b>not</b> need this catalog for tracking. It adds MDBList Continue Watching catalogs to Stremio.</p>
<code>{addon_url}</code>
</div>
<div class="card">
<h3>Status</h3><button onclick="syncNow()">Sync now</button><button onclick="status()">Refresh status</button>
<pre id="status">Loading...</pre>
</div>
<script>
let activeCode = null;
async function jsonFetch(url, options={{}}) {{
  let r = await fetch(url, options); let data = await r.json();
  if (!r.ok) throw new Error(data.detail || JSON.stringify(data)); return data;
}}
async function saveKeys() {{
  try {{ let body={{}}; if(mdb.value) body.mdblist_api_key=mdb.value; if(tmdb.value) body.tmdb_token=tmdb.value;
    await jsonFetch('/api/settings',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}}); keymsg.textContent='Saved'; status(); }}
  catch(e){{keymsg.textContent=e.message}}
}}
async function connectNuvio() {{
  try {{let data=await jsonFetch('/api/nuvio/connect',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email:nemail.value,password:npass.value,profile_id:Number(nprofile.value)}})}}); npass.value=''; nmsg.textContent='Connected'; status();}}
  catch(e){{nmsg.textContent=e.message}}
}}
async function startStremio() {{
  try {{let d=await jsonFetch('/api/stremio/link/start',{{method:'POST'}}); activeCode=d.code;
    slink.innerHTML=`<p>Code: <b>${{d.code}}</b><br><a href="${{d.link}}" target="_blank" rel="noopener">Authorize in Stremio</a></p><button onclick="checkStremio()">I authorized it, check now</button><span id="smsg"></span>`;}}
  catch(e){{slink.textContent=e.message}}
}}
async function checkStremio() {{
  try {{let d=await jsonFetch('/api/stremio/link/status/'+activeCode); smsg.textContent=d.authorized?' Connected':' Not authorized yet'; if(d.authorized) status();}}
  catch(e){{smsg.textContent=e.message}}
}}
async function syncNow() {{try{{statusEl().textContent='Syncing...'; let d=await jsonFetch('/api/sync',{{method:'POST'}}); statusEl().textContent=JSON.stringify(d,null,2)}}catch(e){{statusEl().textContent=e.message}}}}
function statusEl(){{return document.getElementById('status')}}
async function status() {{try{{let d=await jsonFetch('/api/status');statusEl().textContent=JSON.stringify(d,null,2)}}catch(e){{statusEl().textContent=e.message}}}}
status();
</script>
</body></html>"""
