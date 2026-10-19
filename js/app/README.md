# @slowboard/app

The bridge between a Slowboard app's UI and its hub. The UI runs in a sandboxed frame with no
network; the hub's page hands it a MessagePort, and every call goes through the hub, for this app
only (protocol 2, [`protocol.json`](protocol.json)). The handshake still says protocol 1, so
protocol 1 bundles keep connecting; this client says 2 in its `connect` call, and `app.protocol`
is what the hub agreed (1 from an older hub).

```js
import { connect } from "@slowboard/app";

const app = await connect();          // waits for the hub's page (rejects "no_hub" after 10 s)
app.applyTheme();                     // the hub's colours, now and on every change
app.ui.autoResize();                  // the frame follows the page's height

const { rev, value } = await app.docs.get("tags");
try {
  await app.docs.put("tags", { ...value, work: "important" }, rev);
} catch (e) {
  if (e.code === "conflict") { /* e.rev, e.value: someone else wrote first */ }
}
const r = await app.jobs.run("sync", {});   // {run, outcome, ok, exit, result, message}
```

Secrets (protocol 2, contract 6): `app.secrets.status()` says, per secret, its `kind` (`value` or
`oauth`), whether it's set, when it was last used, and for a sign-in its scopes, date and
accounts, never a value. `set(name, value)` stores a value; `connect(name)` starts a sign-in, which
the hub's page opens at top level (the frame never sees the provider's URL, code or state) and
whose outcome arrives as a `secret` event (`app.secrets.watch(f)`); `clear(name, account?)` clears
a value or disconnects. The ready-made fields are `<sb-secret-field>` and `<sb-connect>` in
`@slowboard/ui/secrets`.

No dependencies. React hooks: `@slowboard/app-react`. Components: `@slowboard/ui`.
