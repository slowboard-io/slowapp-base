# @slowboard/ui

React components that look like the Slowboard hub around them: slowboard.io's tokens
(`tokens.css`, unchanged) and its four fonts (Chivo, Press Start 2P, Silkscreen, VT323; SIL OFL
1.1, see `fonts/LICENSE.md`), inlined into the app's single-file bundle.

`Stack`, `Row`, `Title`, `Hint`, `Card`, `Button`, `Field`, `TextInput`, `Toggle`, `Segmented`,
`List`, `ListItem`, `KeyCap`, `Num`, `Notice`. Importing the module brings in `ui.css`.

## Secrets: `<sb-secret-field>` and `<sb-connect>`

Two framework-free custom elements for an app's secrets (bridge protocol 2, contract 6), in
`@slowboard/ui/secrets` (also re-exported from the package's index):

```js
import { connect } from "@slowboard/app";
import { setApp } from "@slowboard/ui/secrets";
const app = await connect();
setApp(app);              // or el.app = app, per element (React 19: <sb-connect app={app} …/>)
```

```html
<sb-secret-field name="ai_key"></sb-secret-field>
<sb-connect name="google"></sb-connect>
```

- `<sb-secret-field name [label]>`: a value. A masked input and Save while it isn't set; a chip
  "Set · used 3 h ago", Replace and Clear once it is. What's typed goes to the hub
  (`secrets.set`) and the input is emptied; the element never holds or shows a value.
- `<sb-connect name [label]>`: an OAuth sign-in. Connect; once connected, a chip with the date,
  the scopes granted, the account (with `multiple`, each account with its own Disconnect, and
  Add an account) and Disconnect. The hub's page runs the sign-in; the element follows the
  `secret` event, and shows the hub's link in case no window opened.

Clear and Disconnect ask first through the hub's dialog (`ui.confirm`). Events: `sb-secret`
`{name, status}` after a change, `sb-connect-url` `{name, url}`. Shadow DOM with one constructed
stylesheet, no inline script or style, no network, as `@slowboard/elements`: they run under the
hub's CSP. Colours and fonts come from the host's tokens (`tokens.css`, or `app.applyTheme()`).
