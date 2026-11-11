// https://docs.expo.dev/guides/using-eslint/
const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  { ignores: ['dist/*', 'src/api/schema.d.ts'] },
  // jest.mock factories are hoisted and must require() their dependencies.
  { files: ['src/__tests__/**', 'jest.setup.ts'], rules: { '@typescript-eslint/no-require-imports': 'off', 'react/display-name': 'off' } },
]);
