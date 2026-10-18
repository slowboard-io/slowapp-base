import react from "@vitejs/plugin-react";
import { slowboard } from "@slowboard/dev/vite";

// `npm run dev`: the app at /__slowboard/ in the hub's sandbox, against a mock hub. Its jobs run
// for real in the app's image when SLOWAPP_IMAGE names one (e.g. after `docker build -t
// slowapp-example:dev ..`), otherwise with python3 here (needs Pillow). `npm run build`:
// dist/index.html, one file, which the Dockerfile copies to /ui/index.html.
const image = process.env.SLOWAPP_IMAGE;

export default {
  plugins: [
    react(),
    slowboard(image ? { image } : { job: ["python3", "-m", "moon"], env: { PYTHONPATH: "..:../../kit" } }),
  ],
};
