# @slowboard/dev

Build and develop a Slowboard app UI.

```js
// vite.config.js
import react from "@vitejs/plugin-react";
import { slowboard } from "@slowboard/dev/vite";
export default { plugins: [react(), slowboard({ image: "slowapp-myapp:dev" })] };
```

- `slowapp build`: `dist/index.html`, one self-contained file (refused over the hub's 2 MB).
- `slowapp dev`: the app at `/__slowboard/` in the hub's sandbox, against a mock hub with the
  hub's rules. Jobs run in the app's image (`image`), with its command (`job: ["python3", "-m",
  "myapp"]`), or through `slowapp.dev.js` handlers. Contract 6: each job gets only its own
  secrets (an oauth one as a dev token, `dev-<name>-<account>`), render runs with no network,
  and a sync run's artifacts go to the next render. `secrets.connect` is faked: the chrome opens
  `/__slowboard/connect/<name>`, which connects `dev@example.com` with the provider's scopes.
- `slowapp check [file]`: the size cap, and no files the frame would have to fetch.
