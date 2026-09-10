/*
 * 验证码 Service Worker —— 把页面发往 *.alicaptcha.com 的请求改写到插件反代。
 *
 * 背景：Windows 浏览器上 getSmsCode 返回 248 的唯一判别变量是验证码请求的
 * HTTP User-Agent 平台标识；浏览器规范禁止页面 JS 修改 UA，但 Service Worker
 * 可以把请求重定向到同源反代路由，由插件服务端注入 Android 画像后转发。
 * 实测依据见 DNA-analysis docs/login-248/10。
 *
 * 只透传安全头；UA/UA-CH/Cookie 一律由服务端决定（透传受限头会报错或穿帮）。
 */
'use strict';

var ALICAP_HOST_SUFFIX = 'alicaptcha.com';
var PROXY_PREFIX = '/astrbot_plugin_dna/alicap/';

self.addEventListener('install', function () {
  self.skipWaiting();
});
self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function (event) {
  var url;
  try {
    url = new URL(event.request.url);
  } catch (e) {
    return;
  }
  if (!url.hostname.endsWith(ALICAP_HOST_SUFFIX)) return;

  event.respondWith((async function () {
    var target = self.location.origin + PROXY_PREFIX + url.hostname + url.pathname + url.search;
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
