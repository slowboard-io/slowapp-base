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
 * Changes from elsewhere arrive on their own. Saves go one at a time, each over the last one's
 * revision, so a quick second save (or `prev => next`) builds on the first. A conflict rejects the
 * saves queued behind it too (they never saw the other writer's value); later saves build on it.
 */
export function useDoc(name, initial = null) {
  const app = useApp();
  const [doc, setDoc] = useState({ rev: 0, value: initial, loading: true });
  const [status, setStatus] = useState({ saving: false, error: null, conflict: false });
  const cur = useRef(doc); // the latest doc, ahead of the next render
  const queue = useRef(Promise.resolve());
  const pending = useRef(0);
  const conflicts = useRef({ n: 0, error: null }); // a save queued before the nth conflict fails with it
  const show = (d) => { cur.current = d; setDoc(d); };
  useEffect(() => {
    let live = true;
    app.docs.get(name).then(
      // A watched change may have landed first: keep whichever revision is newer.
      (d) => live && show(d.rev >= cur.current.rev ? { rev: d.rev, value: d.value ?? initial, loading: false } : { ...cur.current, loading: false }),
      (error) => live && (show({ ...cur.current, loading: false }), setStatus((s) => ({ ...s, error }))),
    );
    const off = app.docs.watch(name, (d) => {
      if (d.rev > cur.current.rev) show({ rev: d.rev, value: d.value ?? initial, loading: false });
    });
    return () => { live = false; off(); };
  }, [app, name]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useCallback((next) => {
    pending.current += 1;
    setStatus({ saving: true, error: null, conflict: false });
    const seen = conflicts.current.n;
    const one = queue.current.then(async () => {
      if (conflicts.current.n !== seen) {
        const { error } = conflicts.current;
        setStatus({ saving: --pending.current > 0, error, conflict: true });
        throw error;
      }
      const base = cur.current;
      const value = typeof next === "function" ? next(base.value) : next;
      show({ ...base, value }); // optimistic
      try {
        const { rev } = await app.docs.put(name, value, base.rev);
        show({ rev, value, loading: false });
        if (--pending.current === 0) setStatus({ saving: false, error: null, conflict: false });
        return rev;
      } catch (error) {
        if (error.code === "conflict") {
          conflicts.current = { n: conflicts.current.n + 1, error };
          show({ rev: error.rev, value: error.value ?? initial, loading: false });
        } else show(base);
        setStatus({ saving: --pending.current > 0, error, conflict: error.code === "conflict" });
        throw error;
      }
    });
    queue.current = one.catch(() => {});
    return one;
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

/**
 * Which secrets are set (never their values), and set/clear/connect: {status, set, clear, connect,
 * busy}. Protocol 2: status follows `secret` events (a sign-in finishing, another tab), and
 * connect(name) starts an oauth sign-in (the outcome arrives as one of those events).
 */
export function useSecrets() {
  const app = useApp();
  const [status, setStatus] = useState(app.info.secrets || []);
  const [busy, setBusy] = useState(false);
  useEffect(() => app.secrets.watch?.(({ event, ...s }) => {
    setStatus((p) => (p.some((x) => x.name === s.name) ? p.map((x) => (x.name === s.name ? s : x)) : [...p, s]));
  }), [app]);
  const wrap = (f) => async (...a) => {
    setBusy(true);
    try { const r = await f(...a); setStatus(await app.secrets.status()); return r; } finally { setBusy(false); }
  };
  return {
    status,
    isSet: (name) => status.some((s) => s.name === name && s.set),
    set: useCallback(wrap(app.secrets.set), [app]), // eslint-disable-line react-hooks/exhaustive-deps
    clear: useCallback(wrap(app.secrets.clear), [app]), // eslint-disable-line react-hooks/exhaustive-deps
    connect: useCallback(wrap(app.secrets.connect), [app]), // eslint-disable-line react-hooks/exhaustive-deps
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
