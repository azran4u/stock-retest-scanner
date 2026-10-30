// Nightly app-data upload (stock-retest-scanner, 2026-10-30): the box's export writes app/data/*.json and POSTs them
// here; files go to the PRIVATE Storage bucket 'app-data' (read only by the owner's login, storage policy).
// Auth: header x-srs-token, checked against a SHA-256 hash in srs_private.upload_tokens (rpc srs_check_upload_token).
// Body: {"files": [{"path": "index.json", "content": "<json text>"}, ...]}  or  {"delete": ["candles/X.json"]}
import { createClient } from 'npm:@supabase/supabase-js@2';

const sb = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });
const OK_PATH = /^(?!.*\.\.)[A-Za-z0-9_\-]+(\/[A-Za-z0-9_.\-]+)*\.json$/;
const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { 'Content-Type': 'application/json' } });

Deno.serve(async (req: Request) => {
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
  const tok = req.headers.get('x-srs-token') || '';
  if (!tok) return json({ error: 'unauthorized' }, 401);
  const { data: good, error: e1 } = await sb.rpc('srs_check_upload_token', { t: tok });
  if (e1) return json({ error: 'token check failed' }, 500);
  if (!good) return json({ error: 'unauthorized' }, 401);
  let body: any;
  try { body = await req.json(); } catch { return json({ error: 'bad json' }, 400); }
  const bucket = sb.storage.from('app-data');
  const done: string[] = [], failed: { path: string; error: string }[] = [];
  for (const f of (Array.isArray(body?.files) ? body.files : [])) {
    const path = String(f?.path || '');
    if (!OK_PATH.test(path) || typeof f?.content !== 'string') { failed.push({ path, error: 'bad path or content' }); continue; }
    const { error } = await bucket.upload(path, new Blob([f.content], { type: 'application/json' }), { upsert: true, contentType: 'application/json', cacheControl: '0' });
    if (error) failed.push({ path, error: error.message }); else done.push(path);
  }
  let deleted = 0;
  const del = (Array.isArray(body?.delete) ? body.delete : []).map(String).filter((p: string) => OK_PATH.test(p));
  if (del.length) { const { data, error } = await bucket.remove(del); if (error) failed.push({ path: 'delete', error: error.message }); else deleted = data?.length ?? 0; }
  return json({ uploaded: done.length, deleted, failed }, failed.length ? 207 : 200);
});
