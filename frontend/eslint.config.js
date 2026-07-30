import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import typescriptEslint from 'typescript-eslint';

export default typescriptEslint.config(
  { ignores: ['dist'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      typescriptEslint.configs.recommendedTypeChecked,
      typescriptEslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat['recommended-latest'],
      reactRefresh.configs.vite,
      prettier,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
);
