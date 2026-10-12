// CarPlay TV — статичный веб-плеер + прокси для M3U-плейлистов (обход CORS)
const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = process.env.PORT || 3000;
const PUBLIC = path.join(__dirname, "public");
const MAX_BYTES = 30 * 1024 * 1024;

const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webmanifest": "application/manifest+json",
};

async function proxyPlaylist(req, res, target) {
  let url;
  try {
    url = new URL(target);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error();
  } catch {
    res.writeHead(400, { "content-type": "text/plain; charset=utf-8" });
    return res.end("Неверная ссылка на плейлист");
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch(url, {
      signal: ctrl.signal,
      headers: { "user-agent": "Mozilla/5.0 (iPhone) CarPlayTV/1.0" },
      redirect: "follow",
    });
    if (!r.ok) {
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      return res.end(`Источник ответил ошибкой ${r.status}`);
    }
    const reader = r.body.getReader();
    const chunks = [];
    let size = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_BYTES) throw new Error("too big");
      chunks.push(value);
    }
    res.writeHead(200, {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    });
    res.end(Buffer.concat(chunks));
  } catch (e) {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(e.message === "too big" ? "Плейлист слишком большой" : "Не удалось скачать плейлист");
  } finally {
    clearTimeout(timer);
  }
}

http
  .createServer((req, res) => {
    const u = new URL(req.url, "http://x");
    if (u.pathname === "/api/playlist") return proxyPlaylist(req, res, u.searchParams.get("url") || "");
    if (u.pathname === "/health") return res.end("ok");

    let p = path.normalize(decodeURIComponent(u.pathname)).replace(/^(\.\.[/\\])+/, "");
    if (p === "/" || p === "\\") p = "/index.html";
    const file = path.join(PUBLIC, p);
    if (!file.startsWith(PUBLIC)) {
      res.writeHead(403);
      return res.end();
    }
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404);
        return res.end("Not found");
      }
      res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" });
      res.end(data);
    });
  })
  .listen(PORT, () => console.log("CarPlay TV on :" + PORT));
