export function createStatusTransport({ url, onSnapshot, onError, authMessage }) {
  let socket = null;
  let fallbackTimer = null;
  let retry = 0;
  let closed = false;

  const visible = () => document.visibilityState !== 'hidden';
  const stopFallback = () => {
    if (fallbackTimer !== null) {
      clearTimeout(fallbackTimer);
      fallbackTimer = null;
    }
  };
  const fallback = () => {
    stopFallback();
    if (closed || socket || !visible()) return;
    fallbackTimer = setTimeout(async () => {
      fallbackTimer = null;
      if (!closed && !socket && visible()) {
        try { onSnapshot(await fetch(url, { credentials: 'same-origin' }).then(r => r.json())); }
        catch (error) { onError?.(error); }
      }
      fallback();
    }, 5000);
  };
  const connect = () => {
    if (closed || socket || !visible()) return;
    try { socket = new WebSocket(url); }
    catch (error) { onError?.(error); fallback(); return; }
    socket.onopen = () => { retry = 0; stopFallback(); socket.send(JSON.stringify(authMessage)); };
    socket.onmessage = event => { try { onSnapshot(JSON.parse(event.data)); } catch (error) { onError?.(error); } };
    socket.onclose = () => { socket = null; fallback(); setTimeout(connect, Math.min(15000, 1000 * 2 ** retry++)); };
    socket.onerror = () => { try { socket.close(); } catch (_) {} };
  };
  const visibility = () => { if (visible()) { fallback(); connect(); } else stopFallback(); };
  document.addEventListener('visibilitychange', visibility);
  connect();
  return {
    close() { closed = true; stopFallback(); document.removeEventListener('visibilitychange', visibility); try { socket?.close(); } catch (_) {} socket = null; },
    reconnect() { if (!closed) { stopFallback(); socket = null; connect(); } },
  };
}
