# @slowboard/app

The bridge between a Slowboard app's UI and its hub. The UI runs in a sandboxed frame with no
network; the hub's page hands it a MessagePort, and every call goes through the hub, for this app
only (protocol 1, [`protocol.json`](protocol.json)).

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

No dependencies. React hooks: `@slowboard/app-react`. Components: `@slowboard/ui`.
