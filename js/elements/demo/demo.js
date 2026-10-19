// The demo's script: the moon bundle from its catalog.json, the theme from ?theme=dark.
import "../dist/slowboard-elements.js";

const dark = new URLSearchParams(location.search).get("theme") === "dark";
if (dark) document.documentElement.dataset.theme = "dark";
const moon = document.getElementById("moon");
moon.setAttribute("theme", dark ? "dark" : "light");
moon.catalog = await (await fetch("../test/moon/catalog.json")).json();
for (const ev of ["slowapp-card", "slowapp-size"]) document.addEventListener(ev, (e) => console.log(ev, JSON.stringify(e.detail)));
