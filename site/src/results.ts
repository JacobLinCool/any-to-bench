import { mount } from 'svelte'
import Results from './Results.svelte'
import './app.css'

export default mount(Results, { target: document.getElementById('app')! })
