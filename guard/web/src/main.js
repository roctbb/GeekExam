import { createApp } from "vue";
import { config } from "@fortawesome/fontawesome-svg-core";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fortawesome/fontawesome-svg-core/styles.css";
import App from "./App.vue";
import "./style.css";

config.autoAddCss = false;
createApp(App).mount("#app");
