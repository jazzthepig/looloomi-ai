import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],

      // ── TO ENABLE (needs one install) ──────────────────────────────────────
      // 2026-08-18: clicking "Asset Radar" produced a blank page —
      // `ReferenceError: AssetRadar is not defined`. App.jsx rendered it and
      // never imported it; the import was lost in the 227edcd split. The Vite
      // build stayed GREEN because another module lazy-imports the same
      // component, so the chunk was emitted and nothing warned.
      //
      // Base `no-undef` does NOT catch this — measured, exit 0 on a probe file.
      // The rule that does is `react/jsx-no-undef`, in eslint-plugin-react,
      // which is not installed here. Until it is, tests/test_no_undefined_jsx_components.py
      // stands in with a parser-free heuristic; it is a stopgap and says so.
      //
      //   cd dashboard && npm i -D eslint-plugin-react
      //
      // then import it above and add to this block:
      //   'react/jsx-no-undef': 'error',
    },
  },
])
