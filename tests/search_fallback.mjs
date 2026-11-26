import * as S from "../functions/api/search.js";
const assert = (c, m) => { if (!c) { console.error("FAIL", m); process.exit(1); } else console.log("ok ", m); };
const NOW = Date.parse("2026-11-25T12:00:00Z");
const day = n => new Date(NOW - n*864e5).toUTCString();

// --- mock fetch
let calls = [];
const bingRss = `<?xml version="1.0"?><rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss"><channel><title>x</title>
<item><title>Tech giant lays off 500 software engineers as AI agents take over coding</title><link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=abc&amp;url=https%3a%2f%2fexample.com%2fa1&amp;c=1&amp;mkt=en-us</link><pubDate>${day(2)}</pubDate><News:Source>Example Times</News:Source></item>
<item><title>AI coding tools introduce more bugs, study finds errors rising</title><link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fexample.org%2fb2&amp;mkt=en-us</link><pubDate>${day(5)}</pubDate><News:Source>Org News</News:Source></item>
<item><title>Old story about AI jobs</title><link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fold.com%2fx</link><pubDate>${day(90)}</pubDate><News:Source>Old</News:Source></item>
</channel></rss>`;
const gdeltJson = JSON.stringify({ articles: [
  { url: "https://g.com/1", title: "Companies replace junior developers with AI", seendate: "20261120T101500Z", domain: "g.com" },
  { url: "https://g.com/2", title: "Why AI won't replace software engineers", seendate: "20261118T000000Z", domain: "g2.com" },
]});
function mock(plan) {
  globalThis.fetch = async (url) => {
    const host = new URL(url).hostname; calls.push(url);
    const r = plan[host];
    if (typeof r === "number") return new Response("blocked", { status: r });
    return new Response(r ?? "", { status: 200 });
  };
}
class MemCache { constructor(){this.m=new Map();} async match(r){return this.m.get(r.url);} async put(r,v){this.m.set(r.url,v);} }

// 1. unwrap
assert(S.unwrap("http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fexample.com%2fa1&c=1") === "https://example.com/a1", "unwrap bing link");
assert(S.unwrap("https://news.google.com/rss/articles/x") === "https://news.google.com/rss/articles/x", "keep google link");
// 2. gdeltQuery
const gq = S.gdeltQuery("software engineer AI", "en");
assert(gq.startsWith('software engineer "artificial intelligence" (') && gq.endsWith("sourcelang:english"), "gdelt query: " + gq);
assert(!/\bAI\b/.test(S.gdeltQuery("AI ML engineer", "en").split("(")[0].replace('"artificial intelligence"',"")), "drop short words");
assert(S.gdeltQuery("软件工程师 AI", "zh") === '软件工程师 "artificial intelligence" sourcelang:chinese', "gdelt zh");
// 3. parseGdelt errors
let threw = false; try { S.parseGdelt("Your search contained a keyword that was too short."); } catch (e) { threw = /too short/.test(e.message); }
assert(threw, "gdelt text error -> exception");

// 4. Google 503 -> Bing
calls = []; mock({ "news.google.com": 503, "www.bing.com": bingRss });
let cache = new MemCache(); const pend = [];
let r = await S.searchAll("software engineer AI", "en", 30, true, { cache, now: NOW, waitUntil: p => pend.push(p) });
await Promise.all(pend);
assert(r.source === "Bing News", "fell back to Bing");
assert(r.items.length === 2 && r.items.every(i => i.url.startsWith("https://example.")), "bing items unwrapped, old item dropped, dup across groups removed");
assert(r.items.find(i => i.src === "Org News").k === "check" && r.items.find(i => i.src === "Example Times").k === "signal", "classified");
assert(r.tried[0].source === "google" && /503/.test(r.tried[0].error), "tried records google 503");
assert(calls.some(u => u.includes("sortbydate")), "bing sorted by date");
// 5. second request skips google (blocked memo)
calls = []; r = await S.searchAll("nurse AI", "en", 30, true, { cache, now: NOW });
assert(!calls.some(u => u.includes("news.google.com")) && r.tried[0].error.startsWith("skipped"), "google skipped for 1h");
// 6. Google + Bing (HTML bot page) fail -> GDELT
calls = []; mock({ "news.google.com": 503, "www.bing.com": "<html>captcha</html>", "api.gdeltproject.org": gdeltJson });
r = await S.searchAll("software engineer AI", "en", 30, true, { cache: new MemCache(), now: NOW });
assert(r.source === "GDELT" && r.items.length === 2, "fell back to GDELT");
assert(r.items.find(i => i.url === "https://g.com/2").k === "check", "gdelt classified");
assert(calls.filter(u => u.includes("gdelt")).length === 1, "only one gdelt request");
// 7. Bing returns RSS with nothing relevant -> tries GDELT; GDELT also empty -> returns empty result
const emptyRss = `<rss><channel><item><title>Learn Python course</title><link>https://x.com/c</link><pubDate>${day(1)}</pubDate></item></channel></rss>`;
mock({ "news.google.com": 503, "www.bing.com": emptyRss, "api.gdeltproject.org": JSON.stringify({}) });
r = await S.searchAll("software engineer AI", "en", 30, true, { cache: new MemCache(), now: NOW });
assert(r.source === "Bing News" && r.items.length === 0 && r.tried.length === 3, "all empty -> empty 200");
// 8. all fail -> throws with tried
mock({ "news.google.com": 503, "www.bing.com": 403, "api.gdeltproject.org": "rate limited" });
threw = null; try { await S.searchAll("x y", "en", 30, true, { now: NOW }); } catch (e) { threw = e; }
assert(threw && threw.tried.length === 3, "all fail -> error with tried: " + JSON.stringify(threw.tried));
// 9. Google works -> uses google (regression)
const gRss = `<rss><channel><item><title>AI replaces call center jobs - Reuters</title><link>https://news.google.com/rss/articles/1</link><pubDate>${day(1)}</pubDate><source url="https://reuters.com">Reuters</source></item></channel></rss>`;
mock({ "news.google.com": gRss });
r = await S.searchAll("call center AI", "en", 30, true, { now: NOW });
assert(r.source === "Google News" && r.items[0].t === "AI replaces call center jobs" && r.items[0].src === "Reuters", "google path unchanged");

// 10. full handler with mocked caches + 502 body
globalThis.caches = { default: new MemCache() };
mock({ "news.google.com": 503, "www.bing.com": bingRss });
const ctx = u => ({ request: new Request(u), waitUntil: () => {} });
let resp = await S.onRequestGet(ctx("https://x.dev/api/search?q=software%20engineer%20AI&lang=en"));
let body = await resp.json();
assert(resp.status === 200 && body.source === "Bing News" && Array.isArray(body.tried), "handler 200 via Bing (dates are real-now relative)");
mock({ "news.google.com": 503, "www.bing.com": 503, "api.gdeltproject.org": 503 });
globalThis.caches = { default: new MemCache() };
resp = await S.onRequestGet(ctx("https://x.dev/api/search?q=nurse%20AI&lang=en"));
body = await resp.json();
assert(resp.status === 502 && body.tried.length === 3, "handler 502 lists tried");
console.log("\nALL PASS");
