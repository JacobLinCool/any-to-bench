import { mount } from 'svelte'
import App from './App.svelte'
import './app.css'
import 'katex/dist/katex.min.css'

export default mount(App, { target: document.getElementById('app')! })
