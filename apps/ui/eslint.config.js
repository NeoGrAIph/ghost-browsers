import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import reactPlugin from 'eslint-plugin-react';
import hooksPlugin from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import prettierConfig from 'eslint-config-prettier';

/** @type {import('eslint').Linter.Config[]} */
const sharedPlugins = {
  '@typescript-eslint': tsPlugin,
  react: reactPlugin,
  'react-hooks': hooksPlugin,
  'jsx-a11y': jsxA11y,
};

const sharedRules = {
  ...reactPlugin.configs.recommended.rules,
  ...reactPlugin.configs['jsx-runtime'].rules,
  ...jsxA11y.configs.recommended.rules,
  'react/react-in-jsx-scope': 'off',
  'react/prop-types': 'off',
  'react-hooks/rules-of-hooks': 'error',
  'react-hooks/exhaustive-deps': 'warn',
};

const sharedSettings = {
  react: { version: 'detect' },
};

const config = [
  {
    ignores: ['dist', 'coverage', 'node_modules'],
  },
  {
    files: ['vite.config.ts'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        project: false,
      },
    },
    plugins: sharedPlugins,
    settings: sharedSettings,
    rules: {
      ...tsPlugin.configs.recommended.rules,
      ...sharedRules,
    },
  },
  {
    files: ['src/**/*.{ts,tsx}', 'src/**/?(*.)+(ts|tsx)'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        project: './tsconfig.json',
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: sharedPlugins,
    settings: sharedSettings,
    rules: {
      ...tsPlugin.configs['recommended-type-checked'].rules,
      ...sharedRules,
    },
  },
  prettierConfig,
];

export default config;
