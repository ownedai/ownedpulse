import { useState, useEffect, useCallback, useRef } from 'react';
import { openBootstrapProgress, openRssProgress, stopBootstrapSession } from '../api/client';

// Module-level state — survives component unmount so the status bar keeps
// tracking even when the BootstrapModal is closed.
let _state = {
  sessionId: null,
  uiMode: 'idle',        // 'idle' | 'running' | 'complete'
  progress: { total: 0, processed: 0, succeeded: 0, failed: 0, skipped: 0, status: 'pending', eta_seconds: 0 },
  docEvents: [],
  stopping: false,
};
let _listeners = [];
let _esRef = null;

function notify() {
  _listeners.forEach((fn) => fn({ ..._state }));
}

export function getBootstrapProgressState() {
  return { ..._state };
}

export function subscribeBootstrapProgress(fn) {
  _listeners.push(fn);
  fn({ ..._state }); // immediate current state
  return () => {
    _listeners = _listeners.filter((f) => f !== fn);
  };
}

function closeSSE() {
  if (_esRef) {
    _esRef.close();
    _esRef = null;
  }
}

let _errorCount = 0;
const MAX_RECONNECT_ERRORS = 8; // give up after ~16s of consecutive failures

export function startBootstrapTracking(sessionId) {
  closeSSE();
  _errorCount = 0;
  _state = {
    sessionId,
    uiMode: 'running',
    progress: { total: 0, processed: 0, succeeded: 0, failed: 0, skipped: 0, status: 'running', eta_seconds: 0 },
    docEvents: [],
    stopping: false,
  };
  notify();

  const es = openBootstrapProgress(sessionId);
  _esRef = es;
  es.onmessage = (evt) => {
    _errorCount = 0; // successful message resets error streak
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'doc') {
        _state.docEvents = [msg, ..._state.docEvents].slice(0, 150);
        // Clear disconnected status on first successful doc event
        if (_state.progress.status === 'disconnected') {
          _state.progress = { ..._state.progress, status: 'running' };
        }
        notify();
      } else if (msg.type === 'progress') {
        _state.progress = {
          total: msg.total ?? _state.progress.total,
          processed: msg.processed ?? _state.progress.processed,
          succeeded: msg.succeeded ?? _state.progress.succeeded,
          failed: msg.failed ?? _state.progress.failed,
          skipped: msg.skipped ?? _state.progress.skipped,
          status: msg.status ?? _state.progress.status,
          eta_seconds: msg.eta_seconds ?? 0,
        };
        if (msg.status !== 'pending' && msg.status !== 'running') {
          _state.uiMode = 'complete';
          closeSSE();
        }
        notify();
      } else if (msg.type === 'error') {
        // Server-sent error (e.g. session not found after API restart)
        _state.uiMode = 'complete';
        _state.progress = { ..._state.progress, status: 'session_lost' };
        closeSSE();
        notify();
      }
    } catch (_) {}
  };
  es.onerror = () => {
    _errorCount += 1;
    if (_errorCount >= MAX_RECONNECT_ERRORS) {
      // Too many consecutive failures — session is likely gone
      _state.uiMode = 'complete';
      _state.progress = { ..._state.progress, status: 'disconnected' };
      closeSSE();
    } else {
      // Transient drop — mark disconnected but keep uiMode running so the
      // spinner stays visible and EventSource auto-reconnects.
      _state.progress = { ..._state.progress, status: 'disconnected' };
    }
    notify();
  };
}

export function stopBootstrapTracking() {
  if (_state.sessionId && _state.uiMode === 'running') {
    _state.stopping = true;
    notify();
    stopBootstrapSession(_state.sessionId).catch(() => {});
  }
}

export function dismissBootstrapTracking() {
  closeSSE();
  _state = { sessionId: null, uiMode: 'idle', progress: { total: 0, processed: 0, succeeded: 0, failed: 0, skipped: 0, status: 'pending', eta_seconds: 0 }, docEvents: [], stopping: false };
  notify();
}

export function useBootstrapProgress() {
  const [state, setState] = useState(_state);

  useEffect(() => {
    return subscribeBootstrapProgress(setState);
  }, []);

  const start = useCallback((sessionId) => {
    startBootstrapTracking(sessionId);
  }, []);

  const stop = useCallback(() => {
    stopBootstrapTracking();
  }, []);

  const dismiss = useCallback(() => {
    dismissBootstrapTracking();
  }, []);

  return { ...state, start, stop, dismiss };
}

// ── RSS run progress tracking (same pattern, separate SSE source) ──────────

let _rssState = {
  runId: null,
  uiMode: 'idle',
  progress: { total: 0, processed: 0, succeeded: 0, failed: 0, skipped: 0, status: 'pending', eta_seconds: 0 },
  docEvents: [],
};
let _rssListeners = [];
let _rssEsRef = null;
let _rssErrorCount = 0;

function rssNotify() {
  _rssListeners.forEach((fn) => fn({ ..._rssState }));
}

export function subscribeRssProgress(fn) {
  _rssListeners.push(fn);
  fn({ ..._rssState });
  return () => { _rssListeners = _rssListeners.filter((f) => f !== fn); };
}

function closeRssSSE() {
  if (_rssEsRef) { _rssEsRef.close(); _rssEsRef = null; }
}

export function startRssTracking(runId) {
  closeRssSSE();
  _rssErrorCount = 0;
  _rssState = {
    runId,
    uiMode: 'running',
    progress: { total: 0, processed: 0, succeeded: 0, failed: 0, skipped: 0, status: 'running', eta_seconds: 0 },
    docEvents: [],
  };
  rssNotify();

  const es = openRssProgress(runId);
  _rssEsRef = es;
  es.onmessage = (evt) => {
    _rssErrorCount = 0;
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'doc') {
        _rssState.docEvents = [msg, ..._rssState.docEvents].slice(0, 150);
        rssNotify();
      } else if (msg.type === 'progress') {
        _rssState.progress = {
          total: msg.total ?? _rssState.progress.total,
          processed: msg.processed ?? _rssState.progress.processed,
          succeeded: msg.succeeded ?? _rssState.progress.succeeded,
          failed: msg.failed ?? _rssState.progress.failed,
          skipped: msg.skipped ?? _rssState.progress.skipped,
          status: msg.status ?? _rssState.progress.status,
          eta_seconds: msg.eta_seconds ?? 0,
        };
        if (msg.status !== 'pending' && msg.status !== 'running') {
          _rssState.uiMode = 'complete';
          closeRssSSE();
        }
        rssNotify();
      } else if (msg.type === 'error') {
        _rssState.uiMode = 'complete';
        _rssState.progress = { ..._rssState.progress, status: 'session_lost' };
        closeRssSSE();
        rssNotify();
      }
    } catch (_) {}
  };
  es.onerror = () => {
    _rssErrorCount += 1;
    if (_rssErrorCount >= 8) {
      _rssState.uiMode = 'complete';
      _rssState.progress = { ..._rssState.progress, status: 'disconnected' };
      closeRssSSE();
    } else {
      _rssState.progress = { ..._rssState.progress, status: 'disconnected' };
    }
    rssNotify();
  };
}

export function stopRssTracking() {
  closeRssSSE();
  _rssState.uiMode = 'complete';
  rssNotify();
}

export function useRssProgress(runId) {
  const [state, setState] = useState(_rssState);

  useEffect(() => {
    return subscribeRssProgress(setState);
  }, []);

  useEffect(() => {
    if (runId && _rssState.runId !== runId) {
      startRssTracking(runId);
    }
    return () => {
      if (_rssState.runId === runId) {
        closeRssSSE();
      }
    };
  }, [runId]);

  return state;
}
