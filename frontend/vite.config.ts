import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// `npm run dev` talks to `memo serve` on :8000, so cookies stay same-origin.
		proxy: { '/api': 'http://127.0.0.1:8000' }
	},
	test: { include: ['src/**/*.test.ts'] }
});
