/*
 * 验证码 Service Worker —— 把页面发往 *.alicaptcha.com 的请求改写到插件反代。
 *
 * 背景：Windows 浏览器上 getSmsCode 返回 248 的唯一判别变量是验证码请求的
 * HTTP User-Agent 平台标识；浏览器规范禁止页面 JS 修改 UA，但 Service Worker
 * 可以把请求重定向到同源反代路由，由插件服务端注入 Android 画像后转发。
 * 实测依据见 DNA-analysis docs/login-248/10。
 *
 * 只透传安全头；UA/UA-CH/Cookie 一律由服务端决定（透传受限头会报错或穿帮）。
 * 反代地址携带当前登录会话 auth：服务端只对仍然有效的会话转发，匿名或过期
 * 会话不会产生任何上游流量，因此这里必须先解析出受控登录页的 auth。
 */
'use strict';

// 与服务端 UPSTREAM_HOSTS 保持一致，避免两套安全边界漂移。
var ALICAP_HOSTS = [
  'captcha.alicaptcha.com',
  'captchabak.alicaptcha.com',
  'static.alicaptcha.com',
];
var LOGIN_PAGE_RE = /\/dna\/i\/([^/?#]+)/;

self.addEventListener('install', function () {
  self.skipWaiting();
});
self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

// 从受控登录页 URL 解析出会话 auth 与插件基址。
function sessionFromUrl(raw) {
  if (typeof raw !== 'string') return null;
  var match = LOGIN_PAGE_RE.exec(raw);
  if (!match) return null;
  return { auth: match[1], base: raw.slice(0, match.index) };
}

async function resolveSession(event) {
  if (!event.clientId) return null;
  var client = await self.clients.get(event.clientId);
  return client ? sessionFromUrl(client.url) : null;
}

self.addEventListener('fetch', function (event) {
  var url;
  try {
    url = new URL(event.request.url);
  } catch (e) {
    return;
  }
  if (ALICAP_HOSTS.indexOf(url.hostname) === -1) return;

  event.respondWith((async function () {
    var session;
    try {
      session = await resolveSession(event);
    } catch (e) {
      session = null;
    }
    if (!session) {
      // 无法确认登录会话时不做任何改写，避免变成匿名单跳中继。
      return new Response('captcha proxy requires an active login session', {
        status: 403,
      });
    }
    var target =
      session.base + '/alicap/' + session.auth + '/' + url.hostname + url.pathname + url.search;
    var passHeaders = {};
    for (var k of ['accept', 'accept-language', 'content-type']) {
      var v = event.request.headers.get(k);
      if (v) passHeaders[k] = v;
    }
    var init = { method: event.request.method, headers: passHeaders, redirect: 'follow' };
    if (event.request.method !== 'GET' && event.request.method !== 'HEAD') {
      init.body = await event.request.arrayBuffer();
    }
    try {
      return await fetch(target, init);
    } catch (e) {
      return new Response('captcha proxy unavailable: ' + e, { status: 502 });
    }
  })());
});
