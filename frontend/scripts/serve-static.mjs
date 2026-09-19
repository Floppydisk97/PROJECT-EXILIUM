// A static file server with no dependencies, for looking at the built site locally and for
// the container image. The site is a folder of files now -- there is no Next server to run,
// which is the entire point of the change -- but `npm start` and `docker run` should still
// show you the planet without asking you to install anything.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const ROOT = new URL("../out/", import.meta.url).pathname;
const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOSTNAME ?? "0.0.0.0";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png",
  ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8",
  // The planet. Deliberately an opaque type: naming it gzip here would make the browser
  // unpack it, and the client unpacks it itself.
  ".bin": "application/octet-stream",
};

createServer((request, response) => {
  // normalize() plus the prefix check is what stops `GET /../../etc/passwd`.
  const path = decodeURIComponent((request.url ?? "/").split("?")[0]);
  let file = normalize(join(ROOT, path));
  if (!file.startsWith(ROOT)) return send(response, 403, "Forbidden");
  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
  if (!existsSync(file)) {
    file = join(ROOT, "404.html");
    if (!existsSync(file)) return send(response, 404, "Not found");
    response.statusCode = 404;
  }
  response.setHeader("Content-Type", TYPES[extname(file)] ?? "application/octet-stream");
  createReadStream(file).pipe(response);
}).listen(PORT, HOST, () => console.log(`static site on http://${HOST}:${PORT}`));

function send(response, status, body) {
  response.statusCode = status;
  response.end(body);
}
