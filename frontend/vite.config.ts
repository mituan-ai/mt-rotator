import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
    plugins: [react(), tailwindcss()],
    build: { chunkSizeWarningLimit: 550 },
    server: {
        port: 3000,
        proxy: {
            '/api': 'http://127.0.0.1:8000',
            '/django-static': 'http://127.0.0.1:8000'
        }
    },
    test: {
        environment: 'jsdom',
        setupFiles: './tests/setup.ts',
        restoreMocks: true,
        exclude: ['e2e/**', 'node_modules/**', 'dist/**']
    }
})
