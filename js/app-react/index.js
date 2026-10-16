// @slowboard/app-react: React hooks over @slowboard/app.
//
//   <AppProvider fallback={<p>Connecting…</p>}><Tags /></AppProvider>
//
//   function Tags() {
//     const [tags, saveTags, { saving, error }] = useDoc("tags", {});
//     const sync = useJob("sync");
//     return <button disabled={sync.running} onClick={() => sync.run()}>Sync now</button>;
//   }

import { connect } from "@slowboard/app";
import { createContext, createElement, useCallback, useContext, useEffect, useRef, useState } from "react";

const Ctx = createContext(null);

/**
 * Connects to the hub once, applies its theme to <html>, keeps the frame as tall as the page,
 * then renders `children` with the app in context. Until then: `fallback`; on failure:
 * `onError(error)` or a short message.
 */
export function AppProvider({ children, fallback = null, onError, autoResize = true, applyTheme = true, connectOptions }) {
  const [state, setState] = useState({ app: null, error: null });
  useEffect(() => {
    let stop = [];
    let live = true;
    connect(connectOptions).then(
      (app) => {
        if (!live) return;
        if (applyTheme) stop.push(app.applyTheme());
        if (autoResize) stop.push(app.ui.autoResize());
        setState({ app, error: null });
      },
      (error) => live && setState({ app: null, error }),
    );
    return () => { live = false; stop.forEach((f) => f()); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (state.error) return onError ? onError(state.error) : createElement("p", { role: "alert" }, `Can't reach the hub: ${state.error.message}`);
  if (!state.app) return fallback;
  return createElement(Ctx.Provider, { value: state.app }, children);
}

/** The connected app (@slowboard/app): app.info, app.ui, app.call(…). */
export function useApp() {
  const app = useContext(Ctx);
  if (!app) throw new Error("useApp: wrap the UI in <AppProvider>");
  return app;
}

/**
 * One hub-stored doc. Returns [value, save, {rev, loading, saving, error, conflict}].
 * `save(next)` takes a value or `prev => next` and writes over the revision last seen. If someone
 * else (a job, another tab) wrote first, the hub refuses it: the hook takes their version,
 * sets `conflict`, and `save` rejects with code "conflict" so the caller can retry on top.
 * Changes from elsewhere arrive on their own.
 */
export function useDoc(name, initial = null) {
  const app = useApp();
  const [doc, setDoc] = useState({ rev: 0, value: initial, loading: true });
  const [status, setStatus] = useState({ saving: false, error: null, conflict: false });
  const cur = useRef(doc);
  cur.current = doc;
  useEffect(() => {
    let live = true;
    app.docs.get(name).then(
      (d) => live && setDoc({ rev: d.rev, value: d.value ?? initial, loading: false }),
      (error) => live && (setDoc((p) => ({ ...p, loading: false })), setStatus((s) => ({ ...s, error }))),
    );
    const off = app.docs.watch(name, (d) => {
      if (d.rev > cur.current.rev) setDoc({ rev: d.rev, value: d.value ?? initial, loading: false });
    });
    return () => { live = false; off(); };
  }, [app, name]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useCallback(async (next) => {
    const base = cur.current;
    const value = typeof next === "function" ? next(base.value) : next;
    setStatus({ saving: true, error: null, conflict: false });
    setDoc({ ...base, value }); // optimistic
    try {
      const { rev } = await app.docs.put(name, value, base.rev);
      setDoc({ rev, value, loading: false });
      setStatus({ saving: false, error: null, conflict: false });
      return rev;
    } catch (error) {
      if (error.code === "conflict") setDoc({ rev: error.rev, value: error.value ?? initial, loading: false });
      else setDoc(base);
      setStatus({ saving: false, error, conflict: error.code === "conflict" });
      throw error;
    }
  }, [app, name]); // eslint-disable-line react-hooks/exhaustive-deps
  return [doc.value, save, { rev: doc.rev, loading: doc.loading, ...status }];
}

/** The app's settings: [values, save, {schema, saving, errors}]. A refused save sets `errors` per field. */
export function useSettings() {
  const app = useApp();
  const [values, setValues] = useState(app.info.settings || {});
  const [status, setStatus] = useState({ saving: false, errors: null });
  const save = useCallback(async (next) => {
    setStatus({ saving: true, errors: null });
    try {
      const v = await app.settings.set(next);
      setValues(v);
      setStatus({ saving: false, errors: null });
      return v;
    } catch (e) {
      setStatus({ saving: false, errors: e.errors || { "": e.message } });
      throw e;
    }
  }, [app]);
  return [values, save, { schema: app.info.settings_schema || {}, ...status }];
}

/** Which secrets are set (never their values), and set/clear: {status, set, clear, busy}. */
export function useSecrets() {
  const app = useApp();
  const [status, setStatus] = useState(app.info.secrets || []);
  const [busy, setBusy] = useState(false);
  const wrap = (f) => async (...a) => {
    setBusy(true);
    try { await f(...a); setStatus(await app.secrets.status()); } finally { setBusy(false); }
  };
  return {
    status,
    isSet: (name) => status.some((s) => s.name === name && s.set),
    set: useCallback(wrap(app.secrets.set), [app]), // eslint-disable-line react-hooks/exhaustive-deps
    clear: useCallback(wrap(app.secrets.clear), [app]), // eslint-disable-line react-hooks/exhaustive-deps
    busy,
  };
}

/** One job: {run(args), running, result, error, last}. `last` is the whole reply. */
export function useJob(name) {
  const app = useApp();
  const [s, setS] = useState({ running: false, result: null, error: null, last: null });
  const run = useCallback(async (args = {}) => {
    setS((p) => ({ ...p, running: true, error: null }));
    try {
      const last = await app.jobs.run(name, args);
      setS({ running: false, result: last.result, error: last.ok ? null : new Error(last.message || last.outcome), last });
      return last;
    } catch (error) {
      setS((p) => ({ ...p, running: false, error }));
      throw error;
    }
  }, [app, name]);
  return { run, ...s };
}

/** The app's runs as they happen (from any cause): the jobs running now, and the last run event. */
export function useRuns() {
  const app = useApp();
  const [s, setS] = useState({ running: [], last: null });
  useEffect(() => app.events.runs((e) => setS((p) => ({
    last: e,
    running: e.phase === "started" ? [...p.running.filter((j) => j !== e.job), e.job] : p.running.filter((j) => j !== e.job),
  }))), [app]);
  return s;
}

/** The hub's theme: {theme: "light"|"dark", tokens}. */
export function useTheme() {
  const app = useApp();
  const [t, setT] = useState({ theme: app.info.theme, tokens: app.info.tokens });
  useEffect(() => app.onTheme(setT), [app]);
  return t;
}
