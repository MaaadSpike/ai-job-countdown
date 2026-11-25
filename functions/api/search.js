// Cloudflare Pages Function：GET /api/search?q=software+engineer+AI&lang=en&days=30
// 在服务器端查 Google News RSS（浏览器不能直接跨域请求它），返回 JSON。不需要 API key。
// 同一个查询在 Cloudflare 边缘缓存 6 小时，避免频繁请求 Google。
// 部署：functions/ 要在仓库根目录（wrangler 运行的目录），`wrangler pages deploy web` 会自动带上。
// 本地测试：在仓库根目录运行 `npx wrangler pages dev web`（python -m http.server 不会运行这个函数）。

const UA = "Mozilla/5.0 (compatible; ai-job-countdown/1.0)";
const EDITIONS = {
  en: { hl: "en-US", gl: "US", ceid: "US:en" },
  zh: { hl: "zh-CN", gl: "CN", ceid: "CN:zh-Hans" },
};

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function decode(s) {
  return s
    .replace(/^<!\[CDATA\[|\]\]>$/g, "")
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(+n))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&quot;/g, '"').replace(/&apos;|&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
    .trim();
}

function tag(block, name) {
  const m = block.match(new RegExp("<" + name + "(?:\\s[^>]*)?>([\\s\\S]*?)</" + name + ">"));
  return m ? decode(m[1]) : "";
}

export function parseRss(xml, limit = 10) {
  const out = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const b = m[1];
    let t = tag(b, "title");
    const src = tag(b, "source");
    if (src && t.endsWith(" - " + src)) t = t.slice(0, -(src.length + 3)).trim();
    const url = tag(b, "link");
    const d = new Date(tag(b, "pubDate"));
    if (!t || !/^https?:\/\//.test(url) || isNaN(d)) continue;
    out.push({ t, src, url, date: d.toISOString().slice(0, 10) });
    if (out.length >= limit) break;
  }
  return out;
}

export async function onRequestGet(context) {
  const u = new URL(context.request.url);
  const q = (u.searchParams.get("q") || "").replace(/\s+/g, " ").trim().slice(0, 120);
  if (q.length < 2) return json({ error: "q is required" }, 400);
  const lang = u.searchParams.get("lang") === "zh" ? "zh" : "en";
  const days = Math.min(365, Math.max(1, parseInt(u.searchParams.get("days"), 10) || 30));

  const cache = caches.default;
  const key = new Request("https://cache.internal/search?" + new URLSearchParams({ q: q.toLowerCase(), lang, days }));
  const hit = await cache.match(key);
  if (hit) return hit;

  const rss = "https://news.google.com/rss/search?" + new URLSearchParams({ q: `${q} when:${days}d`, ...EDITIONS[lang] });
  let r;
  try {
    r = await fetch(rss, { headers: { "User-Agent": UA } });
  } catch (e) {
    return json({ error: "upstream fetch failed" }, 502);
  }
  if (!r.ok) return json({ error: "upstream " + r.status }, 502);

  const items = parseRss(await r.text());
  const resp = json({ q, lang, days, items }, 200, { "Cache-Control": "public, max-age=1800" });
  context.waitUntil(cache.put(key, new Response(resp.clone().body, {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=21600" },
  })));
  return resp;
}
