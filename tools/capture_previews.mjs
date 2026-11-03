#!/usr/bin/env node
// Capture only the generated synthetic demo. No dependency install or private reports.
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const html = await readFile(join(root, 'docs/preview.html'), 'utf8');
if (!html.includes('Fictional models and synthetic scores. Not benchmark results.')) throw Error('Generate the synthetic preview first');
const profile = await mkdtemp(join(tmpdir(), 'modelprune-preview-'));
let browser, socket;
try {
  browser = spawn(process.env.CHROMIUM_BIN || 'chromium', [
    '--headless', '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
    '--disable-component-update', '--disable-extensions', '--remote-debugging-port=0',
    '--remote-allow-origins=http://localhost', '--user-data-dir=' + profile, 'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe'] });
  const endpoint = await new Promise((resolve, reject) => {
    let buffer = '';
    const timer = setTimeout(() => reject(Error('Chromium startup timed out')), 20000);
    browser.once('error', error => { clearTimeout(timer); reject(error); });
    browser.stderr.on('data', chunk => {
      buffer += chunk;
      const match = buffer.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
    browser.once('exit', code => { clearTimeout(timer); reject(Error('Chromium exited ' + code)); });
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const value = JSON.parse(event.data);
    if (pending.has(value.id)) {
      const {resolve, reject, timer} = pending.get(value.id); pending.delete(value.id); clearTimeout(timer);
      value.error ? reject(Error(JSON.stringify(value.error))) : resolve(value.result);
    }
  };
  function send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(Error(method + ' timed out')); }, 15000);
      pending.set(id, {resolve, reject, timer});
      socket.send(JSON.stringify({id, method, params, ...(sessionId ? {sessionId} : {})}));
    });
  }
  const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
  const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
  const command = (method, params = {}) => send(method, params, sessionId);
  await command('Page.enable');
  await command('Network.enable');
  await command('Network.setBlockedURLs', {urls: ['http://*', 'https://*']});
  await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1200, deviceScaleFactor: 1, mobile: false});
  await command('Page.navigate', {url: pathToFileURL(join(root, 'docs/preview.html')).href});
  const evaluate = async expression => {
    const result = await command('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  for (let tries = 0; tries < 100; tries++) {
    if (await evaluate('document.readyState === "complete" && !!document.querySelector("#radar-svg polygon")')) break;
    if (tries === 99) throw Error('Radar did not render');
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  await evaluate('document.fonts.ready.then(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true)))))');
  const destination = join(root, 'docs/images');
  await mkdir(destination, {recursive: true});
  const overview = await command('Page.captureScreenshot', {format: 'png'});
  await writeFile(join(destination, 'report-overview.png'), Buffer.from(overview.data, 'base64'));
  await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1040, deviceScaleFactor: 1, mobile: false});
  await evaluate('scrollTo(0,document.getElementById("models-generative").getBoundingClientRect().top+scrollY-24)');
  await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))');
  const tables = await command('Page.captureScreenshot', {format: 'png'});
  await writeFile(join(destination, 'model-comparison.png'), Buffer.from(tables.data, 'base64'));
  console.log('Wrote two preview screenshots from synthetic demo');
} finally {
  socket?.close();
  if (browser && browser.exitCode === null) {
    browser.kill('SIGTERM');
    await new Promise(resolve => { browser.once('exit', resolve); setTimeout(resolve, 5000).unref(); });
    if (browser.exitCode === null) browser.kill('SIGKILL');
  }
  await rm(profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 200});
}
