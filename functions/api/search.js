// Cloudflare Pages Function：GET /api/search?q=software+engineer+AI&lang=en&days=30[&impact=0]
// 在服务器端查新闻（浏览器不能直接跨域请求这些源），返回 JSON。不需要 API key。
// 新闻源按顺序尝试，前一个失败就换下一个：
//   1. Google News RSS —— 常常拒绝 Cloudflare 的服务器（返回 503），失败后 1 小时内跳过
//   2. Bing News RSS
//   3. GDELT DOC API（免费的全球新闻库，专门给程序用；只跑一次合并查询，因为它限速）
// 默认（impact=1）跑两组查询，按标题关键词粗分：
//   signal「AI 进展」：取代、裁员、自动化、岗位……
//   check 「现实检验」：出错、幻觉、重新招人、不会取代、短缺……
// 只看标题、不调模型，分类会有错；页面上标明「自动搜索，未经人工核实」。
// 同一个查询在 Cloudflare 边缘缓存 6 小时。返回里的 source 说明这次用的是哪个源，tried 记录失败的源。
// 部署：functions/ 要在仓库根目录（wrangler 运行的目录），`wrangler pages deploy web` 会自动带上。
// 本地测试：在仓库根目录运行 `npx wrangler pages dev web`（python -m http.server 不会运行这个函数）。

const UA = "Mozilla/5.0 (compatible; ai-job-countdown/1.0)";
const EDITIONS = {
  en: { hl: "en-US", gl: "US", ceid: "US:en" },
  zh: { hl: "zh-CN", gl: "CN", ceid: "CN:zh-Hans" },
};

const QUERY = {
  signal: {
    en: '(replace OR replacing OR replaced OR layoffs OR "job cuts" OR automate OR automation OR jobs OR hiring OR workforce OR obsolete)',
    zh: "(取代 OR 替代 OR 代替 OR 裁员 OR 失业 OR 岗位 OR 饭碗 OR 就业 OR 自动化 OR 淘汰)",
  },
  check: {
    en: '(errors OR mistakes OR fails OR failed OR hallucinations OR fabricated OR rehire OR rehiring OR "won\'t replace" OR "can\'t replace" OR overhyped OR backlash OR shortage OR "still need")',
    zh: "(出错 OR 失误 OR 幻觉 OR 翻车 OR 重新招聘 OR 不会取代 OR 无法取代 OR 高估 OR 局限 OR 短缺)",
  },
};
// 按标题分类：先看是不是「现实检验」，再看是不是「AI 进展」，都不是就丢掉（招聘广告、课程、泛泛的介绍）
const TITLE = {
  check: {
    en: /\b(errors?|mistakes?|fail\w*|flaw\w*|hallucinat\w*|fabricat\w*|fake|wrong|rehir\w*|revers\w*|backtrack\w*|scal\w* back|pull\w* back|paus\w*|halt\w*|ban\w*|sanction\w*|lawsuits?|sued|backlash|protest\w*|overhyped|hype|limits?|limitations?|struggl\w*|shortages?|still need\w*|(won't|can't|cannot|will not|isn't|not) (replace|take)\w*|slower|worse|risks?)\b/i,
    zh: /出错|错误|失误|幻觉|编造|翻车|重新招聘|回聘|叫停|暂停|起诉|处罚|抗议|高估|局限|短缺|不会取代|无法取代|难以取代|取代不了|风险/,
  },
  signal: {
    en: /\b(replac\w*|layoffs?|laid off|lay off|job cuts?|cut\w* jobs?|jobs?|automat\w*|obsolete|displac\w*|hiring|hires?|workforce|unemploy\w*|eliminat\w*|redundan\w*|take over|taking over|threat\w*|wipe out|wiping out|headcount|entry-level|junior|agents?)\b/i,
    zh: /取代|替代|代替|裁员|失业|岗位|饭碗|就业|自动化|淘汰|消失|冲击|抢走|招聘|入门级|初级/,
  },
};

export function classify(title) {
  if (TITLE.check.en.test(title) || TITLE.check.zh.test(title)) return "check";
  if (TITLE.signal.en.test(title) || TITLE.signal.zh.test(title)) return "signal";
  return null;
}

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

// Bing 的链接是 bing.com/news/apiclick.aspx?...&url=<原文>，取出原文地址
export function unwrap(link) {
  try {
    const u = new URL(link);
    const real = /(^|\.)bing\.com$/.test(u.hostname) && u.searchParams.get("url");
    if (real && /^https?:\/\//i.test(real)) return real;
  } catch (_) { /* 不是合法 URL，原样返回，后面会被过滤 */ }
  return link;
}

export function parseRss(xml, limit = 10) {
  const out = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)) {
    const b = m[1];
    let t = tag(b, "title");
    const src = tag(b, "source") || tag(b, "News:Source");
    if (src && t.endsWith(" - " + src)) t = t.slice(0, -(src.length + 3)).trim();
    const url = unwrap(tag(b, "link"));
    const d = new Date(tag(b, "pubDate"));
    if (!t || !/^https?:\/\//.test(url) || isNaN(d)) continue;
    out.push({ t, src, url, date: d.toISOString().slice(0, 10) });
    if (out.length >= limit) break;
  }
  return out;
}

const TIMEOUT_MS = 8000;

async function get(url) {
  const r = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/rss+xml, application/xml, application/json;q=0.9, */*;q=0.5" },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!r.ok) { const e = new Error("HTTP " + r.status); e.status = r.status; throw e; }
  return r.text();
}

function rssOrThrow(xml) {
  if (!/<rss[\s>]|<item>/.test(xml)) throw new Error("not RSS (probably a bot check page)");
  return parseRss(xml, 50);
}

async function googleNews(q, lang, days) {
  return rssOrThrow(await get("https://news.google.com/rss/search?" +
    new URLSearchParams({ q: `${q} when:${days}d`, ...EDITIONS[lang] })));
}

const BING = { en: { setlang: "en-US", cc: "US" }, zh: { setlang: "zh-Hans", cc: "CN" } };
async function bingNews(q, lang) {
  return rssOrThrow(await get("https://www.bing.com/news/search?" +
    new URLSearchParams({ q, format: "rss", count: "50", qft: 'sortbydate="1"', ...BING[lang] })));
}

// GDELT：短于 3 个字母的词会被拒绝，把 AI 换成 "artificial intelligence"，其他短词去掉
export function gdeltQuery(q, lang) {
  const words = (q.match(/"[^"]+"|\S+/g) || [])
    .map(w => /^ai$/i.test(w) ? '"artificial intelligence"' : w)
    .filter(w => w.startsWith('"') || !/^[\x00-\x7f]{1,2}$/.test(w));
  const extra = lang === "zh" ? "" :
    ' (replace OR layoffs OR automation OR jobs OR hiring OR workforce OR errors OR mistakes OR rehire OR shortage OR backlash)';
  return words.join(" ") + extra + " sourcelang:" + (lang === "zh" ? "chinese" : "english");
}

export function parseGdelt(text, limit = 75) {
  let data;
  try { data = JSON.parse(text); } catch (_) { throw new Error("GDELT: " + text.trim().slice(0, 100)); }
  const out = [];
  for (const a of data.articles || []) {
    const m = /^(\d{4})(\d{2})(\d{2})/.exec(a.seendate || "");
    const t = decode(String(a.title || ""));
    if (!m || !t || !/^https?:\/\//.test(a.url || "")) continue;
    out.push({ t, src: a.domain || "", url: a.url, date: `${m[1]}-${m[2]}-${m[3]}` });
    if (out.length >= limit) break;
  }
  return out;
}

async function gdelt(q, lang, days) {
  return parseGdelt(await get("https://api.gdeltproject.org/api/v2/doc/doc?" + new URLSearchParams({
    query: gdeltQuery(q, lang), mode: "artlist", format: "json", maxrecords: "75",
    timespan: `${Math.min(days, 90)}d`, sort: "datedesc",
  })));
}

// 每个源：impact 时怎么查（返回若干组结果），普通搜索怎么查
const SOURCES = [
  { name: "google", label: "Google News",
    impact: (q, lang, days) => Promise.all(["signal", "check"].map(g => googleNews(`${q} ${QUERY[g][lang]}`, lang, days))),
    plain: (q, lang, days) => googleNews(q, lang, days) },
  { name: "bing", label: "Bing News",
    impact: (q, lang) => Promise.all(["signal", "check"].map(g => bingNews(`${q} ${QUERY[g][lang]}`, lang))),
    plain: (q, lang) => bingNews(q, lang) },
  { name: "gdelt", label: "GDELT",
    impact: async (q, lang, days) => [await gdelt(q, lang, days)],
    plain: (q, lang, days) => gdelt(q, lang, days) },
];

const SKIP_TTL = 3600; // 被拦（403/429/503）的源，1 小时内不再试
const skipKey = name => new Request("https://cache.internal/skip/" + name);

export function withinDays(items, days, now = Date.now()) {
  const cut = new Date(now - days * 864e5).toISOString().slice(0, 10);
  return items.filter(it => it.date >= cut);
}

// 依次试每个源；返回 { source, items, tried }
export async function searchAll(q, lang, days, impact, { cache = null, sources = SOURCES, now = Date.now(), waitUntil = p => p } = {}) {
  const tried = [];
  let empty = null;
  for (const s of sources) {
    if (cache && await cache.match(skipKey(s.name))) { tried.push({ source: s.name, error: "skipped (blocked recently)" }); continue; }
    try {
      let items;
      if (impact) items = mergeGroups((await s.impact(q, lang, days)).map(g => withinDays(g, days, now)));
      else items = withinDays(await s.plain(q, lang, days), days, now).slice(0, 10);
      if (items.length) return { source: s.label, items, tried };
      tried.push({ source: s.name, error: "0 results" });
      empty = empty || { source: s.label, items, tried };
    } catch (e) {
      tried.push({ source: s.name, error: String(e.message || e) });
      if (cache && [403, 429, 503].includes(e.status)) {
        waitUntil(cache.put(skipKey(s.name), new Response("1", { headers: { "Cache-Control": `max-age=${SKIP_TTL}` } })));
      }
    }
  }
  if (empty) return empty; // 有源正常返回但没有相关报道
  const err = new Error("all news sources failed");
  err.tried = tried;
  throw err;
}

// 两组结果合并、去重、分类，每类最多 per 条，按日期倒序
export function mergeGroups(groups, per = 6) {
  const seen = new Set();
  const kept = { signal: [], check: [] };
  for (const it of groups.flat()) {
    const key = it.t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim(); // 保留中文，否则中文标题都会变成同一个 key
    if (seen.has(it.url) || seen.has(key)) continue;
    seen.add(it.url); seen.add(key);
    const k = classify(it.t);
    if (k && kept[k].length < per) kept[k].push({ ...it, k });
  }
  return [...kept.signal, ...kept.check].sort((a, b) => b.date.localeCompare(a.date));
}

export async function onRequestGet(context) {
  const u = new URL(context.request.url);
  const q = (u.searchParams.get("q") || "").replace(/\s+/g, " ").trim().slice(0, 120);
  if (q.length < 2) return json({ error: "q is required" }, 400);
  const lang = u.searchParams.get("lang") === "zh" ? "zh" : "en";
  const days = Math.min(365, Math.max(1, parseInt(u.searchParams.get("days"), 10) || 30));
  const impact = u.searchParams.get("impact") !== "0";

  const cache = caches.default;
  const key = new Request("https://cache.internal/search?" + new URLSearchParams({ q: q.toLowerCase(), lang, days, impact: impact ? 2 : 0 }));
  const hit = await cache.match(key);
  if (hit) return hit;

  let res;
  try {
    res = await searchAll(q, lang, days, impact, { cache, waitUntil: p => context.waitUntil(p) });
  } catch (e) {
    return json({ error: String(e.message || e), tried: e.tried || [] }, 502);
  }

  const ttl = res.items.length ? 21600 : 1800; // 空结果只缓存半小时
  const resp = json({ q, lang, days, impact, ...res }, 200, { "Cache-Control": "public, max-age=1800" });
  context.waitUntil(cache.put(key, new Response(resp.clone().body, {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": `public, max-age=${ttl}` },
  })));
  return resp;
}
