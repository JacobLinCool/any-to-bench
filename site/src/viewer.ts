import { mount } from 'svelte'
import Viewer from './Viewer.svelte'
import './app.css'
import 'katex/dist/katex.min.css'

export default mount(Viewer, { target: document.getElementById('app')! })
