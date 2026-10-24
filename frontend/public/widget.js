(() => {
  const script = document.currentScript;
  if (!(script instanceof HTMLScriptElement)) return;
  const publicId = script.dataset.assistantId || '';
  if (!/^[0-9a-f-]{36}$/i.test(publicId)) return;
  const asset = new URL(script.src, document.baseURI);
  // The tester credential is entered in this frame. Refuse a same-origin host
  // page because it could inspect the frame DOM despite the iframe sandbox.
  if (window.location.origin === asset.origin) {
    script.dataset.widgetState = 'same-origin-host-disallowed';
    return;
  }
  const frameUrl = new URL('/widget', asset.origin);
  frameUrl.searchParams.set('public_id', publicId);
  const root = document.createElement('div');
  root.setAttribute('data-assistant-widget', publicId);
  const button = document.createElement('button');
  button.type = 'button'; button.textContent = 'Chat'; button.setAttribute('aria-label', 'Open assistant chat');
  Object.assign(button.style, { position: 'fixed', insetInlineEnd: '20px', bottom: '20px', zIndex: '2147483000', border: '0', borderRadius: '999px', background: '#635bff', color: 'white', padding: '13px 20px', font: '600 14px system-ui,sans-serif', boxShadow: '0 4px 18px #20222c44', cursor: 'pointer' });
  const frame = document.createElement('iframe');
  frame.src = frameUrl.href; frame.title = 'AI assistant chat'; frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms');
  frame.setAttribute('allow', 'clipboard-write'); frame.hidden = true;
  Object.assign(frame.style, { position: 'fixed', insetInlineEnd: '20px', bottom: '78px', zIndex: '2147483000', width: 'min(380px, calc(100vw - 24px))', height: 'min(620px, calc(100dvh - 100px))', border: '1px solid #e7e8ef', borderRadius: '16px', background: 'white', boxShadow: '0 10px 40px #20222c33' });
  const close = () => { frame.hidden = true; button.setAttribute('aria-expanded', 'false'); button.focus(); };
  button.setAttribute('aria-expanded', 'false');
  button.addEventListener('click', () => { frame.hidden = !frame.hidden; button.setAttribute('aria-expanded', String(!frame.hidden)); if (!frame.hidden) frame.contentWindow?.focus(); });
  window.addEventListener('message', event => {
    if (event.source !== frame.contentWindow || event.origin !== asset.origin) return;
    if (event.data?.type === 'assistant-widget-close') close();
  });
  root.append(button, frame); document.body.append(root);
  const resize = () => { if (window.innerWidth <= 480) Object.assign(frame.style, { inset: '0', width: '100vw', height: '100dvh', maxHeight: 'none', borderRadius: '0' }); else Object.assign(frame.style, { inset: 'auto 20px 78px auto', width: 'min(380px, calc(100vw - 24px))', height: 'min(620px, calc(100dvh - 100px))', borderRadius: '16px' }); };
  window.addEventListener('resize', resize); resize();
})();
