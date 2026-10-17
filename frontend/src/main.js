import './assets/bootstrap.min.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fortawesome/fontawesome-svg-core/styles.css'
import './assets/style.css'
import { config } from '@fortawesome/fontawesome-svg-core'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import AppIcon from './components/AppIcon.vue'

config.autoAddCss = false
const app = createApp(App)
app.component('AppIcon', AppIcon)
app.use(createPinia())
app.use(router)
app.mount('#app')
