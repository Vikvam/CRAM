import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** Static build, served by FastAPI (PLAN 5). Every route falls back to index.html. */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: false }),
		alias: { '@memo/answer-check': 'packages/answer-check/index.ts' }
	}
};

export default config;
